"""Cryptographic audit receipt (veritas.lock.json).

A tamper-evident manifest of a verification run: content hashes of the shipped
assets, the policy and checks that certified them, per-critic final scores, and
the economics (credits spent vs. credits saved by short-circuiting). This is the
artifact that makes "it passed" independently checkable after the fact.
"""

from __future__ import annotations

import hashlib
import os
import time

from .checks import COST_EST


def _sha256_text(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()


def _sha256_file(path: str) -> str | None:
    if not path or not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def build_receipt(policy, run_input, iterations, artifacts, provider, passed, stopped) -> dict:
    saved = 0.0
    for it in iterations:
        for name in it.skipped:
            ctype = next((c.type for c in policy.checks if c.name == name), None)
            saved += COST_EST.get(ctype, 0.0)

    final_scores = {}
    if iterations:
        for v in iterations[-1].verdicts:
            final_scores[v["check"]] = {"pass": v["passed"], "score": v["score"]}

    return {
        "veritas_version": "0.2.0",
        "policy": policy.name,
        "theme": policy.theme,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "passed": passed,
        "stopped_reason": stopped,
        "iterations": len(iterations),
        "assets": {
            "copy_sha256": _sha256_text(artifacts.get("copy", "")),
            "image_sha256": _sha256_file(artifacts.get("image_path", "")),
            "image_path": artifacts.get("image_path", ""),
        },
        "verification": {
            "checks": [
                {"name": c.name, "type": c.type, "tier": c.tier, "target": c.target}
                for c in policy.checks
            ],
            "final_scores": final_scores,
        },
        "economics": {
            "credits_spent_usd": round(provider.usage.spend_usd, 6),
            "credits_saved_by_short_circuit_usd": round(saved, 6),
            "spend_by_model": {k: round(v, 6) for k, v in provider.usage.by_model.items()},
        },
    }
