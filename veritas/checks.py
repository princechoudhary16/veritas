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
    object_count_critic, scene_plausibility_critic, text_legibility_critic,
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
    "reading_level": 0.0,
    "required_terms": 0.0,
    "text_legibility": 0.012,
    "z3_constraint": 0.0,
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


def _count_syllables(word: str) -> int:
    word = re.sub(r"[^a-z]", "", word.lower())
    if not word:
        return 0
    vowels = "aeiouy"
    count, prev_vowel = 0, False
    for ch in word:
        is_vowel = ch in vowels
        if is_vowel and not prev_vowel:
            count += 1
        prev_vowel = is_vowel
    if word.endswith("e") and count > 1:
        count -= 1
    return max(1, count)


def flesch_reading_ease(text: str) -> float:
    """Flesch Reading Ease (higher = easier). ~60+ is plain language."""
    words = re.findall(r"[A-Za-z]+", text)
    sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    if not words or not sentences:
        return 0.0
    nw, ns = len(words), len(sentences)
    syllables = sum(_count_syllables(w) for w in words)
    return 206.835 - 1.015 * (nw / ns) - 84.6 * (syllables / nw)


def _reading_level(copy: str, min_score: float) -> Verdict:
    fre = flesch_reading_ease(copy)
    if fre < min_score:
        return Verdict("reading_level", False, round(max(fre, 0.0) / max(min_score, 1), 2),
                       f"Flesch Reading Ease {fre:.0f} is below the {min_score:.0f} plain-language bar.",
                       "Use shorter words and shorter sentences to raise readability.")
    return Verdict("reading_level", True, 1.0,
                   f"Flesch Reading Ease {fre:.0f} meets the {min_score:.0f} plain-language bar.", "")


def _required_terms(copy: str, all_terms: list, any_terms: list) -> Verdict:
    low = copy.lower()
    missing = [t for t in all_terms if t.lower() not in low]
    has_any = (not any_terms) or any(t.lower() in low for t in any_terms)
    if missing:
        return Verdict("required_terms", False, 0.0,
                       f"Missing required text: {', '.join(missing)}.",
                       f"Add: {', '.join(missing)}.")
    if not has_any:
        return Verdict("required_terms", False, 0.0,
                       f"Must include at least one of: {', '.join(any_terms)}.",
                       f"Add one of: {', '.join(any_terms)}.")
    return Verdict("required_terms", True, 1.0, "All required text present.", "")


def _z3_constraint(copy: str, extract: dict, asserts: list) -> Verdict:
    """Neuro-symbolic gate: extract numbers from the copy, then formally verify
    policy constraints with the Z3 SMT solver.

    `extract` maps a variable name to a regex with one integer capture group;
    `asserts` is a list of comparison expressions over those variables that must
    all hold. Only assertions whose variables were found in the copy are checked
    (a missing number is not a numeric violation). The verdict is a formal proof,
    not an LLM opinion.
    """
    from z3 import And, Int, Not, Solver, sat

    env, extracted = {}, {}
    for name, pattern in (extract or {}).items():
        match = re.search(pattern, copy)
        value = None
        if match:
            try:
                value = int(match.group(1))
            except (ValueError, IndexError):
                value = None
        env[name] = Int(name)
        extracted[name] = value

    usable = []
    for a in (asserts or []):
        names = [n for n in env if n in a]
        if names and all(extracted.get(n) is not None for n in names):
            try:
                usable.append((a, eval(a, {"__builtins__": {}}, env)))  # Z3 BoolRef
            except Exception:
                continue

    if not usable:
        return Verdict("z3_constraint", True, 1.0,
                       "No numeric claims present to formally verify.", "")

    solver = Solver()
    for name, value in extracted.items():
        if value is not None:
            solver.add(env[name] == value)
    solver.add(Not(And(*[expr for _, expr in usable])))
    if solver.check() == sat:  # a satisfying assignment violates the constraint
        failed = [a for a, _ in usable if not _eval_python(a, extracted)]
        return Verdict("z3_constraint", False, 0.0,
                       f"Z3 disproved a stated claim: {', '.join(failed) or 'constraint unsatisfied'} "
                       f"(extracted {extracted}).",
                       "Correct the stated numbers to satisfy the policy's formal constraints.")
    return Verdict("z3_constraint", True, 1.0,
                   f"Z3 formally verified {len(usable)} numeric constraint(s): {extracted}.", "")


def _eval_python(expr: str, values: dict) -> bool:
    env = {k: v for k, v in values.items() if v is not None}
    try:
        return bool(eval(expr, {"__builtins__": {}}, env))
    except Exception:
        return True


async def run_check(check, provider, artifacts: dict, run_input: dict, critic_provider=None) -> Verdict:
    """Run one check and return a Verdict labelled with the check's declared name.

    Text-only semantic critics (claim_support, brand_tone) run on
    ``critic_provider`` when one is supplied (hybrid routing to an inference
    partner); everything else stays on ``provider`` (Meta).
    """
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
            claim_support_critic, critic_provider or provider, artifacts.get("copy", ""),
            run_input.get("source_truth", ""))
    elif t == "brand_tone":
        v = await asyncio.to_thread(
            brand_critic, critic_provider or provider, artifacts.get("copy", ""), p.get("rules", ""))
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
    elif t == "reading_level":
        v = _reading_level(artifacts.get("copy", ""), float(p.get("min", 60)))
    elif t == "required_terms":
        v = _required_terms(artifacts.get("copy", ""), p.get("all", []), p.get("any", []))
    elif t == "text_legibility":
        v = await asyncio.to_thread(
            text_legibility_critic, provider, artifacts.get("image_b64", ""))
    elif t == "z3_constraint":
        v = _z3_constraint(artifacts.get("copy", ""), p.get("extract", {}), p.get("asserts", []))
    else:
        v = Verdict(check.name, False, 0.0, f"Unknown check type '{t}'.", "")

    v.check = check.name  # distinguish multiple checks that share a type
    return v
