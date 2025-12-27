from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import sys
from datetime import datetime, timezone
from uuid import UUID
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright
from selectolax.parser import HTMLParser
from sqlalchemy import select

from core.artifacts import ArtifactStore
from core.config import settings
from core.db import async_session
from core.models import Artifact, Job
from scraper.engine import EngineOutcome
from scraper.llm_recovery import recover_with_llm
from scraper.parsing import parse_html
from scraper.selector_registry import load_selectors_async, record_candidates_async

logger = logging.getLogger(__name__)


async def run_browser_engine(job_id: UUID) -> EngineOutcome:
    async with async_session() as session:
        result = await session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            return EngineOutcome(success=False, error="job_not_found")
        if not job.schema_id:
            return EngineOutcome(success=False, error="schema_missing")
        url = job.url

    selectors = await load_selectors_async(job.schema_id)
    if not selectors:
        return await _mark_failed(job_id, "no_selectors")

    logger.info(
        "Browser settings: timeout_ms=%s wait_until=%s wait_for_selector=%s wait_for_ms=%s scroll_steps=%s scroll_delay_ms=%s scroll_container=%s collect_max_items=%s pagination_max_pages=%s pagination_next_selector=%s pagination_param=%s pagination_start=%s pagination_step=%s pagination_template=%s headless=%s full_page=%s",
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
        file=sys.stderr,
        flush=True,
    )

    store = ArtifactStore()
    html = None
    screenshot_bytes = None
    har_bytes = None
    error: str | None = None

    snapshots: list[tuple[str, str]] = []
    try:
        html, screenshot_bytes, har_bytes, snapshots = await _render_pages(url)
    except PlaywrightTimeoutError:
        error = "timeout"
    except Exception:
        error = "navigation_failed"

    if error:
        await _update_job(job_id, None, error, store)
        return EngineOutcome(success=False, error=error)

    if _should_collect_items():
        data, errors = _collect_from_snapshots(snapshots, selectors)
    else:
        data, errors = parse_html(html or "", selectors, base_url=url)
    if errors:
        llm_result = await asyncio.to_thread(recover_with_llm, html or "", selectors)
        if llm_result.success and llm_result.data is not None:
            await record_candidates_async(job.schema_id, selectors, llm_result.selectors or {})
            await _update_job(job_id, llm_result.data, None, store, html, screenshot_bytes, har_bytes)
            return EngineOutcome(success=True, error=None)

        error = llm_result.error or "llm_failed"
        await _update_job(job_id, None, error, store, html, screenshot_bytes, har_bytes)
        return EngineOutcome(success=False, error=error)

    await _update_job(job_id, data, None, store, html, screenshot_bytes, har_bytes)
    return EngineOutcome(success=True, error=None)


async def _render_pages(url: str) -> tuple[str, bytes, bytes, list[tuple[str, str]]]:
    html = ""
    snapshots: list[tuple[str, str]] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        har_path = os.path.join(tmpdir, "trace.har")
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=settings.browser_headless)
            context = None
            try:
                context = await browser.new_context(record_har_path=har_path)
                page = await context.new_page()
                page_urls = _build_page_urls(url)
                if page_urls:
                    for page_url in page_urls:
                        page_snapshots = await _render_single_page(page, page_url)
                        snapshots.extend(page_snapshots)
                        if page_snapshots:
                            html = page_snapshots[-1][0]
                else:
                    current_url = url
                    visited: set[str] = set()
                    for _ in range(max(settings.browser_pagination_max_pages, 1)):
                        if current_url in visited:
                            break
                        visited.add(current_url)
                        page_snapshots = await _render_single_page(page, current_url)
                        snapshots.extend(page_snapshots)
                        if page_snapshots:
                            html = page_snapshots[-1][0]
                        if not settings.browser_pagination_next_selector:
                            break
                        next_url = _extract_next_url(html, current_url)
                        if not next_url or next_url in visited:
                            break
                        current_url = next_url

                if not html and snapshots:
                    html = snapshots[-1][0]
                screenshot = await page.screenshot(full_page=settings.browser_full_page)
            finally:
                if context is not None:
                    await context.close()
                await browser.close()

        with open(har_path, "rb") as handle:
            har_bytes = handle.read()

    return html, screenshot, har_bytes, snapshots


async def _render_single_page(page, url: str) -> list[tuple[str, str]]:
    await page.goto(
        url,
        wait_until=settings.browser_wait_until,
        timeout=settings.browser_timeout_ms,
    )
    if settings.browser_wait_for_selector:
        await page.wait_for_selector(
            settings.browser_wait_for_selector,
            timeout=settings.browser_timeout_ms,
        )
    if settings.browser_wait_for_ms > 0:
        await page.wait_for_timeout(settings.browser_wait_for_ms)
    return await _collect_scroll_snapshots(page)


async def _collect_scroll_snapshots(page) -> list[tuple[str, str]]:
    snapshots = [(await page.content(), page.url)]
    if settings.browser_scroll_steps <= 0:
        return snapshots
    for _ in range(settings.browser_scroll_steps):
        await _scroll_once(page)
        if settings.browser_scroll_delay_ms > 0:
            await page.wait_for_timeout(settings.browser_scroll_delay_ms)
        snapshots.append((await page.content(), page.url))
    return snapshots


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
    snapshots: list[tuple[str, str]],
    selectors: list,
) -> tuple[dict, list[str]]:
    if not snapshots:
        return {}, ["no_html"]
    groups = _group_selectors(selectors)
    if not groups:
        html, base_url = snapshots[-1]
        return parse_html(html or "", selectors, base_url=base_url)

    aggregated: dict[str, list[dict[str, object]]] = {name: [] for name in groups}
    seen: dict[str, set[str]] = {name: set() for name in groups}
    flat_data: dict[str, object] = {}
    last_errors: list[str] = []
    max_items = settings.browser_collect_max_items

    for html, base_url in snapshots:
        data, errors = parse_html(html or "", selectors, base_url=base_url)
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

        await session.commit()


async def _mark_failed(job_id: UUID, reason: str) -> EngineOutcome:
    await _update_job(job_id, None, reason, ArtifactStore())
    return EngineOutcome(success=False, error=reason)
