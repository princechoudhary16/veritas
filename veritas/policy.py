"""Declarative verification policies ("Policy Packs").

A policy is a hot-swappable contract: it declares what artifacts to produce and
the tiered checks that must pass before anything ships. The same engine runs any
policy, so the product is a verification *protocol*, not a single app. This is
the Constitutional-AI idea (Bai et al., 2022) made operational: principles live
in data, not in code.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import yaml

# Check types the engine knows how to run (see veritas/checks.py).
KNOWN_TYPES = {
    "banned_terms",    # deterministic, no API call
    "max_sentences",   # deterministic, no API call
    "grounding",       # SAM 3.1 spatial grounding
    "claim_support",   # Muse Spark fact-check
    "brand_tone",      # Muse Spark brand compliance
    "consistency",     # Muse Spark vision cross-modal check
}


@dataclass
class Check:
    name: str
    type: str
    tier: int = 2            # 1 = cheap/deterministic+spatial gate, 2 = semantic court
    target: str = "copy"     # which artifact this check judges: copy | image
    params: dict = field(default_factory=dict)


@dataclass
class Policy:
    name: str
    description: str = ""
    theme: str = ""
    brief: str = ""
    source_truth: str = ""
    target_object: str = ""
    scene_prompt: str = ""
    produces: list = field(default_factory=lambda: ["copy", "image"])
    checks: list = field(default_factory=list)
    max_iters: int = 6
    budget_usd: float = 5.0


def load_policy(path: str) -> Policy:
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    checks = []
    for c in raw.get("checks", []):
        merged = {"tier": 2, "target": "copy", "params": {}}
        merged.update(c)
        checks.append(Check(**merged))
    limits = raw.get("limits", {}) or {}
    policy = Policy(
        name=raw["name"],
        description=raw.get("description", ""),
        theme=raw.get("theme", ""),
        brief=raw.get("brief", ""),
        source_truth=raw.get("source_truth", ""),
        target_object=raw.get("target_object", ""),
        scene_prompt=raw.get("scene_prompt", ""),
        produces=raw.get("produces", ["copy", "image"]),
        checks=checks,
        max_iters=int(limits.get("max_iters", 6)),
        budget_usd=float(limits.get("budget_usd", 5.0)),
    )
    validate_policy(policy)
    return policy


def validate_policy(policy: Policy) -> None:
    if not policy.name:
        raise ValueError("policy is missing a name")
    if not policy.checks:
        raise ValueError(f"policy '{policy.name}' declares no checks")
    for c in policy.checks:
        if c.type not in KNOWN_TYPES:
            raise ValueError(
                f"policy '{policy.name}': unknown check type '{c.type}' in '{c.name}'. "
                f"Known types: {sorted(KNOWN_TYPES)}"
            )
        if c.target not in ("copy", "image"):
            raise ValueError(
                f"policy '{policy.name}': check '{c.name}' target must be 'copy' or 'image'"
            )
        if c.tier < 1:
            raise ValueError(f"policy '{policy.name}': check '{c.name}' tier must be >= 1")
