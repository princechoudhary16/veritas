"""The Fixer turns a set of failing verdicts into actionable feedback.

It does not regenerate anything itself — it produces the instruction set the
generator consumes on its next pass, so the generator fixes only what failed.
"""

from __future__ import annotations

from .contracts import Verdict


def build_feedback(verdicts: list[Verdict]) -> str:
    lines = []
    for v in verdicts:
        if not v.passed:
            hint = f" FIX: {v.fix_hint}" if v.fix_hint else ""
            lines.append(f"- [{v.check}] {v.reason}{hint}")
    return "\n".join(lines)
