# Veritas — submission answers (copy-paste)

Draft answers for the Cerebral Valley / Meta Global AI Developer Hackathon form.
Edit the bracketed bits; paste the rest. Replace the demo link once recorded.

---

**Project name**
Veritas

**One-line pitch**
A verification engine for multimodal AI — "CI/CD for generative models" — that proves every AI output against a declarative policy before it ships.

**Track**
Indie developer.

**What it does**
Veritas generates copy and images with Meta's models, then adversarially cross-checks every artifact against a source of truth in a closed loop until it provably passes — refusing to ship anything it cannot verify. A whole domain is just a YAML "policy pack," so the same engine gates five real-world problems: brand safety, accessibility (WCAG), health-claim safety (FTC), robotics synthetic-training-data, and AI misinformation. Every run ends in a cryptographic receipt, and the receipt can be bound into the image itself as a C2PA Content Credential.

**The problem**
Generative models are powerful but confidently wrong — an ad that claims a feature the product lacks, a training image with hallucinated physics, a caption that doesn't match its photo. Today humans catch this by hand, slowly, and it blocks AI adoption in exactly the regulated, high-stakes domains that need it most.

**How it works (technical)**
- An async, **tiered DAG**: cheap deterministic + SAM 3.1 spatial checks gate an expensive semantic court, so a failure **short-circuits** and saves credits. Verdicts for unchanged artifacts are served from a **content-addressable cache** — together ~46% fewer credits on a real run.
- **Separation of powers**: generators and critics are always independent model calls (mitigates LLM-as-a-judge bias). Deterministic + formal checks gate the probabilistic ones.
- **Formal verification**: numeric claims (capacity, price, dose) are proven with the **Z3 SMT solver**, not LLM-judged.
- **Fix routing + surgical repair**: a failure is routed to the copy or the image; image fixes **edit the flagged image in place** via Muse Image `/images/edits` instead of regenerating.
- **Tier-3 escalation**: when the loop keeps failing, it escalates to **Muse Wonder** (Meta's agentic reasoning model) as a deep-reasoning arbitrator that synthesizes a multi-constraint repair.
- **Self-improving flywheel**: every repaired run exports a verified (rejected, chosen) **DPO** pair to post-train the generator.

**Which Meta Model API models / features**
Muse Spark 1.3 (text + vision critics and the copy generator), Muse Image 1.0 (image generation and in-place edits), SAM 3.1 (grounding, object counting, pixel masks), Muse Wonder 1.0 (Tier-3 reasoning arbitrator). All via the Meta Model API Responses + Images endpoints, with a live USD spend ledger.

**Inference partners**
Baseten — text-only critics "burst" to open-weights models on Baseten's OpenAI-compatible endpoint (hybrid routing), which offloads load from Meta and is tracked separately in the receipt. The adapter is provider-agnostic (Fireworks/Modal drop in by changing one URL).

**What's novel / technically impressive**
A domain-agnostic verification *protocol* (not a single app), combining neuro-symbolic (Z3) formal proofs with grounded SAM 3.1 vision evidence, measurable credit economics (short-circuit + cache), hybrid partner routing, surgical in-place repair, a DPO self-improvement flywheel, and tamper-evident C2PA provenance. 30 automated tests, CI-green.

**Challenges**
Keeping the loop honest and cheap (tiering + caching), making verdicts deterministic (strict JSON + Z3), getting the C2PA cert profile right for valid signing, and being disciplined about what Meta's API actually offers (e.g., Muse Wonder is a reasoning model, not video — so it became the arbitrator, not a video source).

**What's next**
SAM 3.1 video temporal-stability for provided clips, audio disclaimer checks via Muse Voice Transcribe, and a managed policy-pack registry.

**Open-source repo**
https://github.com/princechoudhary16/veritas

**Demo video**
[paste the 3-minute video link here]

**Team**
[your name / handle]
