"""DPO preference-pair extraction from audit ledgers (no network)."""

import json

from veritas.dpo import build_dpo_pairs


def _write_run(runs_dir, name, passed, copies):
    iters = [{"n": i + 1, "artifacts": {"copy": c, "image": ""}} for i, c in enumerate(copies)]
    (runs_dir / name).write_text(json.dumps({"policy": "demo", "passed": passed, "iterations": iters}))


def test_pairs_from_repaired_run(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    _write_run(runs, "engine_demo_1.json", True, ["bad draft", "bad draft", "good final"])
    pairs = build_dpo_pairs(str(runs), str(tmp_path / "policies"))
    assert len(pairs) == 1
    assert pairs[0]["rejected"] == "bad draft"
    assert pairs[0]["chosen"] == "good final"


def test_no_pair_when_copy_never_changed(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    _write_run(runs, "engine_demo_1.json", True, ["same", "same"])
    assert build_dpo_pairs(str(runs), str(tmp_path / "policies")) == []


def test_failed_run_excluded(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    _write_run(runs, "engine_demo_1.json", False, ["a", "b"])
    assert build_dpo_pairs(str(runs), str(tmp_path / "policies")) == []
