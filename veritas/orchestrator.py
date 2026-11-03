"""The orchestrator — the closed loop and its safety rails.

    generate -> verify -> (pass? ship : fix) -> repeat

Bounded by max_iters and a hard spend budget. Every iteration is recorded in
an append-only audit trail, which is both the product's guarantee and the
demo's proof.
"""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Callable

from .config import DEFAULT_BUDGET_USD, DEFAULT_MAX_ITERS
from .fixer import build_feedback
from .generators import generate_copy


@dataclass
class Iteration:
    n: int
    artifact: str
    verdicts: list
    passed: bool
    spend_after: float


@dataclass
class LoopResult:
    passed: bool
    stopped_reason: str
    final_artifact: str
    spend_usd: float
    iterations: list = field(default_factory=list)


def run_text_loop(
    client,
    brief: str,
    source_truth: str,
    critics: list[Callable],
    *,
    max_iters: int = DEFAULT_MAX_ITERS,
    budget_usd: float = DEFAULT_BUDGET_USD,
    generate: Callable = generate_copy,
    on_event: Callable | None = None,
) -> LoopResult:
    iterations: list[Iteration] = []
    feedback: str | None = None
    artifact = ""
    stopped = "max_iters_reached"

    for n in range(1, max_iters + 1):
        # --- budget guard: fail closed before spending more ---
        if client.usage.spend_usd >= budget_usd:
            stopped = "budget_exceeded"
            break

        artifact = generate(client, brief, source_truth, feedback=feedback)
        if on_event:
            on_event("generated", n, artifact)

        verdicts = [critic(client, artifact, source_truth) for critic in critics]
        passed = all(v.passed for v in verdicts)
        iterations.append(
            Iteration(n, artifact, [v.to_dict() for v in verdicts], passed,
                      round(client.usage.spend_usd, 6))
        )
        if on_event:
            on_event("verified", n, verdicts)

        if passed:
            stopped = "passed"
            break
        feedback = build_feedback(verdicts)

    return LoopResult(
        passed=bool(iterations and iterations[-1].passed),
        stopped_reason=stopped,
        final_artifact=artifact,
        spend_usd=round(client.usage.spend_usd, 6),
        iterations=[asdict(i) for i in iterations],
    )


def run_image_loop(
    client,
    scene_prompt: str,
    critics: list[Callable],
    *,
    max_iters: int = DEFAULT_MAX_ITERS,
    budget_usd: float = DEFAULT_BUDGET_USD,
    out_dir: str = "out",
    generate: Callable | None = None,
    on_event: Callable | None = None,
) -> LoopResult:
    """Closed loop for image artifacts, verified with grounding critics.

    Each critic is a callable (client, image_b64) -> Verdict. Generated images
    are saved to `out_dir`; the ledger records paths, never raw base64.
    """
    from .generators import generate_scene_image

    generate = generate or generate_scene_image
    os.makedirs(out_dir, exist_ok=True)
    iterations: list[Iteration] = []
    feedback: str | None = None
    img_path = ""
    stopped = "max_iters_reached"

    for n in range(1, max_iters + 1):
        if client.usage.spend_usd >= budget_usd:
            stopped = "budget_exceeded"
            break

        b64 = generate(client, scene_prompt, feedback=feedback)
        img_path = os.path.join(out_dir, f"iter_{n}.webp")
        with open(img_path, "wb") as f:
            f.write(base64.b64decode(b64))
        if on_event:
            on_event("generated", n, img_path)

        verdicts = [critic(client, b64) for critic in critics]
        passed = all(v.passed for v in verdicts)
        iterations.append(
            Iteration(n, img_path, [v.to_dict() for v in verdicts], passed,
                      round(client.usage.spend_usd, 6))
        )
        if on_event:
            on_event("verified", n, verdicts)

        if passed:
            stopped = "passed"
            break
        feedback = build_feedback(verdicts)

    return LoopResult(
        passed=bool(iterations and iterations[-1].passed),
        stopped_reason=stopped,
        final_artifact=img_path,
        spend_usd=round(client.usage.spend_usd, 6),
        iterations=[asdict(i) for i in iterations],
    )


def write_ledger(result: LoopResult, path_dir: str = "runs") -> str:
    """Persist the full audit trail as JSON. This is the 'proof' artifact."""
    os.makedirs(path_dir, exist_ok=True)
    path = os.path.join(path_dir, f"run_{int(time.time())}.json")
    with open(path, "w") as f:
        json.dump(asdict(result), f, indent=2, default=str)
    return path
