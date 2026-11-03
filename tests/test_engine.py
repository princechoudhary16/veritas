"""Engine orchestration tests — tiering, short-circuit, fix routing, receipt.

Runs entirely offline: generators and the check runner are monkeypatched, so we
test the control flow of the DAG without touching the Meta Model API.
"""

import asyncio
import base64

from veritas import engine as engine_mod
from veritas.contracts import Verdict
from veritas.engine import run_engine
from veritas.policy import Check, Policy


class _FakeUsage:
    def __init__(self):
        self.spend_usd = 0.0
        self.by_model = {}

    def add(self, model, cost):
        self.spend_usd += cost
        self.by_model[model] = self.by_model.get(model, 0.0) + cost


class _FakeProvider:
    def __init__(self):
        self.usage = _FakeUsage()


def _unique_image_gen():
    """A generate_scene_image stub that returns distinct bytes each call."""
    counter = {"i": 0}

    def gen(p, s, f=None):
        counter["i"] += 1
        return base64.b64encode(f"img{counter['i']}".encode()).decode()

    return gen


def _policy():
    return Policy(
        name="test_policy",
        checks=[
            Check(name="grounding", type="grounding", tier=1, target="image"),
            Check(name="claim_support", type="claim_support", tier=2, target="copy"),
        ],
        max_iters=4,
        budget_usd=5.0,
        produces=["copy", "image"],
    )


def test_short_circuit_fix_and_receipt(tmp_path, monkeypatch):
    state = {"grounding_calls": 0}

    async def fake_run_check(check, provider, artifacts, run_input, critic_provider=None):
        if check.name == "grounding":
            state["grounding_calls"] += 1
            ok = state["grounding_calls"] >= 2  # fails first pass, passes after a fix
            return Verdict("grounding", ok, 1.0 if ok else 0.0,
                           "image", "" if ok else "add the product")
        return Verdict("claim_support", True, 1.0, "ok", "")

    monkeypatch.setattr(engine_mod, "run_check", fake_run_check)
    monkeypatch.setattr(engine_mod, "generate_copy", lambda p, b, s, f=None: "Headline\nBody one. Body two.")
    monkeypatch.setattr(engine_mod, "generate_scene_image", _unique_image_gen())

    run_input = {"brief": "b", "source_truth": "s",
                 "target_object": "water bottle", "scene_prompt": "sc"}
    result = asyncio.run(run_engine(_policy(), run_input, _FakeProvider(), out_dir=str(tmp_path)))

    assert result.passed is True
    assert len(result.iterations) == 2
    # Tier 1 failed on iteration 1, so the Tier 2 claim_support check was skipped.
    assert result.iterations[0]["skipped"] == ["claim_support"]
    assert result.iterations[0]["passed"] is False
    # Receipt integrity: content hashes present and savings accrued from the skip.
    assert result.receipt["assets"]["copy_sha256"]
    assert result.receipt["assets"]["image_sha256"]
    assert result.receipt["economics"]["credits_saved_by_short_circuit_usd"] > 0
    assert result.receipt["passed"] is True


def test_budget_guard_stops(tmp_path, monkeypatch):
    async def always_fail(check, provider, artifacts, run_input, critic_provider=None):
        return Verdict(check.name, False, 0.0, "nope", "fix it")

    monkeypatch.setattr(engine_mod, "run_check", always_fail)
    monkeypatch.setattr(engine_mod, "generate_copy", lambda p, b, s, f=None: "Headline\nBody.")
    monkeypatch.setattr(engine_mod, "generate_scene_image",
                        lambda p, s, f=None: base64.b64encode(b"x").decode())

    provider = _FakeProvider()
    provider.usage.spend_usd = 99.0  # already over budget
    result = asyncio.run(run_engine(_policy(), {"brief": "b", "source_truth": "s",
                                                "target_object": "o", "scene_prompt": "sc"},
                                    provider, out_dir=str(tmp_path)))
    assert result.passed is False
    assert result.stopped_reason == "budget_exceeded"


def test_cache_reuses_stable_copy(tmp_path, monkeypatch):
    # Both checks are Tier 1; copy stays constant while the image is regenerated,
    # so the copy check must be served from cache on iteration 2.
    policy = Policy(
        name="cache_policy",
        checks=[
            Check(name="claim_support", type="claim_support", tier=1, target="copy"),
            Check(name="grounding", type="grounding", tier=1, target="image"),
        ],
        max_iters=4, budget_usd=5.0, produces=["copy", "image"],
    )
    state = {"grounding_calls": 0, "claim_calls": 0}

    async def fake_run_check(check, provider, artifacts, run_input, critic_provider=None):
        if check.name == "grounding":
            state["grounding_calls"] += 1
            ok = state["grounding_calls"] >= 2
            return Verdict("grounding", ok, 1.0 if ok else 0.0, "img", "" if ok else "fix image")
        state["claim_calls"] += 1
        return Verdict("claim_support", True, 1.0, "ok", "")

    monkeypatch.setattr(engine_mod, "run_check", fake_run_check)
    monkeypatch.setattr(engine_mod, "generate_copy", lambda p, b, s, f=None: "STABLE COPY")
    monkeypatch.setattr(engine_mod, "generate_scene_image", _unique_image_gen())

    result = asyncio.run(run_engine(policy, {"brief": "b", "source_truth": "s",
                                             "target_object": "o", "scene_prompt": "sc"},
                                    _FakeProvider(), out_dir=str(tmp_path)))

    assert result.passed is True
    assert len(result.iterations) == 2
    # claim_support ran once (iter 1) and was cached on iter 2 (copy unchanged).
    assert state["claim_calls"] == 1
    assert result.iterations[1]["cached"] == ["claim_support"]
    assert result.receipt["economics"]["credits_saved_by_cache_usd"] > 0


def test_surgical_repair_edits_instead_of_regenerating(tmp_path, monkeypatch):
    policy = Policy(
        name="surg_policy",
        checks=[Check(name="grounding", type="grounding", tier=1, target="image")],
        max_iters=4, budget_usd=5.0, produces=["image"],
    )
    state = {"grounding_calls": 0}

    async def fake_run_check(check, provider, artifacts, run_input, critic_provider=None):
        state["grounding_calls"] += 1
        ok = state["grounding_calls"] >= 2
        return Verdict("grounding", ok, 1.0 if ok else 0.0, "img", "" if ok else "add the product")

    calls = {"gen": 0, "edit": 0}
    monkeypatch.setattr(engine_mod, "run_check", fake_run_check)
    monkeypatch.setattr(engine_mod, "generate_scene_image",
                        lambda p, s, f=None: (calls.__setitem__("gen", calls["gen"] + 1)
                                              or base64.b64encode(f"g{calls['gen']}".encode()).decode()))
    monkeypatch.setattr(engine_mod, "edit_scene_image",
                        lambda p, img, instr: (calls.__setitem__("edit", calls["edit"] + 1)
                                               or base64.b64encode(f"e{calls['edit']}".encode()).decode()))

    result = asyncio.run(run_engine(
        policy, {"brief": "b", "source_truth": "s", "target_object": "o", "scene_prompt": "sc"},
        _FakeProvider(), surgical_repair=True, out_dir=str(tmp_path)))

    assert result.passed is True
    assert calls["gen"] == 1   # first image generated from scratch
    assert calls["edit"] == 1  # the fix was a surgical edit, not a regeneration


def test_arbiter_escalates_after_threshold(tmp_path, monkeypatch):
    policy = Policy(
        name="arb_policy",
        checks=[Check(name="grounding", type="grounding", tier=1, target="image")],
        max_iters=5, budget_usd=5.0, produces=["image"],
    )
    state = {"g": 0}

    async def fake_run_check(check, provider, artifacts, run_input, critic_provider=None):
        state["g"] += 1
        ok = state["g"] >= 3
        return Verdict("grounding", ok, 1.0 if ok else 0.0, "img", "" if ok else "add product")

    calls = {"arb": 0}
    monkeypatch.setattr(engine_mod, "run_check", fake_run_check)
    monkeypatch.setattr(engine_mod, "arbitrate",
                        lambda client, verdicts, run_input, target, model=None:
                        (calls.__setitem__("arb", calls["arb"] + 1) or f"fix {target}"))
    monkeypatch.setattr(engine_mod, "generate_scene_image", _unique_image_gen())

    result = asyncio.run(run_engine(
        policy, {"brief": "b", "source_truth": "s", "target_object": "o", "scene_prompt": "sc"},
        _FakeProvider(), arbiter=True, escalate_after=2, out_dir=str(tmp_path)))

    assert result.passed is True
    # iter 1 fails (n<2, plain feedback); iter 2 fails (n>=2 -> arbiter); iter 3 passes.
    assert calls["arb"] == 1
