from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas import (
    ArtifactOut,
    EngineType,
    JobPriority,
    JobResultResponse,
    JobState,
    JobStatusResponse,
    JobSubmitRequest,
    JobSubmitResponse,
)
from core.db import get_session
from core.models import Artifact, Job
from core.queues import enqueue_priority
from core.redis import get_redis

router = APIRouter()


def _coerce_state(value: str) -> JobState:
    try:
        return JobState(value)
    except ValueError:
        return JobState.unknown


def _coerce_engine(value: str | None) -> EngineType | None:
    if value is None:
        return None
    try:
        return EngineType(value)
    except ValueError:
        return None


def _coerce_priority(value: str) -> JobPriority:
    try:
        return JobPriority(value)
    except ValueError:
        return JobPriority.standard


@router.post("/submit", response_model=JobSubmitResponse, status_code=status.HTTP_201_CREATED)
async def submit_job(
    payload: JobSubmitRequest,
    session: AsyncSession = Depends(get_session),
) -> JobSubmitResponse:
    job = Job(
        url=str(payload.url),
        state=JobState.queued.value,
        priority=payload.priority.value,
        schema_id=payload.schema_id,
        tenant=payload.tenant,
        engine=payload.engine.value if payload.engine else None,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    redis = get_redis()
    await enqueue_priority(redis, payload.priority.value, str(job.id))

    return JobSubmitResponse(job_id=str(job.id), state=JobState.queued)


@router.get("/status/{job_id}", response_model=JobStatusResponse)
async def get_status(
    job_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> JobStatusResponse:
    result = await session.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")

    return JobStatusResponse(
        job_id=str(job.id),
        state=_coerce_state(job.state),
        priority=_coerce_priority(job.priority),
        engine=_coerce_engine(job.engine),
        schema_id=job.schema_id,
        tenant=job.tenant,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@router.get("/results/{job_id}", response_model=JobResultResponse)
async def get_results(
    job_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> JobResultResponse:
    result = await session.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")

    artifact_result = await session.execute(select(Artifact).where(Artifact.job_id == job_id))
    artifacts = [
        ArtifactOut(
            id=str(artifact.id),
            type=artifact.type,
            location=artifact.location,
            checksum=artifact.checksum,
            created_at=artifact.created_at,
        )
        for artifact in artifact_result.scalars().all()
    ]

    return JobResultResponse(
        job_id=str(job.id),
        state=_coerce_state(job.state),
        data=job.result,
        artifacts=artifacts,
        error=job.error,
    )
