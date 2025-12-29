from __future__ import annotations

import asyncio
import math
import logging
import os
import random
import tempfile
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright
from selectolax.parser import HTMLParser
from sqlalchemy import select

from core.artifacts import ArtifactStore
from core.config import settings
from core.db import async_session
from core.redis import get_redis
from core.governance import (
    GovernanceError,
    allow_llm_call_async,
    extract_domain,
    guard_request_async,
    record_failure_async,
)
from core.identities import (
    IdentityContext,
    acquire_identity_for_url_async,
    record_identity_failure_async,
    store_identity_cookies_async,
    store_identity_storage_state_async,
)
from core.models import Artifact, Job
from core.metrics import record_detector_signal
from core.security import SecurityError, ensure_url_allowed
from scraper.detector import detect_blocked_response, detect_empty_parse
from scraper.engine import EngineOutcome
from scraper.fetcher import filter_cookies_for_url, identity_headers, merge_cookies
from scraper.llm_recovery import recover_with_llm
from scraper.parsing import parse_html
from scraper.plugins import (
    ParseContext,
    RequestContext,
    ResponseContext,
    apply_parse_plugins,
    apply_request_plugins,
    apply_response_plugins,
    load_plugins,
    resolve_plugin_names,
)
from scraper.selector_registry import load_selectors_async, record_candidates_async
from scraper.vision import analyze_screenshot

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PageSnapshot:
    html: str
    url: str
    status: int | None
    headers: dict[str, str]


async def render_preview_html(
    url: str,
    tenant: str | None = None,
) -> tuple[str, bytes, bytes]:
    redis = get_redis()
    assignment = await acquire_identity_for_url_async(url, tenant)
    identity = assignment.identity
    html, screenshot, har, _ = await _render_pages(url, redis, identity, assignment.proxy_url)
    return html, screenshot, har


async def run_browser_engine(job_id: UUID) -> EngineOutcome:
    async with async_session() as session:
        result = await session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            return EngineOutcome(success=False, error="job_not_found")
        if not job.schema_id:
            return EngineOutcome(success=False, error="schema_missing")
        url = job.url
        plugin_names = await resolve_plugin_names(session, job.schema_id, job.tenant)

    selectors = await load_selectors_async(job.schema_id)
    if not selectors:
        return await _mark_failed(job_id, "no_selectors")

    plugins, plugin_error = load_plugins(plugin_names)
    if plugin_error:
        return await _mark_failed(job_id, plugin_error)

    redis = get_redis()
    try:
        await ensure_url_allowed(url)
    except SecurityError as exc:
        return await _mark_failed(job_id, exc.code)
    assignment = await acquire_identity_for_url_async(url, job.tenant)
    identity = assignment.identity

    headers = identity_headers(
        identity.fingerprint if identity else None,
        settings.fetch_user_agent,
    )
    identity_cookies = list(identity.cookies) if identity else []
    request_cookies = filter_cookies_for_url(identity_cookies, url)
    request_ctx = RequestContext(
        url=url,
        headers=headers,
        cookies=request_cookies,
        proxy_url=assignment.proxy_url,
        engine="browser",
        tenant=job.tenant,
        schema_id=job.schema_id,
        job_id=str(job_id),
    )
    request_ctx, error = apply_request_plugins(request_ctx, plugins)
    if error:
        return await _mark_failed(job_id, error)
    if request_ctx.url != url:
        original_domain = extract_domain(url)
        new_domain = extract_domain(request_ctx.url)
        if not original_domain or original_domain != new_domain:
            return await _mark_failed(job_id, "plugin_url_changed")
        url = request_ctx.url
        try:
            await ensure_url_allowed(url)
        except SecurityError as exc:
            return await _mark_failed(job_id, exc.code)

    logger.info(
        "Browser settings: timeout_ms=%s wait_until=%s wait_for_selector=%s wait_for_ms=%s scroll_steps=%s scroll_delay_ms=%s scroll_container=%s collect_max_items=%s pagination_max_pages=%s pagination_next_selector=%s pagination_param=%s pagination_start=%s pagination_step=%s pagination_template=%s headless=%s full_page=%s humanize=%s humanize_moves=%s",
        settings.browser_timeout_ms,
        settings.browser_wait_until,
        settings.browser_wait_for_selector,
        settings.browser_wait_for_ms,
        settings.browser_scroll_steps,
        settings.browser_scroll_delay_ms,
        settings.browser_scroll_container_selector,
        settings.browser_collect_max_items,
        settings.browser_pagination_max_pages,
        settings.browser_pagination_next_selector,
        settings.browser_pagination_param,
        settings.browser_pagination_start,
        settings.browser_pagination_step,
        settings.browser_pagination_template,
        settings.browser_headless,
        settings.browser_full_page,
        settings.browser_humanize,
        settings.browser_humanize_moves,
    )
    print(
        "BROWSER_SETTINGS",
        settings.browser_timeout_ms,
        settings.browser_wait_until,
        settings.browser_wait_for_selector,
        settings.browser_wait_for_ms,
        settings.browser_scroll_steps,
        settings.browser_scroll_delay_ms,
        settings.browser_scroll_container_selector,
        settings.browser_collect_max_items,
        settings.browser_pagination_max_pages,
        settings.browser_pagination_next_selector,
        settings.browser_pagination_param,
        settings.browser_pagination_start,
        settings.browser_pagination_step,
        settings.browser_pagination_template,
        settings.browser_headless,
        settings.browser_full_page,
        settings.browser_humanize,
        settings.browser_humanize_moves,
        file=sys.stderr,
        flush=True,
    )
    print(
        "BROWSER_ENV",
        os.environ.get("BROWSER_TIMEOUT_MS"),
        os.environ.get("BROWSER_WAIT_UNTIL"),
        os.environ.get("BROWSER_WAIT_FOR_SELECTOR"),
        os.environ.get("BROWSER_WAIT_FOR_MS"),
        os.environ.get("BROWSER_SCROLL_STEPS"),
        os.environ.get("BROWSER_SCROLL_DELAY_MS"),
        os.environ.get("BROWSER_SCROLL_CONTAINER_SELECTOR"),
        os.environ.get("BROWSER_COLLECT_MAX_ITEMS"),
        os.environ.get("BROWSER_PAGINATION_MAX_PAGES"),
        os.environ.get("BROWSER_PAGINATION_NEXT_SELECTOR"),
        os.environ.get("BROWSER_PAGINATION_PARAM"),
        os.environ.get("BROWSER_PAGINATION_START"),
        os.environ.get("BROWSER_PAGINATION_STEP"),
        os.environ.get("BROWSER_PAGINATION_TEMPLATE"),
        os.environ.get("BROWSER_HEADLESS"),
        os.environ.get("BROWSER_FULL_PAGE"),
        os.environ.get("BROWSER_HUMANIZE"),
        os.environ.get("BROWSER_HUMANIZE_MOVES"),
        file=sys.stderr,
        flush=True,
    )

    store = ArtifactStore()
    html = None
    screenshot_bytes = None
    har_bytes = None
    error: str | None = None

    snapshots: list[PageSnapshot] = []
    try:
        html, screenshot_bytes, har_bytes, snapshots = await _render_pages(
            url,
            redis,
            identity,
            request_ctx.proxy_url,
            extra_headers=request_ctx.headers,
            extra_cookies=request_ctx.cookies,
        )
    except GovernanceError as exc:
        error = exc.code
    except PlaywrightTimeoutError:
        error = "timeout"
    except Exception:
        error = "navigation_failed"

    if error:
        if error in {"http_403", "http_429"}:
            if identity:
                await record_identity_failure_async(identity.id, error, url=url)
            return EngineOutcome(success=False, error=error, escalate=True)
        if identity:
            await record_identity_failure_async(identity.id, error, url=url)
        await _update_job(job_id, None, error, store)
        return EngineOutcome(success=False, error=error)

    if plugins:
        updated_snapshots: list[PageSnapshot] = []
        for snapshot in snapshots:
            response_ctx = ResponseContext(
                url=snapshot.url,
                status=snapshot.status,
                headers=snapshot.headers,
                body=snapshot.html,
                content=snapshot.html.encode("utf-8", errors="ignore"),
                content_type=snapshot.headers.get("content-type")
                or snapshot.headers.get("Content-Type"),
                cookies=[],
                truncated=False,
                engine="browser",
                tenant=job.tenant,
                schema_id=job.schema_id,
                job_id=str(job_id),
            )
            response_ctx, error = apply_response_plugins(response_ctx, plugins)
            if error:
                return await _mark_failed(job_id, error)
            updated_snapshots.append(
                PageSnapshot(
                    html=response_ctx.body,
                    url=response_ctx.url or snapshot.url,
                    status=response_ctx.status if response_ctx.status is not None else snapshot.status,
                    headers=response_ctx.headers or snapshot.headers,
                )
            )
        snapshots = updated_snapshots
        if snapshots:
            html = snapshots[-1].html

    ocr_text = None
    if (settings.vision_ocr_enabled or settings.vision_yolo_enabled) and screenshot_bytes:
        vision = analyze_screenshot(screenshot_bytes)
        ocr_text = vision.ocr_text
        vision_reason = vision.ocr_reason or vision.yolo_reason
        if vision_reason:
            record_detector_signal(vision_reason, "browser", "pre_parse", url)
            if identity:
                await record_identity_failure_async(identity.id, vision_reason, url=url)
            return EngineOutcome(success=False, error=vision_reason, escalate=True)

    blocked_reason = _detect_blocked_snapshots(snapshots)
    if blocked_reason:
        record_detector_signal(blocked_reason, "browser", "pre_parse", url)
        if identity:
            await record_identity_failure_async(identity.id, blocked_reason, url=url)
        return EngineOutcome(success=False, error=blocked_reason, escalate=True)

    if _should_collect_items():
        data, errors = _collect_from_snapshots(snapshots, selectors)
    else:
        data, errors = parse_html(html or "", selectors, base_url=url)
    parse_ctx = ParseContext(
        data=data,
        errors=errors,
        engine="browser",
        tenant=job.tenant,
        schema_id=job.schema_id,
        job_id=str(job_id),
    )
    parse_ctx, error = apply_parse_plugins(parse_ctx, plugins)
    if error:
        return await _mark_failed(job_id, error)
    data, errors = parse_ctx.data, parse_ctx.errors

    empty_reason = detect_empty_parse(_latest_snapshot_status(snapshots), data, selectors, errors)
    if empty_reason:
        record_detector_signal(empty_reason, "browser", "post_parse", url)
        return EngineOutcome(success=False, error=empty_reason, escalate=True)
    if errors:
        budget_allowed = await allow_llm_call_async(redis, str(job.id), job.tenant)
        if not budget_allowed:
            error = "llm_budget_exceeded"
            await _update_job(
                job_id,
                None,
                error,
                store,
                html,
                screenshot_bytes,
                har_bytes,
                ocr_text=ocr_text,
            )
            return EngineOutcome(success=False, error=error)
        llm_result = await asyncio.to_thread(recover_with_llm, html or "", selectors, job.tenant)
        if llm_result.success and llm_result.data is not None:
            await record_candidates_async(job.schema_id, selectors, llm_result.selectors or {})
            await _update_job(
                job_id,
                llm_result.data,
                None,
                store,
                html,
                screenshot_bytes,
                har_bytes,
                ocr_text=ocr_text,
            )
            return EngineOutcome(success=True, error=None)

        error = llm_result.error or "llm_failed"
        await _update_job(
            job_id,
            None,
            error,
            store,
            html,
            screenshot_bytes,
            har_bytes,
            ocr_text=ocr_text,
        )
        return EngineOutcome(success=False, error=error)

    await _update_job(job_id, data, None, store, html, screenshot_bytes, har_bytes, ocr_text=ocr_text)
    return EngineOutcome(success=True, error=None)


async def _render_pages(
    url: str,
    redis,
    identity: IdentityContext | None,
    proxy_url: str | None,
    extra_headers: dict[str, str] | None = None,
    extra_cookies: list[dict[str, Any]] | None = None,
) -> tuple[str, bytes, bytes, list[PageSnapshot]]:
    html = ""
    snapshots: list[PageSnapshot] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        har_path = os.path.join(tmpdir, "trace.har")
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=settings.browser_headless)
            context = None
            try:
                context_kwargs = {"record_har_path": har_path}
                if proxy_url:
                    context_kwargs["proxy"] = {"server": proxy_url}
                fingerprint = identity.fingerprint if identity else {}
                context_kwargs.update(_context_kwargs_from_fingerprint(fingerprint))
                if extra_headers:
                    existing_headers = context_kwargs.get("extra_http_headers") or {}
                    if not isinstance(existing_headers, dict):
                        existing_headers = {}
                    merged_headers = {**existing_headers, **extra_headers}
                    context_kwargs["extra_http_headers"] = merged_headers
                if identity and identity.storage_state:
                    context_kwargs["storage_state"] = identity.storage_state
                context = await browser.new_context(**context_kwargs)
                if not identity or not identity.storage_state:
                    base_cookies = identity.cookies if identity else []
                    cookies = _filter_context_cookies(base_cookies, url)
                    if extra_cookies:
                        cookies = merge_cookies(cookies, extra_cookies)
                        cookies = _filter_context_cookies(cookies, url)
                    if cookies:
                        await context.add_cookies(cookies)
                permissions = fingerprint.get("permissions") if isinstance(fingerprint, dict) else None
                if permissions:
                    await context.grant_permissions(permissions)
                page = await context.new_page()
                page_urls = _build_page_urls(url)
                if page_urls:
                    for page_url in page_urls:
                        page_snapshots = await _render_single_page(page, page_url, redis)
                        snapshots.extend(page_snapshots)
                        if page_snapshots:
                            html = page_snapshots[-1].html
                else:
                    current_url = url
                    visited: set[str] = set()
                    for _ in range(max(settings.browser_pagination_max_pages, 1)):
                        if current_url in visited:
                            break
                        visited.add(current_url)
                        page_snapshots = await _render_single_page(page, current_url, redis)
                        snapshots.extend(page_snapshots)
                        if page_snapshots:
                            html = page_snapshots[-1].html
                        if not settings.browser_pagination_next_selector:
                            break
                        next_url = _extract_next_url(html, current_url)
                        if not next_url or next_url in visited:
                            break
                        current_url = next_url

                if not html and snapshots:
                    html = snapshots[-1].html
                if identity:
                    await store_identity_cookies_async(identity.id, await context.cookies())
                    await store_identity_storage_state_async(identity.id, await context.storage_state())
                screenshot = await page.screenshot(full_page=settings.browser_full_page)
            finally:
                if context is not None:
                    await context.close()
                await browser.close()

        with open(har_path, "rb") as handle:
            har_bytes = handle.read()

    return html, screenshot, har_bytes, snapshots


async def _render_single_page(page, url: str, redis) -> list[PageSnapshot]:
    error = await guard_request_async(redis, url)
    if error:
        raise GovernanceError(error)
    domain = extract_domain(url)
    response = await page.goto(
        url,
        wait_until=settings.browser_wait_until,
        timeout=settings.browser_timeout_ms,
    )
    if response is not None and response.url:
        try:
            await ensure_url_allowed(response.url)
        except SecurityError as exc:
            raise GovernanceError(exc.code) from exc
    status = response.status if response else None
    headers = {str(k): str(v) for k, v in (response.headers or {}).items()} if response else {}
    if domain and status in {403, 429}:
        await record_failure_async(redis, domain, status)
    if status not in {403, 429} and settings.browser_wait_for_selector:
        await page.wait_for_selector(
            settings.browser_wait_for_selector,
            timeout=settings.browser_timeout_ms,
        )
    if status not in {403, 429} and settings.browser_wait_for_ms > 0:
        await page.wait_for_timeout(settings.browser_wait_for_ms)
    await _humanize_page(page)
    return await _collect_scroll_snapshots(page, status, headers)


async def _collect_scroll_snapshots(
    page,
    status: int | None,
    headers: dict[str, str],
) -> list[PageSnapshot]:
    snapshots = [PageSnapshot(await page.content(), page.url, status, headers)]
    if settings.browser_scroll_steps <= 0:
        return snapshots
    for _ in range(settings.browser_scroll_steps):
        await _scroll_once(page)
        if settings.browser_scroll_delay_ms > 0:
            await page.wait_for_timeout(settings.browser_scroll_delay_ms)
        snapshots.append(PageSnapshot(await page.content(), page.url, status, headers))
    return snapshots


async def _humanize_page(page) -> None:
    if not settings.browser_humanize:
        return
    moves = settings.browser_humanize_moves
    if moves <= 0:
        return
    viewport = page.viewport_size
    if not viewport:
        try:
            viewport = await page.evaluate("() => ({width: window.innerWidth, height: window.innerHeight})")
        except Exception:
            viewport = {"width": 1280, "height": 720}
    width = int(viewport.get("width") or 1280)
    height = int(viewport.get("height") or 720)
    start = _random_point(width, height)
    await page.mouse.move(start[0], start[1])
    for _ in range(moves):
        end = _random_point(width, height)
        await _ghost_move(page, start, end)
        start = end
        pause = max(settings.browser_humanize_pause_ms, 0)
        if pause:
            await page.wait_for_timeout(pause)


async def _scroll_once(page) -> None:
    await page.evaluate(
        """
        (selector) => {
            let target = window.__proteusScrollTarget;
            if (target && !target.isConnected) {
                target = null;
            }
            if (!target && selector) {
                target = document.querySelector(selector);
            }
            if (!target) {
                const candidates = Array.from(document.querySelectorAll("*")).filter((el) => {
                    const style = getComputedStyle(el);
                    return (
                        el.scrollHeight - el.clientHeight > 5 &&
                        (style.overflowY === "auto" || style.overflowY === "scroll")
                    );
                });
                candidates.sort(
                    (a, b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight),
                );
                target = candidates[0] || null;
            }
            target = target || document.scrollingElement || document.documentElement;
            window.__proteusScrollTarget = target;
            const step =
                target === document.scrollingElement || target === document.documentElement
                    ? window.innerHeight
                    : target.clientHeight;
            target.scrollTop = (target.scrollTop || 0) + step;
        }
        """,
        settings.browser_scroll_container_selector,
    )


def _random_point(width: int, height: int, margin: int = 12) -> tuple[float, float]:
    width = max(width, margin * 2 + 1)
    height = max(height, margin * 2 + 1)
    x = random.uniform(margin, width - margin)
    y = random.uniform(margin, height - margin)
    return x, y


async def _ghost_move(page, start: tuple[float, float], end: tuple[float, float]) -> None:
    distance = math.hypot(end[0] - start[0], end[1] - start[1])
    steps = max(12, int(distance / 25))
    cp1 = _random_control_point(start, end, 0.25)
    cp2 = _random_control_point(start, end, 0.75)
    for step in range(steps + 1):
        t = step / steps
        x, y = _bezier_point(start, cp1, cp2, end, t)
        jitter = random.uniform(-1.0, 1.0)
        await page.mouse.move(x + jitter, y + jitter)
        delay_ms = _random_delay_ms()
        if delay_ms:
            await page.wait_for_timeout(delay_ms)


def _random_control_point(
    start: tuple[float, float],
    end: tuple[float, float],
    weight: float,
) -> tuple[float, float]:
    x = start[0] + (end[0] - start[0]) * weight
    y = start[1] + (end[1] - start[1]) * weight
    offset_x = random.uniform(-80, 80)
    offset_y = random.uniform(-80, 80)
    return x + offset_x, y + offset_y


def _bezier_point(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    t: float,
) -> tuple[float, float]:
    u = 1 - t
    tt = t * t
    uu = u * u
    uuu = uu * u
    ttt = tt * t
    x = uuu * p0[0] + 3 * uu * t * p1[0] + 3 * u * tt * p2[0] + ttt * p3[0]
    y = uuu * p0[1] + 3 * uu * t * p1[1] + 3 * u * tt * p2[1] + ttt * p3[1]
    return x, y


def _random_delay_ms() -> int:
    low = max(settings.browser_humanize_min_delay_ms, 0)
    high = max(settings.browser_humanize_max_delay_ms, low)
    if high == 0:
        return 0
    return int(random.uniform(low, high))


def _build_page_urls(base_url: str) -> list[str] | None:
    max_pages = max(settings.browser_pagination_max_pages, 1)
    start = settings.browser_pagination_start
    step = settings.browser_pagination_step
    if settings.browser_pagination_template:
        urls: list[str] = []
        for page in range(start, start + max_pages * step, step):
            template = settings.browser_pagination_template
            url = template.format(page=page)
            if not url.startswith(("http://", "https://")):
                url = urljoin(base_url, url)
            urls.append(url)
        return urls
    if settings.browser_pagination_param:
        return [
            _set_query_param(base_url, settings.browser_pagination_param, page)
            for page in range(start, start + max_pages * step, step)
        ]
    return None


def _context_kwargs_from_fingerprint(fingerprint: dict) -> dict:
    if not isinstance(fingerprint, dict):
        return {}
    kwargs: dict = {}
    user_agent = fingerprint.get("user_agent")
    if user_agent:
        kwargs["user_agent"] = user_agent
    viewport = fingerprint.get("viewport")
    if isinstance(viewport, dict):
        kwargs["viewport"] = viewport
    locale = fingerprint.get("locale")
    if locale:
        kwargs["locale"] = locale
    timezone_id = fingerprint.get("timezone_id")
    if timezone_id:
        kwargs["timezone_id"] = timezone_id
    geolocation = fingerprint.get("geolocation")
    if isinstance(geolocation, dict):
        kwargs["geolocation"] = geolocation
    headers = fingerprint.get("headers") or fingerprint.get("extra_http_headers")
    if isinstance(headers, dict):
        kwargs["extra_http_headers"] = headers
    device_scale_factor = fingerprint.get("device_scale_factor")
    if device_scale_factor is not None:
        kwargs["device_scale_factor"] = device_scale_factor
    is_mobile = fingerprint.get("is_mobile")
    if is_mobile is not None:
        kwargs["is_mobile"] = is_mobile
    has_touch = fingerprint.get("has_touch")
    if has_touch is not None:
        kwargs["has_touch"] = has_touch
    color_scheme = fingerprint.get("color_scheme")
    if color_scheme:
        kwargs["color_scheme"] = color_scheme
    return kwargs


def _filter_context_cookies(cookies: list[dict], url: str) -> list[dict]:
    filtered = filter_cookies_for_url(cookies, url)
    return [
        cookie
        for cookie in filtered
        if isinstance(cookie, dict) and (cookie.get("url") or cookie.get("domain"))
    ]


def _set_query_param(url: str, param: str, value: int) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query[param] = str(value)
    new_query = urlencode(query, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def _extract_next_url(html: str, base_url: str) -> str | None:
    if not settings.browser_pagination_next_selector:
        return None
    tree = HTMLParser(html)
    node = tree.css_first(settings.browser_pagination_next_selector)
    if node is None:
        return None
    href = node.attributes.get("href")
    if not href:
        return None
    return urljoin(base_url, href)


def _should_collect_items() -> bool:
    return bool(
        settings.browser_scroll_steps > 0
        or settings.browser_pagination_max_pages > 1
        or settings.browser_pagination_next_selector
        or settings.browser_pagination_param
        or settings.browser_pagination_template
    )


def _collect_from_snapshots(
    snapshots: list[PageSnapshot],
    selectors: list,
) -> tuple[dict, list[str]]:
    if not snapshots:
        return {}, ["no_html"]
    groups = _group_selectors(selectors)
    if not groups:
        snapshot = snapshots[-1]
        return parse_html(snapshot.html or "", selectors, base_url=snapshot.url)

    aggregated: dict[str, list[dict[str, object]]] = {name: [] for name in groups}
    seen: dict[str, set[str]] = {name: set() for name in groups}
    flat_data: dict[str, object] = {}
    last_errors: list[str] = []
    max_items = settings.browser_collect_max_items

    for snapshot in snapshots:
        data, errors = parse_html(snapshot.html or "", selectors, base_url=snapshot.url)
        last_errors = errors
        for key, value in data.items():
            if key in groups:
                continue
            if value is not None and key not in flat_data:
                flat_data[key] = value

        for group_name, specs in groups.items():
            items = data.get(group_name) or []
            required_fields = {spec.field for spec in specs if spec.required}
            for item in items:
                if not _item_has_required_fields(item, required_fields):
                    continue
                key = _dedupe_key(item, specs)
                if key in seen[group_name]:
                    continue
                seen[group_name].add(key)
                aggregated[group_name].append(item)
                if max_items > 0 and len(aggregated[group_name]) >= max_items:
                    break

    for group_name in groups:
        flat_data[group_name] = aggregated[group_name]

    errors = _filter_list_errors(last_errors, {g for g, items in aggregated.items() if items})
    return flat_data, errors


def _group_selectors(selectors: list) -> dict[str, list]:
    groups: dict[str, list] = {}
    for spec in selectors:
        if spec.group_name:
            groups.setdefault(spec.group_name, []).append(spec)
    return groups


def _item_has_required_fields(item: dict, required_fields: set[str]) -> bool:
    if not required_fields:
        return True
    for field in required_fields:
        value = item.get(field)
        if value is None or value == "":
            return False
    return True


def _dedupe_key(item: dict, specs: list) -> str:
    for key in ("url", "link", "href"):
        value = item.get(key)
        if value:
            return f"{key}:{value}"
    fields = sorted({spec.field for spec in specs})
    return "|".join(f"{field}={item.get(field)}" for field in fields)


def _filter_list_errors(errors: list[str], groups_with_items: set[str]) -> list[str]:
    if not groups_with_items:
        return errors
    filtered: list[str] = []
    for error in errors:
        group = _error_group_name(error)
        if group and group in groups_with_items:
            continue
        filtered.append(error)
    return filtered


def _detect_blocked_snapshots(snapshots: list[PageSnapshot]) -> str | None:
    for snapshot in snapshots:
        reason = detect_blocked_response(
            snapshot.status,
            snapshot.headers,
            snapshot.url,
            snapshot.html,
        )
        if reason:
            return reason
    return None


def _latest_snapshot_status(snapshots: list[PageSnapshot]) -> int | None:
    if not snapshots:
        return None
    return snapshots[-1].status


def _error_group_name(error: str) -> str | None:
    if ":" not in error:
        return None
    code, rest = error.split(":", 1)
    if code == "missing_group_selector":
        return rest
    if code in {"missing", "type"}:
        group = rest.split(".", 1)[0]
        group = group.split(":", 1)[0]
        return group
    return None


async def _update_job(
    job_id: UUID,
    data: dict | None,
    error: str | None,
    store: ArtifactStore,
    html: str | None = None,
    screenshot_bytes: bytes | None = None,
    har_bytes: bytes | None = None,
    ocr_text: str | None = None,
) -> None:
    async with async_session() as session:
        result = await session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            return

        async def replace_artifact(artifact_type: str, artifact: Artifact) -> None:
            existing = await session.execute(
                select(Artifact)
                .where(Artifact.job_id == job_id)
                .where(Artifact.type == artifact_type)
            )
            for row in existing.scalars().all():
                session.delete(row)
            session.add(artifact)

        job.state = "succeeded" if error is None else "failed"
        job.result = data if error is None else None
        job.error = error
        job.updated_at = datetime.now(timezone.utc)

        if html:
            stored = store.store_text(str(job_id), "rendered.html", html, content_type="text/html")
            await replace_artifact(
                "html",
                Artifact(
                    job_id=job.id,
                    type="html",
                    location=stored.location,
                    checksum=stored.checksum,
                ),
            )
        if screenshot_bytes:
            stored = store.store_bytes(
                str(job_id),
                "screenshot.png",
                screenshot_bytes,
                content_type="image/png",
            )
            await replace_artifact(
                "screenshot",
                Artifact(
                    job_id=job.id,
                    type="screenshot",
                    location=stored.location,
                    checksum=stored.checksum,
                ),
            )
        if har_bytes:
            stored = store.store_bytes(
                str(job_id),
                "trace.har",
                har_bytes,
                content_type="application/json",
            )
            await replace_artifact(
                "har",
                Artifact(
                    job_id=job.id,
                    type="har",
                    location=stored.location,
                    checksum=stored.checksum,
                ),
            )
        if ocr_text:
            stored = store.store_text(
                str(job_id),
                "ocr.txt",
                ocr_text,
                content_type="text/plain",
            )
            await replace_artifact(
                "ocr",
                Artifact(
                    job_id=job.id,
                    type="ocr",
                    location=stored.location,
                    checksum=stored.checksum,
                ),
            )

        await session.commit()


async def _mark_failed(job_id: UUID, reason: str) -> EngineOutcome:
    await _update_job(job_id, None, reason, ArtifactStore())
    return EngineOutcome(success=False, error=reason)
