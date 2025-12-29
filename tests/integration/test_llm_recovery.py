from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.config import settings
from scraper.llm_recovery import LLMRecoveryResult, recover_with_llm
from scraper.parsing import SelectorSpec

BASE_DIR = Path(__file__).resolve().parents[1]
JSON_DIR = BASE_DIR / "fixtures" / "json"


def _load_expected(name: str) -> dict:
    return json.loads((JSON_DIR / name).read_text(encoding="utf-8"))


class _FakeData:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def model_dump(self) -> dict:
        return dict(self._payload)


class _FakeResponse:
    def __init__(self, payload: dict, selectors: dict) -> None:
        self.data = _FakeData(payload)
        self.selectors = selectors
        self.usage = type("Usage", (), {"total_tokens": 42})()


class _FakeClient:
    class _Chat:
        class _Completions:
            def __init__(self, payload: dict, selectors: dict) -> None:
                self._payload = payload
                self._selectors = selectors

            def create(self, *args, **kwargs):
                return _FakeResponse(self._payload, self._selectors)

        def __init__(self, payload: dict, selectors: dict) -> None:
            self.completions = self._Completions(payload, selectors)

    def __init__(self, payload: dict, selectors: dict) -> None:
        self.chat = self._Chat(payload, selectors)


@pytest.mark.asyncio
async def test_llm_recovery_uses_stubbed_response(mock_client, monkeypatch) -> None:
    response = await mock_client.get("/broken")
    response.raise_for_status()

    selectors = [
        SelectorSpec(field="title", selector="h1.title", data_type="string", required=True),
        SelectorSpec(field="price", selector=".price", data_type="float", required=True),
        SelectorSpec(
            field="buy_url",
            selector="a.buy",
            attribute="href",
            data_type="string",
            required=True,
        ),
    ]
    payload = _load_expected("llm_recovery.json")
    fake_selectors = {
        "title": "h2.title",
        "price": ".price",
        "buy_url": "a.buy",
        "extra": ".ignored",
    }

    monkeypatch.setattr(settings, "openai_api_key", "test")

    def _fake_patch(*args, **kwargs):
        return _FakeClient(payload, fake_selectors)

    monkeypatch.setattr("scraper.llm_recovery.instructor.patch", _fake_patch)

    result = recover_with_llm(response.text, selectors, tenant="test")
    assert isinstance(result, LLMRecoveryResult)
    assert result.success is True
    assert result.data == payload
    assert result.selectors == {
        "title": "h2.title",
        "price": ".price",
        "buy_url": "a.buy",
    }
