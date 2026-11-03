"""Thin, dependency-light client for the Meta Model API.

One class, one responsibility: talk to the Meta Model API and keep an honest
running tally of spend. Uses the OpenAI-compatible Responses API
(POST /responses) and Images API (POST /images/generations).

We deliberately use `requests` rather than the OpenAI SDK so we have exact
control over Meta-specific fields (reasoning.effort, image_generation_call
output items, SAM's special-token output) and no hidden retries.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from typing import Any

import requests

from .config import BASE_URL, PRICES, IMAGE_MODEL, SEG_MODEL


class MetaAPIError(RuntimeError):
    """Raised when the Meta Model API returns a non-200 response."""


@dataclass
class Usage:
    """Running cost ledger for a single client session."""

    spend_usd: float = 0.0
    calls: int = 0
    by_model: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Guards concurrent updates when critics run in parallel threads.
        self._lock = threading.Lock()

    def add(self, model: str, cost: float) -> None:
        with self._lock:
            self.spend_usd += cost
            self.calls += 1
            self.by_model[model] = self.by_model.get(model, 0.0) + cost


class MetaClient:
    def __init__(self, api_key: str, base_url: str = BASE_URL, timeout: int = 180):
        if not api_key:
            raise ValueError("api_key is required")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.usage = Usage()
        self._session = requests.Session()
        self._session.headers.update(
            {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        )

    # --- low level ---
    def _post(self, path: str, payload: dict) -> dict:
        resp = self._session.post(
            f"{self.base_url}{path}", data=json.dumps(payload), timeout=self.timeout
        )
        if resp.status_code != 200:
            raise MetaAPIError(f"HTTP {resp.status_code} {path}: {resp.text[:600]}")
        return resp.json()

    # --- text / agentic (Responses API) ---
    def respond(
        self,
        model: str,
        input: Any,
        *,
        reasoning_effort: str | None = None,
        instructions: str | None = None,
        tools: list | None = None,
    ) -> dict:
        payload: dict[str, Any] = {"model": model, "input": input}
        if reasoning_effort:
            payload["reasoning"] = {"effort": reasoning_effort}
        if instructions:
            payload["instructions"] = instructions
        if tools:
            payload["tools"] = tools
        data = self._post("/responses", payload)
        self._account_tokens(model, data.get("usage", {}))
        return data

    def respond_text(self, model: str, input: Any, **kw) -> tuple[str, dict]:
        data = self.respond(model, input, **kw)
        return extract_output_text(data), data

    # --- images (Images API) ---
    def generate_image(
        self, prompt: str, *, n: int = 1, size: str | None = None,
        response_format: str = "b64_json", model: str = IMAGE_MODEL,
    ) -> list[dict]:
        payload: dict[str, Any] = {
            "model": model, "prompt": prompt, "n": n, "response_format": response_format,
        }
        if size:
            payload["size"] = size
        data = self._post("/images/generations", payload)
        self.usage.add(model, PRICES[model]["per_image"] * n)
        return data.get("data", [])

    def edit_image(self, prompt: str, image_b64: str, *, n: int = 1,
                   model: str = IMAGE_MODEL, mime: str = "image/webp") -> list[dict]:
        """Instruction-based in-place edit of an existing image (POST /images/edits).

        Starts from the current (flagged) image and changes only what the prompt
        asks, preserving the rest of the already-verified scene.
        """
        uri = f"data:{mime};base64,{image_b64}"
        payload = {"model": model, "prompt": prompt, "images": [{"image_url": uri}], "n": n}
        data = self._post("/images/edits", payload)
        self.usage.add(model, PRICES[model]["per_image"] * n)
        return data.get("data", [])

    # --- segmentation / grounding (SAM via Responses API) ---
    def segment(self, text: str, image_url: str, model: str = SEG_MODEL) -> tuple[str, dict]:
        input = [{
            "role": "user",
            "content": [
                {"type": "input_text", "text": text},
                {"type": "input_image", "image_url": image_url},
            ],
        }]
        data = self.respond(model, input)  # token accounting is a no-op for SAM
        self.usage.add(model, PRICES[model]["per_image"])
        return extract_output_text(data), data

    @staticmethod
    def to_data_uri(b64: str, mime: str = "image/webp") -> str:
        """Wrap a base64 image as a data URI that SAM/vision inputs accept directly."""
        return f"data:{mime};base64,{b64}"

    # --- cost accounting ---
    def _account_tokens(self, model: str, usage: dict) -> None:
        p = PRICES.get(model)
        if not p or "input" not in p:
            return  # per-image models are billed at call sites
        it = usage.get("input_tokens", 0)
        cached = usage.get("input_tokens_details", {}).get("cached_tokens", 0)
        ot = usage.get("output_tokens", 0)
        cost = ((it - cached) * p["input"] + cached * p["cached"] + ot * p["output"]) / 1_000_000
        self.usage.add(model, cost)


def extract_output_text(data: dict) -> str:
    """Pull the assistant's text out of a Responses API payload."""
    parts: list[str] = []
    for item in data.get("output", []):
        if item.get("type") == "message":
            for c in item.get("content", []):
                if c.get("type") == "output_text":
                    parts.append(c.get("text", ""))
    return "".join(parts).strip()
