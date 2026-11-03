# Veritas — 3-minute demo video script

**Target length:** 3:00. **Voiceover:** ~450 words at ~150 wpm.
**Record from the UI in replay mode** (deterministic, free, re-takeable). Do one
*live* run first if you want to prove it's real, then replay for the clean take.

---

## Pre-flight checklist (do this before recording)

1. Ensure both runs are saved for replay (they already are; re-run if needed):
   ```bash
   set -a; source .env; set +a
   python cli.py policies/commercial_brand_guard.yaml
   python cli.py policies/synthetic_data_gate.yaml
   ```
2. Start the UI and open it full-screen, browser zoomed so text is legible:
   ```bash
   python app.py            # http://127.0.0.1:5050
   ```
3. Record at 1920×1080 (or 1280×720). Hide bookmarks bar, mute notifications.
4. Have a second tab on the GitHub repo and one on the architecture diagram in the README.
5. Keep cursor moves slow and deliberate; **pause** on the overlays and the receipt.

---

## Timed shot list + voiceover

> VO = what you say. SCREEN = what's visible. DO = the click/action. LT = optional lower-third caption.

### 0:00 – 0:18 · The problem (hook)
- **SCREEN:** Title card "Veritas — verification for multimodal AI", then the app's idle screen.
- **VO:** "Generative AI is confidently wrong. It will write an ad claiming a feature your product doesn't have, or render a training image that quietly breaks a robot's perception model. Today, humans catch that by hand — slowly. Veritas catches it automatically."
- **LT:** *The problem: confident, unverified output.*

### 0:18 – 0:33 · What it is
- **SCREEN:** The Veritas header + the Policy Pack dropdown.
- **VO:** "Veritas is a verification engine for multimodal AI — CI/CD for generative models. It generates with Meta's models, then cross-checks every output against a policy, in a loop, until it provably passes. Nothing ships unverified."
- **LT:** *Generate → verify → repeat → receipt.*

### 0:33 – 1:35 · Live demo: catch-and-fix (the core)
- **DO:** Select `commercial_brand_guard`, click **Replay last run** (or Run verification).
- **SCREEN:** Iterations stream in; linger on each critic row and the image overlays.
- **VO (as it plays):**
  - "Here's a brand-safety policy. Veritas generates the ad copy and image with Muse Spark and Muse Image — then the verifier court goes to work."
  - *(iteration 1)* "SAM 3.1 segments the image looking for the product… and finds nothing. Rejected. And because a cheap Tier-1 check failed, Veritas **short-circuits** — it skips the expensive semantic critics entirely, saving credits."
  - *(iteration 2)* "It regenerates. Now SAM confirms the bottle — boxed in green. But the vision critic catches something subtle: the bottle's markings imply a thousand milliliters, while the copy says 750. A contradiction a human would miss. Rejected again."
  - *(final)* "It fixes **only** the image, keeps the verified copy, and on the next pass every check is green."
- **DO:** On the green banner, click **Download veritas.lock.json**; cut to the JSON.
- **VO:** "Shipped — with a cryptographic receipt: SHA-256 hashes of the exact assets, every critic's score, and the credits saved by short-circuiting."
- **LT:** *SAM 3.1 grounding · cross-modal consistency · short-circuit saved $0.03.*

### 1:35 – 2:05 · The pivot (platform, not wrapper)
- **VO:** "Now the important part — none of this is hard-coded. The policy is just a file. Watch me switch it."
- **DO:** Change the dropdown to `synthetic_data_gate`; click **Replay last run**.
- **SCREEN:** The warehouse image with green boxes on the forklift and every pallet.
- **VO:** "Same engine — now it's a synthetic-data gate for robotics. It admits an image into a training set only if SAM 3.1 confirms the forklift, counts the pallets, and a vision check certifies the scene is physically plausible. Commerce to robotics, in one dropdown."
- **LT:** *One engine. Any domain. Both hackathon themes.*

### 2:05 – 2:35 · Under the hood
- **SCREEN:** README architecture section / the tiered-DAG diagram; a flash of `pytest` green and the CI badge.
- **VO:** "Under the hood it's an async, tiered DAG. Cheap deterministic and spatial checks gate the expensive semantic court, so failures short-circuit and save money. Generators and critics are always separate models — separation of powers against judge bias. It's grounded in Self-Refine, Chain-of-Verification, and Segment Anything — open-source, tested, CI-green."
- **LT:** *async tiered DAG · independent critics · open source · tests + CI.*

### 2:35 – 3:00 · Close
- **SCREEN:** Back to the green "verified" banner + receipt; end card with the repo URL.
- **VO:** "Veritas turns 'trust me' into 'here's the receipt.' One engine, any domain, every output provably verified — built on Meta's Muse models and SAM 3.1. Thanks for watching."
- **LT:** *github.com/princechoudhary16/veritas*

---

## If you only have 60 seconds (elevator cut)
0:00 hook (8s) → 0:08 commercial catch-and-fix, iterations 1→final (32s) → 0:40 switch
to robotics, one run (12s) → 0:52 "one engine, any domain — here's the receipt" + repo URL (8s).

## Tips that win points
- **Show a failure.** The rejected red state → green fix is the whole story; don't rush past it.
- **Pause on the receipt.** Judges reward verifiable, production-minded engineering.
- **Say the numbers.** "Short-circuit saved $0.03 this run" and "SAM 3.1 counted 26 pallets" land.
- **Make the pivot deliberate.** The dropdown switch is the "it's a platform" moment — let it breathe.
- **End on the repo URL** so judges can open the open-source code immediately.
