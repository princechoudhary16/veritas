"""Unit tests for the OpenAI-compatible partner adapter (no network)."""

import pytest

from veritas.providers import OpenAICompatProvider, PartnerError


class _Resp:
    status_code = 200

    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


def test_respond_text_parses_and_accounts(monkeypatch):
    p = OpenAICompatProvider("k", "https://x/v1", "some/model",
                             label="baseten", price_in=1.0, price_out=2.0)
    canned = {"choices": [{"message": {"content": '{"pass": true}'}}],
              "usage": {"prompt_tokens": 1000, "completion_tokens": 1000}}
    monkeypatch.setattr(p._session, "post", lambda *a, **k: _Resp(canned))

    text, raw = p.respond_text("ignored-model", "FACTS...\nCOPY...", instructions="sys")
    assert text == '{"pass": true}'
    # cost = (1000 * 1.0 + 1000 * 2.0) / 1e6 = 0.003
    assert abs(p.usage.spend_usd - 0.003) < 1e-9
    assert any(k.startswith("baseten/") for k in p.usage.by_model)


def test_rejects_multimodal_input():
    p = OpenAICompatProvider("k", "https://x/v1", "m")
    with pytest.raises(PartnerError):
        p.respond_text("m", [{"role": "user", "content": []}])
