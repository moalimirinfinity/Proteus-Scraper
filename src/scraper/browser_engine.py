from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import datetime, timezone
from uuid import UUID

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright
from sqlalchemy import select

from core.artifacts import ArtifactStore
from core.config import settings
from core.db import async_session
from core.models import Artifact, Job
from scraper.engine import EngineOutcome
from scraper.llm_recovery import recover_with_llm
from scraper.parsing import parse_html
from scraper.selector_registry import load_selectors_async, record_candidates_async


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

    store = ArtifactStore()
    html = None
    screenshot_bytes = None
    har_bytes = None
    error: str | None = None

    try:
        html, screenshot_bytes, har_bytes = await _render_page(url)
    except PlaywrightTimeoutError:
        error = "timeout"
    except Exception:
        error = "navigation_failed"

    if error:
        await _update_job(job_id, None, error, store)
        return EngineOutcome(success=False, error=error)

    data, errors = parse_html(html or "", selectors)
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


async def _render_page(url: str) -> tuple[str, bytes, bytes]:
    with tempfile.TemporaryDirectory() as tmpdir:
        har_path = os.path.join(tmpdir, "trace.har")
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=settings.browser_headless)
            context = None
            try:
                context = await browser.new_context(record_har_path=har_path)
                page = await context.new_page()
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
                html = await page.content()
                screenshot = await page.screenshot(full_page=settings.browser_full_page)
            finally:
                if context is not None:
                    await context.close()
                await browser.close()

        with open(har_path, "rb") as handle:
            har_bytes = handle.read()

    return html, screenshot, har_bytes


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
