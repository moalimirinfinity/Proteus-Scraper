from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from core.artifacts import ArtifactStore
from core.config import settings
from core.external_api import (
    allow_external_call_async,
    is_external_allowed,
    is_external_circuit_open_async,
    record_external_failure_async,
)
from core.governance import allow_llm_call_async
from core.metrics import (
    record_detector_signal,
    record_external_api_call,
    record_external_api_duration,
    record_external_api_failure,
)
from core.redis import get_redis
from core.db import async_session
from core.models import Artifact, Job
from core.security import SecurityError, ensure_url_allowed
from scraper.detector import detect_blocked_response, detect_empty_parse
from scraper.engine import EngineOutcome
from scraper.external_providers import ExternalFetchResult, ExternalProviderError, get_external_provider
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


async def run_external_engine(job_id: UUID) -> EngineOutcome:
    async with async_session() as session:
        result = await session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            return EngineOutcome(success=False, error="job_not_found")
        if not job.schema_id:
            return EngineOutcome(success=False, error="schema_missing")
        url = job.url
        schema_id = job.schema_id
        tenant = job.tenant
        plugin_names = await resolve_plugin_names(session, schema_id, tenant)

    selectors = await load_selectors_async(schema_id)
    if not selectors:
        return await _mark_failed(job_id, "no_selectors")

    plugins, plugin_error = load_plugins(plugin_names)
    if plugin_error:
        return await _mark_failed(job_id, plugin_error)

    redis = get_redis()
    store = ArtifactStore()
    try:
        request_ctx = RequestContext(
            url=url,
            headers={},
            cookies=[],
            proxy_url=None,
            engine="external",
            tenant=tenant,
            schema_id=schema_id,
            job_id=str(job_id),
        )
        request_ctx, error = apply_request_plugins(request_ctx, plugins)
        if error:
            return await _mark_failed(job_id, error)
        result = await fetch_external_html(request_ctx.url, tenant)
    except ExternalProviderError as exc:
        return await _mark_failed(job_id, exc.code)

    response_ctx = ResponseContext(
        url=result.url or url,
        status=result.status,
        headers=result.headers,
        body=result.html,
        content=result.content,
        content_type=result.content_type,
        cookies=[],
        truncated=False,
        engine="external",
        tenant=tenant,
        schema_id=schema_id,
        job_id=str(job_id),
    )
    response_ctx, error = apply_response_plugins(response_ctx, plugins)
    if error:
        return await _mark_failed(job_id, error, html=response_ctx.body)

    blocked_reason = detect_blocked_response(
        response_ctx.status,
        response_ctx.headers,
        response_ctx.url or url,
        response_ctx.body,
    )
    if blocked_reason:
        record_detector_signal(blocked_reason, "external", "pre_parse", response_ctx.url or url)
        await _update_job(job_id, None, blocked_reason, store, html=response_ctx.body)
        return EngineOutcome(success=False, error=blocked_reason)

    data, errors = parse_html(response_ctx.body, selectors, base_url=response_ctx.url)
    parse_ctx = ParseContext(
        data=data,
        errors=errors,
        engine="external",
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
        record_detector_signal(empty_reason, "external", "post_parse", response_ctx.url or url)
        await _update_job(job_id, None, empty_reason, store, html=response_ctx.body)
        return EngineOutcome(success=False, error=empty_reason)

    if errors:
        budget_allowed = await allow_llm_call_async(redis, str(job_id), tenant)
        if not budget_allowed:
            error = "llm_budget_exceeded"
            await _update_job(job_id, None, error, store, html=response_ctx.body)
            return EngineOutcome(success=False, error=error)

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


async def fetch_external_html(url: str, tenant: str | None) -> ExternalFetchResult:
    try:
        await ensure_url_allowed(url)
    except SecurityError as exc:
        raise ExternalProviderError(exc.code) from exc
    if not settings.external_enabled:
        raise ExternalProviderError("external_disabled")
    if not settings.external_api_key:
        raise ExternalProviderError("external_api_key_missing")
    if not is_external_allowed(url):
        raise ExternalProviderError("external_not_allowed")

    provider = get_external_provider()
    if provider is None:
        raise ExternalProviderError("external_provider_unconfigured")

    redis = get_redis()
    if await is_external_circuit_open_async(redis, url):
        raise ExternalProviderError("external_circuit_open")

    estimated_cost = settings.external_cost_per_call
    budget_allowed = await allow_external_call_async(redis, tenant, estimated_cost)
    if not budget_allowed:
        raise ExternalProviderError("external_budget_exceeded")

    started_at = time.monotonic()
    try:
        result = await provider.fetch(url, settings.external_timeout_ms)
    except ExternalProviderError as exc:
        await record_external_failure_async(redis, url)
        record_external_api_failure(provider.name, exc.code)
        record_external_api_duration(provider.name, time.monotonic() - started_at)
        raise

    duration = time.monotonic() - started_at
    record_external_api_call(provider.name, tenant, result.status, result.cost)
    record_external_api_duration(provider.name, duration)
    return result


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
