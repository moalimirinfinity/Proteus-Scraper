from __future__ import annotations

import pytest

from core import tasks
from core.config import settings
from scraper.detector import detect_blocked_response


@pytest.mark.asyncio
async def test_detector_triggers_escalation(mock_client, monkeypatch) -> None:
    response = await mock_client.get("/blocked")
    reason = detect_blocked_response(
        response.status_code,
        response.headers,
        str(response.url),
        response.text,
    )
    assert reason == "http_403"

    monkeypatch.setattr(settings, "router_max_depth", 2)
    monkeypatch.setattr(settings, "stealth_enabled", True)
    monkeypatch.setattr(settings, "stealth_allowed_domains", "testserver")

    next_engine = tasks._next_engine("fast", str(response.url))
    assert next_engine == "stealth"
    next_engine = tasks._next_engine("stealth", str(response.url))
    assert next_engine == "browser"
