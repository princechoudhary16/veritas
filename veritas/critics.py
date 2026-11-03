"""Critics — independent adversarial judges.

A critic has a narrow mandate and returns a structured Verdict. It is a
*separate* model invocation from the generator (separation of powers): the
model that writes the copy never also certifies it.
"""

from __future__ import annotations

from .config import TEXT_MODEL
from .contracts import Verdict, parse_verdict
from .sam import parse_sam_output

CLAIM_CRITIC_INSTRUCTIONS = (
    "You are a strict advertising fact-checker, independent of the writer.\n"
    "You are given PRODUCT FACTS and an ad COPY. Identify every factual or "
    "feature claim the copy makes (materials, certifications, capacities, "
    "guarantees, performance numbers, safety claims).\n"
    "A claim PASSES only if it is directly supported by PRODUCT FACTS. "
    "Generic marketing adjectives with no factual content (e.g. 'rugged', "
    "'beautiful') are allowed. Any factual claim NOT supported by the facts "
    "is a FAIL.\n"
    "Respond with ONLY a JSON object, no other text:\n"
    '{"pass": true/false, "score": 0.0-1.0, '
    '"reason": "cite each unsupported claim, or confirm all claims supported", '
    '"fix_hint": "specific instruction to fix the copy"}'
)


def claim_support_critic(client, copy: str, source_truth: str, effort: str = "low") -> Verdict:
    payload = f"PRODUCT FACTS:\n{source_truth}\n\nCOPY:\n{copy}"
    text, _ = client.respond_text(
        TEXT_MODEL, payload, instructions=CLAIM_CRITIC_INSTRUCTIONS, reasoning_effort=effort
    )
    return parse_verdict("claim_support", text)


def grounding_critic(
    client, image_b64: str, target_object: str, min_area_frac: float = 0.04
) -> Verdict:
    """Grounded visual check: is the product actually present, and prominent?

    Uses SAM 3.1 as independent pixel-level evidence rather than an LLM's
    opinion. Fails if the object is absent, or present but smaller than
    `min_area_frac` of the frame.
    """
    data_uri = "data:image/webp;base64," + image_b64
    text, _ = client.segment(target_object, data_uri)
    result = parse_sam_output(text)
    dets = result["detections"]

    if not dets:
        return Verdict(
            check="grounding",
            passed=False,
            score=0.0,
            reason=f"SAM 3.1 found no '{target_object}' in the generated image.",
            fix_hint=f"Place a clearly visible, prominent {target_object} as the foreground subject.",
        )

    max_area = max(d["area_frac"] for d in dets)
    if max_area < min_area_frac:
        return Verdict(
            check="grounding",
            passed=False,
            score=round(max_area / min_area_frac, 2),
            reason=(
                f"'{target_object}' present but too small "
                f"({max_area * 100:.1f}% of frame; need >= {min_area_frac * 100:.0f}%)."
            ),
            fix_hint=f"Make the {target_object} larger and the clear focal subject.",
        )

    return Verdict(
        check="grounding",
        passed=True,
        score=1.0,
        reason=(
            f"SAM 3.1 confirms '{target_object}' present and prominent "
            f"({max_area * 100:.1f}% of frame, {len(dets)} instance(s))."
        ),
        fix_hint="",
    )
