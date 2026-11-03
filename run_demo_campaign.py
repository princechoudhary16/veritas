"""End-to-end demo of the full Veritas campaign loop.

Run:
    set -a; source .env; set +a
    python run_demo_campaign.py

Produces a verified campaign (copy + image) judged by four independent critics:
claim-support and brand (copy), SAM grounding and cross-modal consistency
(image). The scene prompt deliberately omits the product, so the grounding and
consistency critics catch it and the loop fixes the image while keeping the
fact-checked copy.
"""

import textwrap

from veritas.config import load_api_key
from veritas.meta_client import MetaClient
from veritas.orchestrator import run_campaign_loop, write_ledger

BRIEF = (
    "Create a premium, confident ad for the HydroPeak water bottle aimed at "
    "serious outdoor enthusiasts."
)

SOURCE_TRUTH = textwrap.dedent(
    """\
    Product: HydroPeak water bottle
    Material: stainless steel
    Capacity: 750 ml
    Keeps drinks cold for 24 hours
    Dishwasher safe
    Colors: slate grey, forest green
    Price: $29
    """
)

TARGET_OBJECT = "water bottle"

BRAND_RULES = (
    "Tone: confident, premium, concise. At most two sentences of body copy. "
    "Banned words: cheap, guarantee, #1, best ever. No unverified superlatives."
)

# No bottle in the scene on purpose -> the visual critics must catch it.
SCENE_PROMPT = "an alpine hiking trail at golden hour with dramatic mountains"


def _banner(title: str) -> None:
    print("\n" + "=" * 72 + f"\n {title}\n" + "=" * 72)


def main() -> None:
    client = MetaClient(load_api_key())

    _banner("VERITAS — full campaign loop (copy + image, 4 critics)")
    print("Brief:", BRIEF)

    def on_event(kind, n, payload):
        if kind == "generated":
            print(f"\n--- iteration {n}: generated campaign ---")
            print("   copy:")
            print(textwrap.indent(payload["copy"], "      "))
            print("   image:", payload["image"])
        elif kind == "verified":
            for v in payload:
                mark = "PASS" if v.passed else "FAIL"
                print(f"   [{mark}] {v.check} (score {v.score:.2f}) -- {v.reason}")
                if not v.passed and v.fix_hint:
                    print(f"          -> {v.fix_hint}")

    result = run_campaign_loop(
        client, BRIEF, SOURCE_TRUTH, TARGET_OBJECT, BRAND_RULES,
        scene_prompt=SCENE_PROMPT, on_event=on_event,
    )

    _banner("RESULT")
    print(f"Passed: {result.passed} | iterations: {len(result.iterations)} "
          f"| stopped: {result.stopped_reason}")
    print(f"Credits spent this run: ${result.spend_usd:.4f}")
    print("\nFinal verified campaign:")
    print(textwrap.indent(result.final_artifact["copy"], "   "))
    print("   image:", result.final_artifact["image"])

    path = write_ledger(result)
    print("\nAudit ledger written to:", path)


if __name__ == "__main__":
    main()
