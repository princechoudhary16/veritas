"""Partner inference providers (OpenAI-compatible) for hybrid critic routing.

Veritas can "burst" text-only critic checks to an inference partner
(Baseten / Fireworks / Modal) running open-weights models, while generation,
SAM 3.1, and the vision critics stay on the Meta Model API. Because the budget
guard tracks Meta spend, offloading critics to a partner *reduces* Meta credit
usage — a real hybrid-routing win.

Any OpenAI-compatible chat-completions endpoint works; only the base URL, key,
and model slug change between partners.
"""

from __future__ import annotations

import json

import requests

from .meta_client import Usage


class PartnerError(RuntimeError):
    """Raised when a partner endpoint returns a non-200 or an unsupported input."""


class OpenAICompatProvider:
    """Drop-in critic provider for any OpenAI-compatible endpoint.

    Exposes the same ``respond_text`` surface the text critics use, so it can be
    passed as the engine's ``critic_provider``.
    """

    def __init__(self, api_key: str, base_url: str, model: str, *, label: str = "partner",
                 price_in: float = 0.0, price_out: float = 0.0, timeout: int = 120):
        if not api_key:
            raise ValueError("partner api_key is required")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.label = label
        self.price_in = price_in
        self.price_out = price_out
        self.timeout = timeout
        self.usage = Usage()
        self._session = requests.Session()
        self._session.headers.update(
            {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})

    def respond_text(self, model, input, *, instructions=None, reasoning_effort=None, tools=None):
        # Only text critics route here; multimodal/vision critics stay on Meta.
        if not isinstance(input, str):
            raise PartnerError("partner provider only handles text (string) critic input")
        messages = []
        if instructions:
            messages.append({"role": "system", "content": instructions})
        messages.append({"role": "user", "content": input})
        payload = {"model": self.model, "messages": messages, "max_tokens": 400}
        resp = self._session.post(
            f"{self.base_url}/chat/completions", data=json.dumps(payload), timeout=self.timeout)
        if resp.status_code != 200:
            raise PartnerError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        text = (data.get("choices", [{}])[0].get("message", {}).get("content", "") or "").strip()
        u = data.get("usage", {}) or {}
        cost = (u.get("prompt_tokens", 0) * self.price_in
                + u.get("completion_tokens", 0) * self.price_out) / 1_000_000
        self.usage.add(f"{self.label}/{self.model}", cost)
        return text, data
