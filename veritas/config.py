"""Central configuration: endpoints, model IDs, prices, and key loading.

All values are overridable via environment variables so nothing is hard-coded
into application logic. The API key is NEVER stored here — it is read from the
MODEL_API_KEY environment variable at runtime.
"""

import os

# --- API surface (confirmed against https://dev.meta.ai/docs) ---
BASE_URL = os.environ.get("META_BASE_URL", "https://api.meta.ai/v1")

TEXT_MODEL = os.environ.get("VERITAS_TEXT_MODEL", "muse-spark-1.3")
IMAGE_MODEL = os.environ.get("VERITAS_IMAGE_MODEL", "muse-image-1.0")
SEG_MODEL = os.environ.get("VERITAS_SEG_MODEL", "sam-3.1")
# muse-wonder-1.0 is Meta's agentic reasoning model (not video) — used as the
# Tier-3 deep-reasoning escalation arbitrator when the normal loop keeps failing.
WONDER_MODEL = os.environ.get("VERITAS_ARBITER_MODEL", "muse-wonder-1.0")

# --- Inference partner (OpenAI-compatible) for hybrid critic routing ---
PARTNER_BASE_URL = os.environ.get("BASETEN_BASE_URL", "https://inference.baseten.co/v1")
PARTNER_MODEL = os.environ.get("BASETEN_MODEL", "openai/gpt-oss-120b")
# Rough open-weights pricing (USD per 1M tokens), for receipt accounting only.
PARTNER_PRICE_IN = float(os.environ.get("PARTNER_PRICE_IN", "0.15"))
PARTNER_PRICE_OUT = float(os.environ.get("PARTNER_PRICE_OUT", "0.60"))

# --- Pricing, USD, per 1M tokens unless noted (from the Meta Model API pricing page) ---
PRICES = {
    "muse-spark-1.3": {"input": 1.25, "cached": 0.15, "output": 4.25},
    "muse-spark-1.2": {"input": 1.25, "cached": 0.15, "output": 4.25},
    "muse-spark-1.1": {"input": 1.25, "cached": 0.15, "output": 4.25},
    "muse-wonder-1.0": {"input": 4.00, "cached": 0.20, "output": 20.00},
    "muse-image-1.0": {"per_image": 0.01},
    "sam-3.1": {"per_image": 0.0025},  # $2.50 / 1k images
}

# --- Loop defaults (safety rails) ---
DEFAULT_MAX_ITERS = int(os.environ.get("VERITAS_MAX_ITERS", "4"))
DEFAULT_BUDGET_USD = float(os.environ.get("VERITAS_BUDGET_USD", "5.0"))


def load_api_key() -> str:
    """Read the Meta Model API key from the environment, failing loudly."""
    key = os.environ.get("MODEL_API_KEY")
    if not key:
        raise SystemExit(
            "MODEL_API_KEY is not set.\n"
            "  cp .env.example .env   # then put your real key in .env\n"
            "  set -a; source .env; set +a\n"
        )
    return key


def make_partner_provider():
    """Return a Baseten OpenAI-compatible critic provider if configured, else None."""
    key = os.environ.get("BASETEN_API_KEY")
    if not key:
        return None
    from .providers import OpenAICompatProvider
    return OpenAICompatProvider(
        key, PARTNER_BASE_URL, PARTNER_MODEL, label="baseten",
        price_in=PARTNER_PRICE_IN, price_out=PARTNER_PRICE_OUT)
