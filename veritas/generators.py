"""Generators — the part of the agent that *produces* artifacts.

Generators are deliberately dumb and willing: they write the best copy they
can. Keeping claims honest is the Verifier's job, not theirs. On a revision
pass they receive structured feedback and must fix only what failed.
"""

from __future__ import annotations

from .config import TEXT_MODEL

COPY_SYSTEM = (
    "You are a senior product copywriter. Write a product ad consisting of:\n"
    "- one headline (max 8 words)\n"
    "- exactly two sentences of body copy\n"
    "Return ONLY the ad text. No preamble, no quotes, no explanation."
)


def generate_copy(
    client,
    brief: str,
    source_truth: str,
    feedback: str | None = None,
    effort: str = "low",
) -> str:
    parts = [
        f"BRIEF:\n{brief}",
        f"\nPRODUCT FACTS (the only facts you may state as claims):\n{source_truth}",
    ]
    if feedback:
        parts.append(
            "\nREVISION REQUIRED. The previous draft failed verification. "
            "Fix exactly these problems and change nothing else:\n" + feedback
        )
    text, _ = client.respond_text(
        TEXT_MODEL, "\n".join(parts), instructions=COPY_SYSTEM, reasoning_effort=effort
    )
    return text


IMAGE_BASE_STYLE = "high-quality photo, realistic lighting, sharp focus"


def generate_scene_image(client, scene_prompt: str, feedback: str | None = None) -> str:
    """Generate one scene image with Muse Image; return its base64 (webp).

    On a revision pass the feedback (from the grounding critic) is appended to
    steer the next render toward a prominent, present product.
    """
    prompt = f"{scene_prompt}, {IMAGE_BASE_STYLE}"
    if feedback:
        prompt += ". " + feedback
    data = client.generate_image(prompt, n=1)
    return data[0].get("b64_json", "") if data else ""


def edit_scene_image(client, image_b64: str, instruction: str) -> str:
    """Surgically edit the current image per the fix instruction; return new b64.

    Used by the Fixer to repair only what a critic flagged, instead of
    regenerating the whole scene from the prompt.
    """
    data = client.edit_image(instruction, image_b64, n=1)
    return data[0].get("b64_json", "") if data else ""
