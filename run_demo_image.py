"""End-to-end demo of the Veritas grounded-visual loop.

Run:
    set -a; source .env; set +a
    python run_demo_image.py

The first scene prompt omits the product, so SAM 3.1 finds no water bottle and
the grounding critic fails the image. The loop then regenerates with the fix
hint until SAM confirms the product is present and prominent.
"""

import textwrap

from veritas.config import load_api_key
from veritas.critics import grounding_critic
from veritas.meta_client import MetaClient
from veritas.orchestrator import run_image_loop, write_ledger

SCENE = "a sweeping alpine mountain landscape at golden hour, hiking trail"
TARGET = "water bottle"


def _banner(title: str) -> None:
    print("\n" + "=" * 72 + f"\n {title}\n" + "=" * 72)


def main() -> None:
    client = MetaClient(load_api_key())

    _banner("VERITAS — grounded-visual loop (Muse Image + SAM 3.1)")
    print("Scene prompt:", SCENE)
    print("Must contain (verified by SAM 3.1):", TARGET)

    def on_event(kind, n, payload):
        if kind == "generated":
            print(f"\n--- iteration {n}: generated image -> {payload} ---")
        elif kind == "verified":
            for v in payload:
                mark = "PASS" if v.passed else "FAIL"
                print(f"   [{mark}] {v.check} (score {v.score:.2f}) -- {v.reason}")
                if not v.passed and v.fix_hint:
                    print(f"          -> {v.fix_hint}")

    def critic(client, image_b64):
        return grounding_critic(client, image_b64, TARGET)

    result = run_image_loop(client, SCENE, [critic], on_event=on_event)

    _banner("RESULT")
    print(f"Passed: {result.passed} | iterations: {len(result.iterations)} "
          f"| stopped: {result.stopped_reason}")
    print(f"Credits spent this run: ${result.spend_usd:.4f}")
    print("Final verified image:", result.final_artifact)

    path = write_ledger(result)
    print("Audit ledger written to:", path)


if __name__ == "__main__":
    main()
