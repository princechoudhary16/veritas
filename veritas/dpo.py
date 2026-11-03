"""Turn the audit ledger into a self-improving flywheel.

Every run where Veritas rejected a first draft and shipped a repaired one is a
verified preference pair (rejected, chosen). Exporting those pairs as a DPO
(Direct Preference Optimization) dataset lets you post-train the generator to
stop making the mistakes the verifier keeps catching — so the guardrail makes
itself less necessary over time.

    python -m veritas.dpo        # writes veritas_dpo.jsonl from runs/
"""

from __future__ import annotations

import glob
import json
import os


def _prompt_for(policy_name: str, policies_dir: str) -> str:
    try:
        from .policy import load_policy
        for path in glob.glob(os.path.join(policies_dir, "*.yaml")):
            pol = load_policy(path)
            if pol.name == policy_name:
                return (pol.brief.strip() + "\n\nFACTS:\n" + pol.source_truth.strip()).strip()
    except Exception:
        pass
    return ""


def build_dpo_pairs(runs_dir: str = "runs", policies_dir: str = "policies") -> list:
    """Scan saved runs and emit {prompt, rejected, chosen} preference pairs."""
    pairs = []
    for path in sorted(glob.glob(os.path.join(runs_dir, "engine_*.json"))):
        try:
            data = json.load(open(path))
        except Exception:
            continue
        if not data.get("passed"):
            continue
        copies = []
        for it in data.get("iterations", []):
            art = it.get("artifacts", {})
            copy = art.get("copy", "") if isinstance(art, dict) else ""
            if copy and (not copies or copies[-1] != copy):
                copies.append(copy)
        if len(copies) < 2:  # need a rejected draft and a different accepted one
            continue
        pairs.append({
            "prompt": _prompt_for(data.get("policy", ""), policies_dir),
            "policy": data.get("policy", ""),
            "rejected": copies[0],
            "chosen": copies[-1],
        })
    return pairs


def export_jsonl(pairs: list, path: str) -> str:
    with open(path, "w") as f:
        for p in pairs:
            f.write(json.dumps(p) + "\n")
    return path


if __name__ == "__main__":
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pairs = build_dpo_pairs(os.path.join(root, "runs"), os.path.join(root, "policies"))
    out = export_jsonl(pairs, os.path.join(root, "veritas_dpo.jsonl"))
    print(f"Wrote {len(pairs)} preference pair(s) to {out}")
