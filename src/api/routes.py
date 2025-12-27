from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, select
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
    PreviewRequest,
    SchemaCreate,
    SchemaOut,
    SchemaUpdate,
    SelectorCreate,
    SelectorOut,
    SelectorUpdate,
)
from core.db import get_session
from core.models import Artifact, Job, Schema, Selector, SelectorCandidate
from core.queues import enqueue_priority
from core.redis import get_redis
from core.tasks import process_job, select_engine

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


def _schema_out(schema: Schema) -> SchemaOut:
    return SchemaOut(
        schema_id=schema.id,
        name=schema.name,
        description=schema.description,
        created_at=schema.created_at,
        updated_at=schema.updated_at,
    )


def _selector_out(selector: Selector) -> SelectorOut:
    return SelectorOut(
        id=str(selector.id),
        schema_id=selector.schema_id,
        field=selector.field,
        selector=selector.selector,
        data_type=selector.data_type,
        required=selector.required,
        active=selector.active,
        created_at=selector.created_at,
    )


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


@router.post("/schemas", response_model=SchemaOut, status_code=status.HTTP_201_CREATED)
async def create_schema(
    payload: SchemaCreate,
    session: AsyncSession = Depends(get_session),
) -> SchemaOut:
    result = await session.execute(select(Schema).where(Schema.id == payload.schema_id))
    existing = result.scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="schema already exists")

    schema = Schema(
        id=payload.schema_id,
        name=payload.name or payload.schema_id,
        description=payload.description,
    )
    session.add(schema)
    await session.commit()
    await session.refresh(schema)
    return _schema_out(schema)


@router.get("/schemas", response_model=list[SchemaOut])
async def list_schemas(session: AsyncSession = Depends(get_session)) -> list[SchemaOut]:
    result = await session.execute(select(Schema).order_by(Schema.id))
    schemas = {schema.id: schema for schema in result.scalars().all()}

    selector_result = await session.execute(select(Selector.schema_id).distinct())
    for row in selector_result.all():
        schema_id = row[0]
        if schema_id not in schemas:
            schemas[schema_id] = Schema(id=schema_id, name=schema_id)

    return [
        _schema_out(schema)
        if schema.created_at is not None
        else SchemaOut(schema_id=schema.id, name=schema.name)
        for schema in sorted(schemas.values(), key=lambda item: item.id)
    ]


@router.get("/schemas/{schema_id}", response_model=SchemaOut)
async def get_schema(
    schema_id: str,
    session: AsyncSession = Depends(get_session),
) -> SchemaOut:
    result = await session.execute(select(Schema).where(Schema.id == schema_id))
    schema = result.scalar_one_or_none()
    if schema is not None:
        return _schema_out(schema)

    selector_result = await session.execute(
        select(Selector.id).where(Selector.schema_id == schema_id).limit(1)
    )
    if selector_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="schema not found")

    return SchemaOut(schema_id=schema_id, name=schema_id)


@router.patch("/schemas/{schema_id}", response_model=SchemaOut)
async def update_schema(
    schema_id: str,
    payload: SchemaUpdate,
    session: AsyncSession = Depends(get_session),
) -> SchemaOut:
    result = await session.execute(select(Schema).where(Schema.id == schema_id))
    schema = result.scalar_one_or_none()
    if schema is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="schema not found")

    if payload.name is not None:
        schema.name = payload.name
    if payload.description is not None:
        schema.description = payload.description

    await session.commit()
    await session.refresh(schema)
    return _schema_out(schema)


@router.delete("/schemas/{schema_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schema(
    schema_id: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    schema_result = await session.execute(select(Schema).where(Schema.id == schema_id))
    schema = schema_result.scalar_one_or_none()
    selector_result = await session.execute(
        select(Selector.id).where(Selector.schema_id == schema_id).limit(1)
    )

    if schema is None and selector_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="schema not found")

    await session.execute(
        delete(SelectorCandidate).where(SelectorCandidate.schema_id == schema_id)
    )
    await session.execute(delete(Selector).where(Selector.schema_id == schema_id))
    if schema is not None:
        await session.delete(schema)

    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/schemas/{schema_id}/selectors", response_model=list[SelectorOut])
async def list_selectors(
    schema_id: str,
    session: AsyncSession = Depends(get_session),
) -> list[SelectorOut]:
    result = await session.execute(
        select(Selector).where(Selector.schema_id == schema_id).order_by(Selector.field)
    )
    selectors = result.scalars().all()
    if not selectors:
        schema_result = await session.execute(select(Schema).where(Schema.id == schema_id))
        if schema_result.scalar_one_or_none() is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="schema not found")
    return [_selector_out(selector) for selector in selectors]


@router.post(
    "/schemas/{schema_id}/selectors",
    response_model=SelectorOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_selector(
    schema_id: str,
    payload: SelectorCreate,
    session: AsyncSession = Depends(get_session),
) -> SelectorOut:
    schema_result = await session.execute(select(Schema).where(Schema.id == schema_id))
    schema = schema_result.scalar_one_or_none()
    if schema is None:
        schema = Schema(id=schema_id, name=schema_id)
        session.add(schema)

    existing = await session.execute(
        select(Selector)
        .where(Selector.schema_id == schema_id)
        .where(Selector.field == payload.field)
        .where(Selector.selector == payload.selector)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="selector already exists")

    selector = Selector(
        schema_id=schema_id,
        field=payload.field,
        selector=payload.selector,
        data_type=payload.data_type,
        required=payload.required,
        active=payload.active,
    )
    session.add(selector)
    await session.commit()
    await session.refresh(selector)
    return _selector_out(selector)


@router.patch("/schemas/{schema_id}/selectors/{selector_id}", response_model=SelectorOut)
async def update_selector(
    schema_id: str,
    selector_id: UUID,
    payload: SelectorUpdate,
    session: AsyncSession = Depends(get_session),
) -> SelectorOut:
    result = await session.execute(
        select(Selector)
        .where(Selector.id == selector_id)
        .where(Selector.schema_id == schema_id)
    )
    selector = result.scalar_one_or_none()
    if selector is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="selector not found")

    if payload.field is not None:
        selector.field = payload.field
    if payload.selector is not None:
        selector.selector = payload.selector
    if payload.data_type is not None:
        selector.data_type = payload.data_type
    if payload.required is not None:
        selector.required = payload.required
    if payload.active is not None:
        selector.active = payload.active

    await session.commit()
    await session.refresh(selector)
    return _selector_out(selector)


@router.delete(
    "/schemas/{schema_id}/selectors/{selector_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_selector(
    schema_id: str,
    selector_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> Response:
    result = await session.execute(
        select(Selector)
        .where(Selector.id == selector_id)
        .where(Selector.schema_id == schema_id)
    )
    selector = result.scalar_one_or_none()
    if selector is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="selector not found")

    await session.delete(selector)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/schemas/{schema_id}/preview", response_model=JobResultResponse)
async def preview_schema(
    schema_id: str,
    payload: PreviewRequest,
    session: AsyncSession = Depends(get_session),
) -> JobResultResponse:
    selector_result = await session.execute(
        select(Selector.id)
        .where(Selector.schema_id == schema_id)
        .where(Selector.active.is_(True))
        .limit(1)
    )
    if selector_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no selectors for schema")

    engine = payload.engine.value if payload.engine else select_engine(payload.url)
    job = Job(
        url=str(payload.url),
        state=JobState.queued.value,
        priority=JobPriority.standard.value,
        schema_id=schema_id,
        engine=engine,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    await process_job({}, str(job.id))

    await session.refresh(job)

    artifact_result = await session.execute(select(Artifact).where(Artifact.job_id == job.id))
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
