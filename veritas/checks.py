"""The check registry — one async entry point that runs any declared check.

Deterministic checks (banned terms, length) run in-process for free and sit in
Tier 1 alongside SAM grounding, so a cheap failure short-circuits the expensive
semantic court (Tier 2). LLM/vision checks reuse the independent critics in
veritas/critics.py, wrapped with asyncio.to_thread so a tier can fan out.
"""

from __future__ import annotations

import asyncio
import re

from .contracts import Verdict
from .critics import (
    brand_critic, claim_support_critic, consistency_critic, grounding_critic,
    object_count_critic, scene_plausibility_critic,
)

# Rough per-call cost in USD, used only to report credits saved by short-circuiting.
COST_EST = {
    "banned_terms": 0.0,
    "max_sentences": 0.0,
    "grounding": 0.003,
    "claim_support": 0.010,
    "brand_tone": 0.008,
    "consistency": 0.012,
    "object_count": 0.003,
    "scene_plausibility": 0.012,
}


def _banned_terms(copy: str, terms: list) -> Verdict:
    hits = [t for t in terms if re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", copy, re.I)]
    if hits:
        return Verdict("banned_terms", False, 0.0,
                       f"Contains banned term(s): {', '.join(hits)}.",
                       f"Remove: {', '.join(hits)}.")
    return Verdict("banned_terms", True, 1.0, "No banned terms present.", "")


def _max_sentences(copy: str, max_n: int) -> Verdict:
    body = copy.split("\n", 1)[1] if "\n" in copy else copy  # ignore the headline line
    sentences = [s for s in re.split(r"[.!?]+", body) if s.strip()]
    n = len(sentences)
    if n > max_n:
        return Verdict("max_sentences", False, round(max_n / n, 2),
                       f"Body copy has {n} sentences; limit is {max_n}.",
                       f"Tighten the body to at most {max_n} sentences.")
    return Verdict("max_sentences", True, 1.0, f"{n} sentence(s), within limit {max_n}.", "")


async def run_check(check, provider, artifacts: dict, run_input: dict) -> Verdict:
    """Run one check and return a Verdict labelled with the check's declared name."""
    t = check.type
    p = check.params or {}

    if t == "banned_terms":
        v = _banned_terms(artifacts.get("copy", ""), p.get("terms", []))
    elif t == "max_sentences":
        v = _max_sentences(artifacts.get("copy", ""), int(p.get("max", 2)))
    elif t == "grounding":
        obj = p.get("object") or run_input.get("target_object", "")
        maf = float(p.get("min_area_frac", 0.04))
        v = await asyncio.to_thread(
            grounding_critic, provider, artifacts.get("image_b64", ""), obj, maf)
    elif t == "claim_support":
        v = await asyncio.to_thread(
            claim_support_critic, provider, artifacts.get("copy", ""),
            run_input.get("source_truth", ""))
    elif t == "brand_tone":
        v = await asyncio.to_thread(
            brand_critic, provider, artifacts.get("copy", ""), p.get("rules", ""))
    elif t == "consistency":
        v = await asyncio.to_thread(
            consistency_critic, provider, artifacts.get("copy", ""),
            artifacts.get("image_b64", ""))
    elif t == "object_count":
        obj = p.get("object") or run_input.get("target_object", "")
        v = await asyncio.to_thread(
            object_count_critic, provider, artifacts.get("image_b64", ""), obj,
            int(p.get("min", 1)), int(p.get("max", 999)))
    elif t == "scene_plausibility":
        v = await asyncio.to_thread(
            scene_plausibility_critic, provider, artifacts.get("image_b64", ""),
            p.get("rubric", ""))
    else:
        v = Verdict(check.name, False, 0.0, f"Unknown check type '{t}'.", "")

    v.check = check.name  # distinguish multiple checks that share a type
    return v
