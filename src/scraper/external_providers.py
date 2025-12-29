from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from core.config import settings


@dataclass(frozen=True)
class ExternalFetchResult:
    url: str
    status: int | None
    html: str
    headers: dict[str, str]
    provider: str
    cost: float


class ExternalProviderError(Exception):
    def __init__(self, code: str, status: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


class ExternalProvider:
    name: str

    async def fetch(self, url: str, timeout_ms: int | None) -> ExternalFetchResult:
        raise NotImplementedError


class ScrapflyProvider(ExternalProvider):
    name = "scrapfly"

    async def fetch(self, url: str, timeout_ms: int | None) -> ExternalFetchResult:
        api_key = settings.external_api_key
        if not api_key:
            raise ExternalProviderError("external_api_key_missing")
        base_url = settings.external_provider_url or "https://api.scrapfly.io/scrape"
        params = {
            "key": api_key,
            "url": url,
            "format": "json",
        }
        response = await _request(base_url, params, timeout_ms)
        if response.status_code in {401, 403}:
            raise ExternalProviderError("external_auth_failed", response.status_code)
        if response.status_code >= 500 or response.status_code == 429:
            raise ExternalProviderError("external_provider_unavailable", response.status_code)
        try:
            payload = response.json()
        except ValueError as exc:
            raise ExternalProviderError("external_provider_response_invalid") from exc
        result = payload.get("result") or {}
        html = result.get("content") or ""
        status = result.get("status_code")
        cost = _extract_cost(payload, response.headers)
        headers = _normalize_headers(result.get("response_headers"))
        return ExternalFetchResult(
            url=str(result.get("url") or url),
            status=_coerce_status(status),
            html=html,
            headers=headers,
            provider=self.name,
            cost=cost,
        )


class ZenRowsProvider(ExternalProvider):
    name = "zenrows"

    async def fetch(self, url: str, timeout_ms: int | None) -> ExternalFetchResult:
        api_key = settings.external_api_key
        if not api_key:
            raise ExternalProviderError("external_api_key_missing")
        base_url = settings.external_provider_url or "https://api.zenrows.com/v1/"
        params = {
            "apikey": api_key,
            "url": url,
        }
        response = await _request(base_url, params, timeout_ms)
        if response.status_code in {401, 403}:
            raise ExternalProviderError("external_auth_failed", response.status_code)
        if response.status_code >= 500 or response.status_code == 429:
            raise ExternalProviderError("external_provider_unavailable", response.status_code)
        html = response.text
        cost = _extract_cost({}, response.headers)
        return ExternalFetchResult(
            url=str(response.url),
            status=response.status_code,
            html=html,
            headers={str(k): str(v) for k, v in response.headers.items()},
            provider=self.name,
            cost=cost,
        )


def get_external_provider() -> ExternalProvider | None:
    provider = (settings.external_provider or "").strip().lower()
    if provider == "scrapfly":
        return ScrapflyProvider()
    if provider == "zenrows":
        return ZenRowsProvider()
    return None


async def _request(
    base_url: str,
    params: dict[str, Any],
    timeout_ms: int | None,
) -> httpx.Response:
    timeout = None
    if timeout_ms is None:
        timeout_ms = settings.external_timeout_ms
    if timeout_ms and timeout_ms > 0:
        timeout = httpx.Timeout(timeout_ms / 1000)
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await client.get(base_url, params=params)


def _extract_cost(payload: dict[str, Any], headers: httpx.Headers) -> float:
    cost = payload.get("cost")
    if isinstance(cost, (int, float)):
        return float(cost)
    for key in ("x-zenrows-cost", "x-zenrows-credits"):
        if key in headers:
            try:
                return float(headers.get(key) or 0)
            except ValueError:
                return settings.external_cost_per_call
    return settings.external_cost_per_call


def _normalize_headers(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items()}
    return {}


def _coerce_status(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
