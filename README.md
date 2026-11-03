# Veritas

**An agent that treats every generative output as a claim to be disproven** — it
generates with Meta's models, then adversarially cross-checks each artifact
against its source of truth in a closed loop until it provably passes, refusing
to ship anything it cannot verify.

Built for the Meta Global AI Developer Hackathon on the Meta Model API
(Muse Spark, Muse Image, Muse Wonder, SAM 3.1).

## Why

Generative models are powerful but confidently wrong. Veritas is a framework
where **nothing ships unverified**: the model that *creates* an artifact is
never the only model that *judges* it, every check returns a machine-checkable
verdict, and every iteration is logged to an append-only audit trail.

## How it works

```
brief + source of truth
        │
        ▼
   ┌─ Generator ─┐        Muse Spark / Muse Image / SAM 3.1
   │             │
   ▼             │
 Verifier court ─┘        independent adversarial critics, each returns a
   │                      structured verdict {pass, score, reason, fix_hint}
   ▼
 all pass? ── yes ──▶ ship (with audit trail)
   │
   no ──▶ Fixer repairs only the fault ──▶ loop back
```

### Design principles

1. **Nothing ships unverified** — every artifact has a machine-checkable pass/fail.
2. **Separation of powers** — generators and critics are independent model calls.
3. **Structured verdicts, not prose** — critics emit strict JSON (`Verdict`).
4. **Everything is logged** — the audit ledger is the guarantee and the proof.
5. **Fail closed, bounded** — hard iteration + spend limits; refuses rather than shipping garbage.

## Repo layout

| File | Role |
|------|------|
| `veritas/meta_client.py` | Meta Model API client + spend ledger |
| `veritas/contracts.py`   | The `Verdict` contract + robust JSON parsing |
| `veritas/generators.py`  | Artifact producers (copy; image/video next) |
| `veritas/critics.py`     | Independent adversarial judges |
| `veritas/fixer.py`       | Turns failing verdicts into fix instructions |
| `veritas/orchestrator.py`| The loop, budget guard, and audit ledger |
| `run_demo.py`            | End-to-end text-verification demo |

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env            # put your Meta Model API key in .env
set -a; source .env; set +a
python run_demo.py
```

## Meta Model API integration

- Base URL `https://api.meta.ai/v1`, auth `Authorization: Bearer $MODEL_API_KEY`
- Text + grounding + agentic → `POST /responses`; images → `POST /images/generations`
- Models: `muse-spark-1.3` (text/critics), `muse-image-1.0` (image),
  `muse-wonder-1.0` (video), `sam-3.1` (grounded verification)

## Status

- [x] Meta Model API client with live spend tracking
- [x] Verdict contract + closed loop + audit ledger
- [x] Text claim-support verification loop (end to end)
- [ ] Muse Image generation + SAM 3.1 grounding critic
- [ ] Brand / consistency critics across copy + image
- [ ] Live web UI showing the loop catch-and-fix

## License

MIT
