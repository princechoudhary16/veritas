"""Veritas CLI — run any policy pack and emit a verification receipt.

    set -a; source .env; set +a
    python cli.py policies/commercial_brand_guard.yaml
"""

import argparse
import asyncio
import json
import os
import time

from veritas.config import load_api_key, make_partner_provider
from veritas.engine import run_engine
from veritas.meta_client import MetaClient
from veritas.policy import load_policy


def main() -> None:
    ap = argparse.ArgumentParser(description="Veritas verification engine")
    ap.add_argument("policy", help="path to a policy YAML (e.g. policies/commercial_brand_guard.yaml)")
    ap.add_argument("--brief", help="override the policy's default brief")
    ap.add_argument("--scene", help="override the policy's default image scene prompt")
    ap.add_argument("--receipt", default="veritas.lock.json", help="where to write the receipt")
    ap.add_argument("--partner", action="store_true",
                    help="route text critics to the Baseten inference partner (hybrid)")
    ap.add_argument("--surgical", action="store_true",
                    help="repair images by editing the flagged image in place (not full regen)")
    args = ap.parse_args()

    policy = load_policy(args.policy)
    run_input = {
        "brief": args.brief or policy.brief,
        "source_truth": policy.source_truth,
        "target_object": policy.target_object,
        "scene_prompt": args.scene or policy.scene_prompt,
    }
    provider = MetaClient(load_api_key())
    critic_provider = make_partner_provider() if args.partner else None
    if args.partner and critic_provider is None:
        raise SystemExit("--partner set but BASETEN_API_KEY is not configured in the environment")
    if critic_provider is not None:
        print(f"Hybrid routing: text critics -> {critic_provider.label}/{critic_provider.model}")
    surgical = args.surgical or policy.image_repair == "edit"
    if surgical:
        print("Surgical repair: image fixes edit the flagged image in place (no full regen)")

    def on_event(kind, n, payload):
        if kind == "generated":
            op = payload.get("image_op", "")
            tag = f" (image {op})" if op and op != "kept" else ""
            print(f"\n[iteration {n}] artifacts{tag}")
        elif kind == "tier":
            for v in payload["verdicts"]:
                mark = "PASS" if v["passed"] else "FAIL"
                print(f"   tier {payload['tier']} [{mark}] {v['check']} "
                      f"({v['score']:.2f}) -- {v['reason']}")
        elif kind == "verified":
            if payload["skipped"]:
                print(f"   short-circuit -> skipped tier-2 checks: {payload['skipped']}")
        elif kind == "done":
            print(f"\nRESULT: passed={payload['passed']} | iterations={payload['iterations']} "
                  f"| stopped={payload['stopped']} | spend=${payload['spend']:.4f}")

    print(f"Policy: {policy.name}  ({policy.theme})")
    result = asyncio.run(run_engine(policy, run_input, provider,
                                    critic_provider=critic_provider, surgical_repair=surgical,
                                    on_event=on_event))

    with open(args.receipt, "w") as f:
        json.dump(result.receipt, f, indent=2)
    print("Receipt written to:", args.receipt)

    # Persist the full run so the UI can replay it with no API spend.
    os.makedirs("runs", exist_ok=True)
    run_path = os.path.join("runs", f"engine_{policy.name}_{int(time.time())}.json")
    with open(run_path, "w") as f:
        json.dump({"policy": policy.name, "passed": result.passed,
                   "stopped_reason": result.stopped_reason, "spend_usd": result.spend_usd,
                   "iterations": result.iterations, "receipt": result.receipt}, f)
    econ = result.receipt["economics"]
    print(f"Meta credits spent:                ${econ['credits_spent_usd']:.4f}")
    print(f"Credits saved by short-circuiting: ${econ['credits_saved_by_short_circuit_usd']:.4f}")
    print(f"Credits saved by cache:            ${econ['credits_saved_by_cache_usd']:.4f}")
    if econ.get("critics_routed_to"):
        print(f"Partner spend ({econ['critics_routed_to']}): ${econ['partner_spend_usd']:.4f}")


if __name__ == "__main__":
    main()
