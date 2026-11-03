"""The verdict contract — the thing that makes the loop deterministic.

Every critic, no matter what it checks, returns the same structured Verdict.
The orchestrator only ever reasons over Verdicts, never over free prose.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass


@dataclass
class Verdict:
    check: str          # name of the check, e.g. "claim_support"
    passed: bool        # did the artifact pass this check?
    score: float        # 0.0 - 1.0 confidence / quality score
    reason: str         # human-readable justification (cite the fault)
    fix_hint: str = ""  # actionable instruction the Fixer can consume

    def to_dict(self) -> dict:
        return asdict(self)


def parse_verdict(check: str, raw_text: str) -> Verdict:
    """Parse a critic's raw model output into a Verdict, failing closed.

    If the critic returns anything we can't parse, we treat it as a FAIL with a
    fix_hint telling it to return strict JSON — the loop never silently passes.
    """
    obj = _extract_json(raw_text)
    if obj is None:
        return Verdict(
            check=check,
            passed=False,
            score=0.0,
            reason=f"Critic returned unparseable output: {raw_text[:160]!r}",
            fix_hint="Return a strict JSON object with keys pass, score, reason, fix_hint.",
        )
    return Verdict(
        check=check,
        passed=bool(obj.get("pass", obj.get("passed", False))),
        score=float(obj.get("score", 0.0) or 0.0),
        reason=str(obj.get("reason", "")).strip(),
        fix_hint=str(obj.get("fix_hint", "")).strip(),
    )


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?", "", t).strip()
    t = re.sub(r"```$", "", t).strip()
    try:
        return json.loads(t)
    except Exception:
        match = re.search(r"\{.*\}", t, re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                return None
    return None
