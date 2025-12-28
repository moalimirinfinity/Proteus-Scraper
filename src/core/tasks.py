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
from core.metrics import (
    record_failure,
    record_job_duration,
    record_job_state,
    record_queue_depth,
    start_metrics_server,
)
from core.models import Job, JobAttempt
from core.queues import ENGINE_TYPES, PRIORITY_ORDER, engine_queue, priority_key
from scraper.browser_engine import run_browser_engine
from scraper.runner import run_fast_engine


def select_engine(url: str) -> str:
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
        job.engine = job.engine or select_engine(job.url)
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

        engine = job.engine or ENGINE_TYPES[0]
        record_job_state("running", engine, job.url)
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
        else:
            outcome = await run_fast_engine(job.id)
        duration = time.monotonic() - started_at
        attempt.ended_at = datetime.now(timezone.utc)
        if outcome.success:
            attempt.status = "succeeded"
            record_job_state("succeeded", engine, job.url)
        else:
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
