from __future__ import annotations

import httpx
import pytest_asyncio

from tests.integration.mock_target import app


@pytest_asyncio.fixture
async def mock_client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
