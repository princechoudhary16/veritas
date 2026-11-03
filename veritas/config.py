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
VIDEO_MODEL = os.environ.get("VERITAS_VIDEO_MODEL", "muse-wonder-1.0")

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
