from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from core.artifacts import ArtifactStore
from core.config import settings
from core.engine_policy import is_stealth_allowed
from core.db import async_session
from core.governance import (
    allow_llm_call_async,
    extract_domain,
    guard_request_async,
    record_failure_async,
)
from core.identities import (
    acquire_identity_for_url_async,
    record_identity_failure_async,
    store_identity_cookies_async,
)
from core.redis import get_redis
from core.security import SecurityError, ensure_url_allowed
from core.models import Artifact, Job
from core.metrics import record_detector_signal
from scraper.detector import detect_blocked_response, detect_empty_parse
from scraper.engine import EngineOutcome
from scraper.fetcher import (
    FetcherError,
    fetch_html,
    filter_cookies_for_url,
    identity_headers,
    merge_cookies,
)
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


async def run_fast_engine(job_id: UUID) -> EngineOutcome:
    async with async_session() as session:
        result = await session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            return EngineOutcome(success=False, error="job_not_found")
        if not job.schema_id:
            return EngineOutcome(success=False, error="schema_missing")
        url = job.url
        schema_id = job.schema_id
        engine = job.engine or "fast"
        tenant = job.tenant
        plugin_names = await resolve_plugin_names(session, schema_id, tenant)

    selectors = await load_selectors_async(schema_id)
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
    error = await guard_request_async(redis, url)
    if error:
        return await _mark_failed(job_id, error)

    assignment = await acquire_identity_for_url_async(url, tenant)
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
        engine=engine,
        tenant=tenant,
        schema_id=schema_id,
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
        error = await guard_request_async(redis, url)
        if error:
            return await _mark_failed(job_id, error)

    backend = "stealth" if engine == "stealth" and is_stealth_allowed(url) else "fast"

    try:
        result = await fetch_html(
            request_ctx.url,
            backend=backend,
            headers=request_ctx.headers,
            cookies=request_ctx.cookies,
            proxy_url=request_ctx.proxy_url,
            timeout_ms=settings.fetch_timeout_ms,
            max_bytes=settings.fetch_max_bytes,
            impersonate=settings.fetch_curl_impersonate,
        )
    except FetcherError as exc:
        return await _mark_failed(job_id, exc.code)

    response_ctx = ResponseContext(
        url=result.url or request_ctx.url,
        status=result.status,
        headers=result.headers,
        body=result.html,
        content=result.content,
        content_type=result.content_type,
        cookies=result.cookies,
        truncated=result.truncated,
        engine=engine,
        tenant=tenant,
        schema_id=schema_id,
        job_id=str(job_id),
    )
    response_ctx, error = apply_response_plugins(response_ctx, plugins)
    if error:
        return await _mark_failed(job_id, error, html=response_ctx.body)

    if response_ctx.url:
        try:
            await ensure_url_allowed(response_ctx.url)
        except SecurityError as exc:
            return await _mark_failed(job_id, exc.code, html=response_ctx.body)

    if identity and response_ctx.cookies:
        merged = merge_cookies(identity_cookies, response_ctx.cookies)
        if merged != identity_cookies:
            await store_identity_cookies_async(identity.id, merged)

    blocked_reason = detect_blocked_response(
        response_ctx.status,
        response_ctx.headers,
        response_ctx.url or url,
        response_ctx.body,
    )
    if blocked_reason:
        record_detector_signal(blocked_reason, engine, "pre_parse", response_ctx.url or url)
        if response_ctx.status in {403, 429}:
            domain = extract_domain(response_ctx.url or url)
            if domain:
                await record_failure_async(redis, domain, response_ctx.status)
        if identity:
            await record_identity_failure_async(identity.id, blocked_reason, url=url)
        return EngineOutcome(success=False, error=blocked_reason, escalate=True)

    data, errors = parse_html(response_ctx.body, selectors, base_url=response_ctx.url)
    store = ArtifactStore()

    parse_ctx = ParseContext(
        data=data,
        errors=errors,
        engine=engine,
        tenant=tenant,
        schema_id=schema_id,
        job_id=str(job_id),
    )
    parse_ctx, error = apply_parse_plugins(parse_ctx, plugins)
    if error:
        return await _mark_failed(job_id, error, html=response_ctx.body)
    data, errors = parse_ctx.data, parse_ctx.errors

    empty_reason = detect_empty_parse(response_ctx.status, data, selectors, errors)
    if empty_reason:
        record_detector_signal(empty_reason, engine, "post_parse", response_ctx.url or url)
        return EngineOutcome(success=False, error=empty_reason, escalate=True)

    if errors:
        budget_allowed = await allow_llm_call_async(redis, str(job_id), tenant)
        if not budget_allowed:
            await _update_job(job_id, None, "llm_budget_exceeded", store, html=response_ctx.body)
            return EngineOutcome(success=False, error="llm_budget_exceeded")

        llm_result = await asyncio.to_thread(
            recover_with_llm,
            response_ctx.body,
            selectors,
            tenant,
        )
        if llm_result.success and llm_result.data is not None:
            await record_candidates_async(schema_id, selectors, llm_result.selectors or {})
            await _update_job(job_id, llm_result.data, None, store, html=response_ctx.body)
            return EngineOutcome(success=True, error=None)

        error = llm_result.error or "llm_failed"
        await _update_job(job_id, None, error, store, html=response_ctx.body)
        return EngineOutcome(success=False, error=error)

    await _update_job(job_id, data, None, store, html=response_ctx.body)
    return EngineOutcome(success=True, error=None)


async def _update_job(
    job_id: UUID,
    data: dict | None,
    error: str | None,
    store: ArtifactStore,
    html: str | None = None,
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
            stored = store.store_text(str(job_id), "raw.html", html, content_type="text/html")
            await replace_artifact(
                "html",
                Artifact(
                    job_id=job.id,
                    type="html",
                    location=stored.location,
                    checksum=stored.checksum,
                ),
            )

        await session.commit()


async def _mark_failed(job_id: UUID, reason: str, html: str | None = None) -> EngineOutcome:
    await _update_job(job_id, None, reason, ArtifactStore(), html=html)
    return EngineOutcome(success=False, error=reason)
