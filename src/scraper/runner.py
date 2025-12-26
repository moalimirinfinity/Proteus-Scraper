from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from core.db import async_session
from core.models import Job
from scraper.engine import EngineOutcome


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

    outcome = await asyncio.to_thread(_run_spider, job_id, url, schema_id)
    if not outcome.success:
        return outcome

    async with async_session() as session:
        result = await session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            return EngineOutcome(success=False, error="job_not_found")
        if job.state == "failed":
            return EngineOutcome(success=False, error=job.error or "validation_failed")
        if job.state == "succeeded":
            return EngineOutcome(success=True, error=None)

        job.error = job.error or "pipeline_incomplete"
        job.state = "failed"
        job.updated_at = datetime.now(timezone.utc)
        await session.commit()
        return EngineOutcome(success=False, error=job.error)


def _run_spider(job_id: UUID, url: str, schema_id: str) -> EngineOutcome:
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    env = os.environ.copy()
    env["SCRAPY_SETTINGS_MODULE"] = "scraper.settings"
    cmd = [
        sys.executable,
        "-m",
        "scrapy",
        "crawl",
        "proteus",
        "-a",
        f"job_id={job_id}",
        "-a",
        f"url={url}",
        "-a",
        f"schema_id={schema_id}",
    ]
    result = subprocess.run(cmd, cwd=project_root, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        return EngineOutcome(success=False, error="spider_error")
    return EngineOutcome(success=True, error=None)
