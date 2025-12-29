from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import select

from core.config import settings
from core.db import async_session
from core.engine_policy import is_stealth_allowed
from core.external_api import is_external_allowed
from core.metrics import (
    record_engine_attempt,
    record_escalation,
    record_failure,
    record_job_duration,
    record_job_state,
    record_queue_depth,
    start_metrics_server,
)
from core.models import Job, JobAttempt
from core.queues import ENGINE_TYPES, PRIORITY_ORDER, engine_queue, priority_key
from scraper.browser_engine import run_browser_engine
from scraper.external_engine import run_external_engine
from scraper.runner import run_fast_engine


def select_engine(url: str) -> str:
    if "engine=stealth" in url or "stealth=true" in url or "stealth=1" in url:
        return _normalize_engine("stealth", url)
    if "engine=external" in url or "external=true" in url or "external=1" in url:
        return "external"
    if "render=true" in url or "browser=true" in url:
        return "browser"
    return ENGINE_TYPES[0]


async def dispatch_once(ctx: dict) -> None:
    redis = ctx["redis"]
    await _record_queue_depths(redis)
    job_id = None
    for priority in PRIORITY_ORDER:
        job_id = await redis.lpop(priority_key(priority))
        if job_id:
            break

    if not job_id:
        return

    if isinstance(job_id, bytes):
        job_id = job_id.decode()

    async with async_session() as session:
        job_uuid = uuid.UUID(str(job_id))
        result = await session.execute(select(Job).where(Job.id == job_uuid))
        job = result.scalar_one_or_none()
        if job is None:
            return
        job.engine = _normalize_engine(job.engine or select_engine(job.url), job.url)
        job.state = "queued"
        await session.commit()

    await redis.enqueue_job("process_job", job_id, _queue_name=engine_queue(job.engine))


async def process_job(ctx: dict, job_id: str) -> None:
    async with async_session() as session:
        job_uuid = uuid.UUID(str(job_id))
        result = await session.execute(select(Job).where(Job.id == job_uuid))
        job = result.scalar_one_or_none()
        if job is None:
            return

        engine = _normalize_engine(job.engine or ENGINE_TYPES[0], job.url)
        if engine != job.engine:
            job.engine = engine
        record_job_state("running", engine, job.url)
        record_engine_attempt(engine, job.url)
        now = datetime.now(timezone.utc)
        attempt = JobAttempt(
            job_id=job.id,
            engine=engine,
            status="running",
            started_at=now,
        )
        session.add(attempt)
        job.state = "running"
        await session.commit()

        started_at = time.monotonic()
        if job.engine == "browser":
            outcome = await run_browser_engine(job.id)
        elif job.engine == "external":
            outcome = await run_external_engine(job.id)
        else:
            outcome = await run_fast_engine(job.id)
        duration = time.monotonic() - started_at
        attempt.ended_at = datetime.now(timezone.utc)
        if outcome.success:
            attempt.status = "succeeded"
            record_job_state("succeeded", engine, job.url)
            record_job_duration(engine, job.url, duration)
            await session.commit()
            return

        if outcome.escalate:
            reason = outcome.error or "escalation"
            attempt.error = reason
            next_engine = _next_engine(engine, job.url)
            if next_engine:
                attempt.status = "escalated"
                job.state = "queued"
                job.engine = next_engine
                job.error = None
                record_escalation(engine, next_engine, reason, job.url)
                record_job_state("escalated", engine, job.url)
                record_job_state("queued", next_engine, job.url)
                record_job_duration(engine, job.url, duration)
                await session.commit()
                await ctx["redis"].enqueue_job(
                    "process_job",
                    job_id,
                    _queue_name=engine_queue(next_engine),
                )
                return
            attempt.status = "failed"
            job.state = "failed"
            job.error = reason
            record_job_state("failed", engine, job.url)
            record_failure(reason, job.url)
            record_job_duration(engine, job.url, duration)
            await session.commit()
            return

        attempt.status = "failed"
        attempt.error = outcome.error
        job.state = "failed"
        job.error = outcome.error
        record_job_state("failed", engine, job.url)
        record_failure(outcome.error, job.url)
        record_job_duration(engine, job.url, duration)
        await session.commit()


async def startup_dispatcher(ctx: dict) -> None:
    port = _metrics_port(settings.metrics_port_dispatcher)
    start_metrics_server(port)


async def startup_worker(ctx: dict) -> None:
    port = _metrics_port(settings.metrics_port_worker)
    start_metrics_server(port)


async def _record_queue_depths(redis) -> None:
    if not settings.metrics_enabled:
        return
    for priority in PRIORITY_ORDER:
        key = priority_key(priority)
        try:
            depth = await redis.llen(key)
        except Exception:
            continue
        record_queue_depth(key, depth)
    for engine in ENGINE_TYPES:
        key = engine_queue(engine)
        depth = None
        try:
            depth = await redis.llen(key)
        except Exception:
            try:
                depth = await redis.zcard(key)
            except Exception:
                depth = None
        if depth is not None:
            record_queue_depth(key, depth)


def _metrics_port(default: int) -> int:
    override = os.getenv("METRICS_PORT")
    if not override:
        return default
    try:
        return int(override)
    except ValueError:
        return default


def _next_engine(current: str, url: str) -> str | None:
    try:
        index = ENGINE_TYPES.index(current)
    except ValueError:
        return None
    max_depth = _max_escalation_depth()
    if max_depth <= 0 or index >= max_depth:
        return None
    next_index = index + 1
    while next_index < len(ENGINE_TYPES) and next_index <= max_depth:
        candidate = ENGINE_TYPES[next_index]
        if _engine_allowed(candidate, url):
            return candidate
        next_index += 1
    return None


def _max_escalation_depth() -> int:
    limit = settings.router_max_depth
    if limit <= 0:
        return 0
    return min(limit, len(ENGINE_TYPES) - 1)


def _normalize_engine(engine: str, url: str) -> str:
    if engine == "external":
        return engine
    if _engine_allowed(engine, url):
        return engine
    if engine == "stealth":
        return "fast"
    return ENGINE_TYPES[0]


def _engine_allowed(engine: str, url: str) -> bool:
    if engine == "stealth":
        return is_stealth_allowed(url)
    if engine == "external":
        return bool(settings.external_api_key) and is_external_allowed(url)
    return True


class DispatcherWorkerSettings:
    functions = [dispatch_once]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    cron_jobs = [cron(dispatch_once, second={0, 10, 20, 30, 40, 50})]
    on_startup = startup_dispatcher


class EngineWorkerSettings:
    functions = [process_job]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    queue_name = settings.engine_queue
    on_startup = startup_worker
