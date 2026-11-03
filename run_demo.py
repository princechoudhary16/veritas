"""End-to-end demo of the Veritas text-verification loop.

Run:
    set -a; source .env; set +a
    python run_demo.py

The brief tempts the writer to embellish; the claim-support critic catches any
unsupported claim and the loop auto-fixes it until the copy is provably backed
by the product facts.
"""

import textwrap

from veritas.config import load_api_key
from veritas.critics import claim_support_critic
from veritas.meta_client import MetaClient
from veritas.orchestrator import run_text_loop, write_ledger

BRIEF = (
    "Write a punchy, confident ad for the HydroPeak water bottle, aimed at "
    "serious outdoor enthusiasts. Make it sound premium and trustworthy."
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


def _banner(title: str) -> None:
    print("\n" + "=" * 72 + f"\n {title}\n" + "=" * 72)


def main() -> None:
    client = MetaClient(load_api_key())

    _banner("VERITAS — self-verifying copy loop")
    print("Brief:", BRIEF)
    print("\nSource of truth:\n" + textwrap.indent(SOURCE_TRUTH, "   "))

    def on_event(kind, n, payload):
        if kind == "generated":
            print(f"\n--- iteration {n}: generated draft ---")
            print(textwrap.indent(payload, "   "))
        elif kind == "verified":
            for v in payload:
                mark = "PASS" if v.passed else "FAIL"
                print(f"   [{mark}] {v.check} (score {v.score:.2f}) -- {v.reason}")
                if not v.passed and v.fix_hint:
                    print(f"          -> {v.fix_hint}")

    result = run_text_loop(
        client, BRIEF, SOURCE_TRUTH, [claim_support_critic], on_event=on_event
    )

    _banner("RESULT")
    print(f"Passed: {result.passed} | iterations: {len(result.iterations)} "
          f"| stopped: {result.stopped_reason}")
    print(f"Credits spent this run: ${result.spend_usd:.4f}")
    print("\nFinal verified copy:\n" + textwrap.indent(result.final_artifact, "   "))

    path = write_ledger(result)
    print("\nAudit ledger written to:", path)


if __name__ == "__main__":
    main()
