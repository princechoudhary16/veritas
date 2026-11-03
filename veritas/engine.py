"""The verification engine — an async, tiered DAG with short-circuiting.

Loop: generate the artifacts a policy declares, verify them tier by tier, and
if a cheap tier fails, short-circuit (skip the expensive semantic court) and
route the failures back to the artifact that owns them so the Fixer regenerates
only what broke. Bounded by max_iters and a hard spend budget; every run emits a
cryptographic receipt.

The generate -> critique -> repair loop is Self-Refine (Madaan et al., 2023) /
Reflexion (Shinn et al., 2023); independent tiered critics are the separation of
powers that guards against LLM-as-judge bias (Zheng et al., 2023).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
from dataclasses import asdict, dataclass, field

from .checks import run_check
from .fixer import build_feedback
from .generators import edit_scene_image, generate_copy, generate_scene_image
from .receipt import build_receipt

# Which artifacts each check reads — the basis for content-addressable caching.
_CHECK_DEPS = {
    "banned_terms": ("copy",), "max_sentences": ("copy",), "reading_level": ("copy",),
    "required_terms": ("copy",), "claim_support": ("copy",), "brand_tone": ("copy",),
    "grounding": ("image",), "object_count": ("image",), "text_legibility": ("image",),
    "scene_plausibility": ("image",), "consistency": ("copy", "image"),
}


def _artifact_hashes(artifacts: dict) -> dict:
    h = {}
    if artifacts.get("copy") is not None:
        h["copy"] = hashlib.sha256(artifacts["copy"].encode("utf-8")).hexdigest()[:16]
    if artifacts.get("image_b64"):
        h["image"] = hashlib.sha256(artifacts["image_b64"].encode("utf-8")).hexdigest()[:16]
    return h


def _cache_key(check, hashes: dict):
    deps = _CHECK_DEPS.get(check.type, ("copy", "image"))
    return (check.name,) + tuple(hashes.get(d, "") for d in deps)


@dataclass
class Iteration:
    n: int
    artifacts: dict
    verdicts: list
    passed: bool
    spend_after: float
    tiers_run: list
    skipped: list
    cached: list


@dataclass
class EngineResult:
    policy: str
    passed: bool
    stopped_reason: str
    spend_usd: float
    final: dict
    receipt: dict
    iterations: list = field(default_factory=list)


def _failures_for_target(verdicts, checks, target):
    name_to_target = {c.name: c.target for c in checks}
    return [v for v in verdicts if not v.passed and name_to_target.get(v.check) == target]


async def run_engine(policy, run_input: dict, provider, *, critic_provider=None,
                     surgical_repair=False, out_dir="out", on_event=None) -> EngineResult:
    checks = policy.checks
    tiers = sorted({c.tier for c in checks})
    os.makedirs(out_dir, exist_ok=True)

    artifacts: dict = {}
    cache: dict = {}  # content-addressable: verdicts keyed by (check, artifact hashes)
    feedback = {"copy": None, "image": None}
    iterations: list[Iteration] = []
    stopped = "max_iters_reached"

    for n in range(1, policy.max_iters + 1):
        if provider.usage.spend_usd >= policy.budget_usd:
            stopped = "budget_exceeded"
            break

        # --- generation: only (re)make artifacts that are missing or flagged ---
        if "copy" in policy.produces and (artifacts.get("copy") is None or feedback["copy"]):
            artifacts["copy"] = await asyncio.to_thread(
                generate_copy, provider, run_input["brief"], run_input["source_truth"], feedback["copy"])
        image_op = "kept"
        if "image" in policy.produces and (artifacts.get("image_b64") is None or feedback["image"]):
            if surgical_repair and artifacts.get("image_b64") and feedback["image"]:
                b64 = await asyncio.to_thread(
                    edit_scene_image, provider, artifacts["image_b64"], feedback["image"])
                image_op = "edited"
            else:
                b64 = await asyncio.to_thread(
                    generate_scene_image, provider, run_input["scene_prompt"], feedback["image"])
                image_op = "generated"
            path = os.path.join(out_dir, f"{policy.name}_iter_{n}.webp")
            with open(path, "wb") as f:
                f.write(base64.b64decode(b64))
            artifacts["image_b64"] = b64
            artifacts["image_path"] = path

        if on_event:
            on_event("generated", n, {"copy": artifacts.get("copy", ""),
                                      "image": artifacts.get("image_path", ""),
                                      "image_op": image_op})

        # --- tiered verification: short-circuit + content-addressable cache ---
        hashes = _artifact_hashes(artifacts)
        verdicts = []
        tiers_run = []
        skipped = []
        cached_names = []
        passed_all = True
        for tier in tiers:
            tier_checks = [c for c in checks if c.tier == tier]
            to_run = [c for c in tier_checks if _cache_key(c, hashes) not in cache]
            fresh = await asyncio.gather(
                *[run_check(c, provider, artifacts, run_input, critic_provider) for c in to_run])
            for c, v in zip(to_run, fresh):
                cache[_cache_key(c, hashes)] = v
            results = [cache[_cache_key(c, hashes)] for c in tier_checks]
            cached_names += [c.name for c in tier_checks if c not in to_run]
            verdicts.extend(results)
            tiers_run.append(tier)
            if on_event:
                on_event("tier", n, {"tier": tier, "verdicts": [v.to_dict() for v in results]})
            if any(not v.passed for v in results):
                passed_all = False
                skipped = [c.name for c in checks if c.tier > tier]
                break  # short-circuit: do not pay for higher tiers

        snapshot = {"copy": artifacts.get("copy", ""), "image": artifacts.get("image_path", "")}
        iterations.append(Iteration(
            n, snapshot, [v.to_dict() for v in verdicts], passed_all,
            round(provider.usage.spend_usd, 6), tiers_run, skipped, cached_names))
        if on_event:
            on_event("verified", n, {"verdicts": [v.to_dict() for v in verdicts],
                                     "skipped": skipped, "cached": cached_names})

        if passed_all:
            stopped = "passed"
            break

        feedback = {
            "copy": build_feedback(_failures_for_target(verdicts, checks, "copy")) or None,
            "image": build_feedback(_failures_for_target(verdicts, checks, "image")) or None,
        }

    final = {"copy": artifacts.get("copy", ""), "image": artifacts.get("image_path", "")}
    passed = bool(iterations and iterations[-1].passed)
    receipt = build_receipt(policy, run_input, iterations, artifacts, provider, passed, stopped,
                            critic_provider)
    if on_event:
        on_event("done", 0, {"passed": passed, "stopped": stopped,
                             "iterations": len(iterations),
                             "spend": round(provider.usage.spend_usd, 6), "receipt": receipt})

    return EngineResult(
        policy=policy.name, passed=passed, stopped_reason=stopped,
        spend_usd=round(provider.usage.spend_usd, 6), final=final, receipt=receipt,
        iterations=[asdict(i) for i in iterations])
