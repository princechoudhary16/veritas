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
    box_data = {"image": result["image"], "detections": dets, "object": target_object}

    if not dets:
        return Verdict("grounding", False, 0.0,
                       f"SAM 3.1 found no '{target_object}' in the generated image.",
                       f"Place a clearly visible, prominent {target_object} as the foreground subject.",
                       data=box_data)

    max_area = max(d["area_frac"] for d in dets)
    box_data["max_area_frac"] = max_area
    if max_area < min_area_frac:
        return Verdict("grounding", False, round(max_area / min_area_frac, 2),
                       f"'{target_object}' present but too small "
                       f"({max_area * 100:.1f}% of frame; need >= {min_area_frac * 100:.0f}%).",
                       f"Make the {target_object} larger and the clear focal subject.",
                       data=box_data)

    return Verdict("grounding", True, 1.0,
                   f"SAM 3.1 confirms '{target_object}' present and prominent "
                   f"({max_area * 100:.1f}% of frame, {len(dets)} instance(s)).",
                   "", data=box_data)


BRAND_CRITIC_INSTRUCTIONS = (
    "You are a brand compliance reviewer, independent of the writer.\n"
    "Given BRAND RULES and ad COPY, judge whether the copy obeys the rules: "
    "tone, length, and any banned words or claims.\n"
    "Respond with ONLY a JSON object, no other text:\n"
    '{"pass": true/false, "score": 0.0-1.0, '
    '"reason": "cite any violation, or confirm compliant", '
    '"fix_hint": "specific instruction to fix the copy"}'
)


def brand_critic(client, copy: str, brand_rules: str, effort: str = "low") -> Verdict:
    payload = f"BRAND RULES:\n{brand_rules}\n\nCOPY:\n{copy}"
    text, _ = client.respond_text(
        TEXT_MODEL, payload, instructions=BRAND_CRITIC_INSTRUCTIONS, reasoning_effort=effort
    )
    return parse_verdict("brand", text)


CONSISTENCY_CRITIC_INSTRUCTIONS = (
    "You are a cross-modal consistency reviewer. You are given ad COPY and the "
    "campaign IMAGE. Judge whether the image CONTRADICTS the copy.\n"
    "A FAIL is a clear contradiction: a different product, a dominant colour "
    "that conflicts with the colour the copy emphasises, or a scene that "
    "conflicts with the copy. Listing options the image does not all show is "
    "NOT a contradiction, and generic marketing language is fine.\n"
    "Respond with ONLY a JSON object, no other text:\n"
    '{"pass": true/false, "score": 0.0-1.0, '
    '"reason": "cite the contradiction, or confirm consistent", '
    '"fix_hint": "how to change the IMAGE so it matches the copy"}'
)


def consistency_critic(client, copy: str, image_b64: str, effort: str = "low") -> Verdict:
    data_uri = "data:image/webp;base64," + image_b64
    inp = [{
        "role": "user",
        "content": [
            {"type": "input_text", "text": "COPY:\n" + copy},
            {"type": "input_image", "image_url": data_uri},
        ],
    }]
    text, _ = client.respond_text(
        TEXT_MODEL, inp, instructions=CONSISTENCY_CRITIC_INSTRUCTIONS, reasoning_effort=effort
    )
    return parse_verdict("consistency", text)


def object_count_critic(
    client, image_b64: str, obj: str, min_count: int = 1, max_count: int = 999
) -> Verdict:
    """Spatial check: SAM 3.1 counts instances of `obj` and gates on [min, max].

    Used by the synthetic-data gate for object density / occlusion control.
    """
    data_uri = "data:image/webp;base64," + image_b64
    text, _ = client.segment(obj, data_uri)
    result = parse_sam_output(text)
    n = result["count"]
    box_data = {"image": result["image"], "detections": result["detections"], "object": obj}

    if n < min_count:
        return Verdict("object_count", False, round(n / max(min_count, 1), 2),
                       f"SAM 3.1 counted {n} '{obj}'(s); need at least {min_count}.",
                       f"Include at least {min_count} clearly visible {obj}(s).",
                       data=box_data)
    if n > max_count:
        return Verdict("object_count", False, round(max_count / max(n, 1), 2),
                       f"SAM 3.1 counted {n} '{obj}'(s); at most {max_count} allowed.",
                       f"Reduce to at most {max_count} {obj}(s) in view.",
                       data=box_data)
    return Verdict("object_count", True, 1.0,
                   f"SAM 3.1 counted {n} '{obj}'(s), within [{min_count}, {max_count}].",
                   "", data=box_data)


SCENE_PLAUSIBILITY_INSTRUCTIONS = (
    "You are a synthetic-data QA reviewer for a robot-perception training set. "
    "You are given REQUIREMENTS and an IMAGE. Judge whether the image is a "
    "physically plausible, clean training sample that matches the requirements.\n"
    "FAIL on rendering artifacts, warped or impossible geometry, floating or "
    "merged objects, nonsensical physics, or a scene that does not match the "
    "requirements.\n"
    "Respond with ONLY a JSON object, no other text:\n"
    '{"pass": true/false, "score": 0.0-1.0, '
    '"reason": "cite the artifact/implausibility, or confirm plausible", '
    '"fix_hint": "how to change the IMAGE to be plausible and on-spec"}'
)


def scene_plausibility_critic(client, image_b64: str, rubric: str, effort: str = "low") -> Verdict:
    data_uri = "data:image/webp;base64," + image_b64
    inp = [{
        "role": "user",
        "content": [
            {"type": "input_text", "text": "REQUIREMENTS:\n" + rubric},
            {"type": "input_image", "image_url": data_uri},
        ],
    }]
    text, _ = client.respond_text(
        TEXT_MODEL, inp, instructions=SCENE_PLAUSIBILITY_INSTRUCTIONS, reasoning_effort=effort
    )
    return parse_verdict("scene_plausibility", text)
