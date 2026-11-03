"""The Fixer turns a set of failing verdicts into actionable feedback.

It does not regenerate anything itself — it produces the instruction set the
generator consumes on its next pass, so the generator fixes only what failed.
"""

from __future__ import annotations

from .config import WONDER_MODEL
from .contracts import Verdict


def build_feedback(verdicts: list[Verdict]) -> str:
    lines = []
    for v in verdicts:
        if not v.passed:
            hint = f" FIX: {v.fix_hint}" if v.fix_hint else ""
            lines.append(f"- [{v.check}] {v.reason}{hint}")
    return "\n".join(lines)


ARBITER_INSTRUCTIONS = (
    "You are the Tier-3 escalation arbitrator of a multimodal verification system. "
    "The automated critics could not repair an artifact after several attempts. "
    "Given the SOURCE OF TRUTH and the failing checks (with reasons), produce ONE "
    "precise, prioritized repair instruction for the generator that fixes ALL the "
    "failures at once without breaking what already passes. Return ONLY the "
    "instruction text, no preamble."
)


def arbitrate(client, failing_verdicts: list[Verdict], run_input: dict, target: str,
              model: str = WONDER_MODEL) -> str:
    """Deep-reasoning repair instruction from Muse Wonder (reasoning model)."""
    lines = [f"SOURCE OF TRUTH:\n{run_input.get('source_truth', '')}",
             f"BRIEF:\n{run_input.get('brief', '')}",
             f"\nFAILING CHECKS (artifact = {target}):"]
    for v in failing_verdicts:
        lines.append(f"- {v.check}: {v.reason} (hint: {v.fix_hint})")
    text, _ = client.respond_text(
        model, "\n".join(lines), instructions=ARBITER_INSTRUCTIONS, reasoning_effort="low")
    return text.strip()
