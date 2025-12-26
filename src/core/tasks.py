from __future__ import annotations

import uuid
from datetime import datetime, timezone

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import select

from core.config import settings
from core.db import async_session
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

        now = datetime.now(timezone.utc)
        attempt = JobAttempt(
            job_id=job.id,
            engine=job.engine or ENGINE_TYPES[0],
            status="running",
            started_at=now,
        )
        session.add(attempt)
        job.state = "running"
        await session.commit()

        if job.engine == "browser":
            outcome = await run_browser_engine(job.id)
        else:
            outcome = await run_fast_engine(job.id)
        attempt.ended_at = datetime.now(timezone.utc)
        if outcome.success:
            attempt.status = "succeeded"
        else:
            attempt.status = "failed"
            attempt.error = outcome.error
            job.state = "failed"
            job.error = outcome.error
        await session.commit()


class DispatcherWorkerSettings:
    functions = [dispatch_once]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    cron_jobs = [cron(dispatch_once, second={0, 10, 20, 30, 40, 50})]


class EngineWorkerSettings:
    functions = [process_job]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    queue_name = settings.engine_queue
