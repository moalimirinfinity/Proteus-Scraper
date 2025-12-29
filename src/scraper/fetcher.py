from __future__ import annotations

import asyncio
import inspect
import logging
import random
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from core.config import settings

logger = logging.getLogger(__name__)
_CLIENTS: dict[str | None, httpx.AsyncClient] = {}
_CLIENT_LOCK = asyncio.Lock()

_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


class FetcherError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class FetchResult:
    url: str
    status: int | None
    html: str
    headers: dict[str, str]
    cookies: list[dict[str, Any]]
    content: bytes
    content_type: str | None
    truncated: bool = False


async def fetch_html(
    url: str,
    *,
    backend: str = "fast",
    headers: dict[str, str] | None = None,
    cookies: list[dict[str, Any]] | None = None,
    proxy_url: str | None = None,
    timeout_ms: int | None = None,
    max_bytes: int | None = None,
    impersonate: str | None = None,
) -> FetchResult:
    attempts = max(1, settings.fetch_retries + 1)
    for attempt in range(attempts):
        try:
            result = await _fetch_once(
                url,
                backend=backend,
                headers=headers,
                cookies=cookies,
                proxy_url=proxy_url,
                timeout_ms=timeout_ms,
                max_bytes=max_bytes,
                impersonate=impersonate,
            )
        except FetcherError as exc:
            if attempt < attempts - 1 and _should_retry_error(exc.code):
                await _sleep_backoff(attempt)
                continue
            raise
        if result.status in _RETRYABLE_STATUS and attempt < attempts - 1:
            await _sleep_backoff(attempt)
            continue
        return result
    return result


def identity_headers(
    fingerprint: dict[str, Any] | None,
    default_user_agent: str | None,
) -> dict[str, str]:
    headers: dict[str, str] = {}
    if fingerprint and isinstance(fingerprint, dict):
        user_agent = fingerprint.get("user_agent")
        if user_agent:
            headers["User-Agent"] = str(user_agent)
        extra = fingerprint.get("headers") or fingerprint.get("extra_http_headers")
        if isinstance(extra, dict):
            for key, value in extra.items():
                if key and value is not None:
                    headers[str(key)] = str(value)
    if "User-Agent" not in headers and default_user_agent:
        headers["User-Agent"] = default_user_agent
    return headers


def filter_cookies_for_url(
    cookies: list[dict[str, Any]] | None,
    url: str,
    *,
    allow_domainless: bool = True,
) -> list[dict[str, Any]]:
    if not cookies:
        return []
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if not host:
        return [cookie for cookie in cookies if isinstance(cookie, dict)]
    filtered: list[dict[str, Any]] = []
    for cookie in cookies:
        if not isinstance(cookie, dict):
            continue
        if _cookie_matches_host(cookie, host, allow_domainless=allow_domainless):
            filtered.append(cookie)
    return filtered


def _cookie_matches_host(
    cookie: dict[str, Any],
    host: str,
    *,
    allow_domainless: bool,
) -> bool:
    domain = cookie.get("domain")
    if domain:
        return _domain_matches(host, str(domain))
    cookie_url = cookie.get("url")
    if cookie_url:
        parsed = urlparse(str(cookie_url))
        cookie_host = parsed.hostname or ""
        if cookie_host:
            return _domain_matches(host, cookie_host)
    return allow_domainless


def _domain_matches(host: str, cookie_domain: str) -> bool:
    normalized = cookie_domain.lstrip(".").lower()
    host = host.lower()
    if host == normalized:
        return True
    return host.endswith(f".{normalized}")


def cookies_for_request(cookies: list[dict[str, Any]] | None) -> dict[str, str]:
    if not cookies:
        return {}
    jar: dict[str, str] = {}
    for cookie in cookies:
        if not isinstance(cookie, dict):
            continue
        name = cookie.get("name")
        value = cookie.get("value")
        if name and value is not None:
            jar[str(name)] = str(value)
    return jar


def merge_cookies(existing: list[dict[str, Any]], fresh: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cookie_map: dict[tuple[str, str | None, str | None], dict[str, Any]] = {}
    for cookie in existing:
        key = _cookie_key(cookie)
        if key:
            cookie_map[key] = cookie
    for cookie in fresh:
        key = _cookie_key(cookie)
        if key:
            cookie_map[key] = cookie
    return list(cookie_map.values())


def _cookie_key(cookie: dict[str, Any]) -> tuple[str, str | None, str | None] | None:
    if not isinstance(cookie, dict):
        return None
    name = cookie.get("name")
    if not name:
        return None
    return str(name), _norm(cookie.get("domain")), _norm(cookie.get("path"))


def _norm(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _supports_proxy_kw() -> bool:
    try:
        return "proxy" in inspect.signature(httpx.AsyncClient).parameters
    except (TypeError, ValueError):
        return False


def _should_retry_error(code: str) -> bool:
    return code in {"timeout", "fetch_failed"}


async def _sleep_backoff(attempt: int) -> None:
    base_ms = max(settings.fetch_backoff_ms, 0)
    max_ms = max(settings.fetch_backoff_max_ms, base_ms)
    delay_ms = min(base_ms * (2**attempt), max_ms) if base_ms else 0
    if delay_ms <= 0:
        await asyncio.sleep(0)
        return
    jitter = random.uniform(0, delay_ms * 0.1)
    await asyncio.sleep((delay_ms + jitter) / 1000)


async def _get_httpx_client(proxy_url: str | None) -> httpx.AsyncClient:
    key = proxy_url or None
    client = _CLIENTS.get(key)
    if client:
        return client
    async with _CLIENT_LOCK:
        client = _CLIENTS.get(key)
        if client:
            return client
        client = _build_httpx_client(proxy_url)
        _CLIENTS[key] = client
        return client


def _build_httpx_client(proxy_url: str | None) -> httpx.AsyncClient:
    proxy_kwargs: dict[str, object] = {}
    if proxy_url:
        if _supports_proxy_kw():
            proxy_kwargs["proxy"] = proxy_url
        else:
            proxy_kwargs["proxies"] = {"http://": proxy_url, "https://": proxy_url}
    limits = None
    max_conn = settings.fetch_pool_max_connections
    max_keepalive = settings.fetch_pool_max_keepalive
    if max_conn > 0 or max_keepalive > 0:
        limits = httpx.Limits(
            max_connections=max_conn if max_conn > 0 else None,
            max_keepalive_connections=max_keepalive if max_keepalive > 0 else None,
        )
    return httpx.AsyncClient(
        follow_redirects=True,
        limits=limits,
        **proxy_kwargs,
    )


async def close_http_clients() -> None:
    async with _CLIENT_LOCK:
        clients = list(_CLIENTS.values())
        _CLIENTS.clear()
    for client in clients:
        await client.aclose()


def _extract_cookie_list(jar) -> list[dict[str, Any]]:
    cookies: list[dict[str, Any]] = []
    if jar is None:
        return cookies
    try:
        iterator = iter(jar)
    except TypeError:
        return cookies
    for cookie in iterator:
        name = getattr(cookie, "name", None)
        value = getattr(cookie, "value", None)
        if not name:
            continue
        entry: dict[str, Any] = {"name": name, "value": value}
        domain = getattr(cookie, "domain", None)
        if domain:
            entry["domain"] = domain
        path = getattr(cookie, "path", None)
        if path:
            entry["path"] = path
        if getattr(cookie, "secure", False):
            entry["secure"] = True
        http_only = False
        if hasattr(cookie, "has_nonstandard_attr") and cookie.has_nonstandard_attr("HttpOnly"):
            http_only = True
        rest = getattr(cookie, "_rest", None)
        if isinstance(rest, dict) and rest.get("HttpOnly") is not None:
            http_only = True
        if http_only:
            entry["httpOnly"] = True
        cookies.append(entry)
    return cookies


async def _fetch_once(
    url: str,
    *,
    backend: str,
    headers: dict[str, str] | None,
    cookies: list[dict[str, Any]] | None,
    proxy_url: str | None,
    timeout_ms: int | None,
    max_bytes: int | None,
    impersonate: str | None,
) -> FetchResult:
    if backend == "stealth":
        return await _fetch_with_curl_cffi(
            url,
            headers=headers,
            cookies=cookies,
            proxy_url=proxy_url,
            timeout_ms=timeout_ms,
            max_bytes=max_bytes,
            impersonate=impersonate,
        )
    return await _fetch_with_httpx(
        url,
        headers=headers,
        cookies=cookies,
        proxy_url=proxy_url,
        timeout_ms=timeout_ms,
        max_bytes=max_bytes,
    )


async def _fetch_with_httpx(
    url: str,
    *,
    headers: dict[str, str] | None,
    cookies: list[dict[str, Any]] | None,
    proxy_url: str | None,
    timeout_ms: int | None,
    max_bytes: int | None,
) -> FetchResult:
    resolved_timeout = settings.fetch_timeout_ms if timeout_ms is None else timeout_ms
    timeout = None
    if resolved_timeout and resolved_timeout > 0:
        timeout = httpx.Timeout(resolved_timeout / 1000)
    request_cookies = cookies_for_request(cookies)
    buffer: list[bytes] = []
    total = 0
    truncated = False
    limit = max_bytes if max_bytes and max_bytes > 0 else None

    try:
        client = await _get_httpx_client(proxy_url)
        async with client.stream(
            "GET",
            url,
            headers=headers or {},
            cookies=request_cookies,
            timeout=timeout,
        ) as response:
            status = response.status_code
            content_type = response.headers.get("content-type")
            async for chunk in response.aiter_bytes():
                if limit is not None and total + len(chunk) > limit:
                    remaining = limit - total
                    if remaining > 0:
                        buffer.append(chunk[:remaining])
                        total += remaining
                        truncated = True
                    break
                buffer.append(chunk)
                total += len(chunk)
            content = b"".join(buffer)
            encoding = response.encoding or "utf-8"
            html = content.decode(encoding, errors="ignore")
            cookies_out = _extract_cookie_list(response.cookies.jar)
            return FetchResult(
                url=str(response.url),
                status=status,
                html=html,
                headers={str(k): str(v) for k, v in response.headers.items()},
                cookies=cookies_out,
                content=content,
                content_type=str(content_type) if content_type else None,
                truncated=truncated,
            )
    except httpx.TimeoutException as exc:
        logger.warning("fetch_timeout: %s", exc)
        raise FetcherError("timeout") from exc
    except httpx.RequestError as exc:
        logger.warning("fetch_failed: %s", exc)
        raise FetcherError("fetch_failed") from exc


async def _fetch_with_curl_cffi(
    url: str,
    *,
    headers: dict[str, str] | None,
    cookies: list[dict[str, Any]] | None,
    proxy_url: str | None,
    timeout_ms: int | None,
    max_bytes: int | None,
    impersonate: str | None,
) -> FetchResult:
    try:
        from curl_cffi.requests import AsyncSession
    except ModuleNotFoundError as exc:
        raise FetcherError("stealth_unavailable") from exc

    resolved_timeout = settings.fetch_timeout_ms if timeout_ms is None else timeout_ms
    timeout_sec = None if not resolved_timeout or resolved_timeout <= 0 else resolved_timeout / 1000
    request_cookies = cookies_for_request(cookies)
    proxies = None
    if proxy_url:
        proxies = {"http": proxy_url, "https": proxy_url}
    limit = max_bytes if max_bytes and max_bytes > 0 else None
    truncated = False

    session_args: dict[str, Any] = {"headers": headers or {}}
    if timeout_sec is not None:
        session_args["timeout"] = timeout_sec
    if impersonate:
        session_args["impersonate"] = impersonate

    try:
        async with AsyncSession(**session_args) as session:
            response = await session.get(
                url,
                cookies=request_cookies,
                proxies=proxies,
                allow_redirects=True,
            )
            status = response.status_code
            content = response.content or b""
            if limit is not None and len(content) > limit:
                content = content[:limit]
                truncated = True
            encoding = response.encoding or "utf-8"
            html = content.decode(encoding, errors="ignore")
            cookie_jar = getattr(response.cookies, "jar", response.cookies)
            cookies_out = _extract_cookie_list(cookie_jar)
            content_type = None
            try:
                content_type = response.headers.get("content-type")
            except Exception:
                content_type = None
            return FetchResult(
                url=str(response.url),
                status=status,
                html=html,
                headers={str(k): str(v) for k, v in response.headers.items()},
                cookies=cookies_out,
                content=content,
                content_type=str(content_type) if content_type else None,
                truncated=truncated,
            )
    except Exception as exc:
        logger.warning("stealth_fetch_failed: %s", exc)
        raise FetcherError("fetch_failed") from exc
