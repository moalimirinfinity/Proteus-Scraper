from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import assert_tenant_access, get_auth_context, resolve_tenant
from api.schemas import (
    ArtifactOut,
    EngineType,
    JobPriority,
    JobResultResponse,
    JobState,
    JobStatusResponse,
    JobSubmitRequest,
    JobSubmitResponse,
    IdentityCreate,
    IdentityOut,
    IdentityUpdate,
    ProxyMode,
    ProxyPolicyCreate,
    ProxyPolicyOut,
    ProxyPolicyUpdate,
    PreviewHtmlRequest,
    PreviewHtmlResponse,
    PreviewRequest,
    SchemaCreate,
    SchemaOut,
    SchemaUpdate,
    SelectorCreate,
    SelectorCandidateOut,
    SelectorOut,
    SelectorUpdate,
)
from core.artifacts import ArtifactStore
from core.config import settings
from core.db import get_session
from core.engine_policy import is_stealth_allowed
from core.governance import extract_domain, guard_request_async, record_failure_async
from core.identities import (
    acquire_identity_for_url_async,
    record_identity_failure_async,
    store_identity_cookies_async,
)
from core.identity_crypto import IdentityCryptoError, encrypt_payload
from core.metrics import record_job_state
from core.models import Artifact, Identity, Job, ProxyPolicy, Schema, Selector, SelectorCandidate
from core.queues import enqueue_priority
from core.redis import get_redis
from core.security import SecurityError, ensure_url_allowed
from core.ui_rate_limit import allow_ui_action_async
from core.tasks import process_job, select_engine
from scraper.browser_engine import render_preview_html
from scraper.external_engine import fetch_external_html
from scraper.external_providers import ExternalProviderError
from scraper.fetcher import (
    FetcherError,
    fetch_html,
    filter_cookies_for_url,
    identity_headers,
    merge_cookies,
)

router = APIRouter()


def _raise_security_error(exc: SecurityError) -> None:
    if exc.code in {"invalid_url", "invalid_scheme", "dns_failed"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.code)
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.code)


def _rate_limit_actor(request: Request) -> str:
    ctx = get_auth_context(request)
    if ctx and ctx.tenant:
        return f"tenant:{ctx.tenant}"
    if request.client and request.client.host:
        return f"ip:{request.client.host}"
    return "unknown"


async def _enforce_ui_rate_limit(request: Request, scope: str) -> None:
    if scope == "preview":
        limit = settings.ui_rate_limit_preview_per_min
    else:
        limit = settings.ui_rate_limit_schema_per_min
    window = settings.ui_rate_limit_window_sec
    if limit <= 0 or window <= 0:
        return
    redis = get_redis()
    allowed = await allow_ui_action_async(redis, scope, _rate_limit_actor(request), limit, window)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="rate_limited")


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
        group_name=selector.group_name,
        field=selector.field,
        selector=selector.selector,
        item_selector=selector.item_selector,
        attribute=selector.attribute,
        data_type=selector.data_type,
        required=selector.required,
        active=selector.active,
        created_at=selector.created_at,
    )


def _proxy_policy_out(policy: ProxyPolicy) -> ProxyPolicyOut:
    try:
        mode = ProxyMode(policy.mode)
    except ValueError:
        mode = ProxyMode.gateway
    return ProxyPolicyOut(
        id=str(policy.id),
        domain=policy.domain,
        mode=mode,
        proxy_url=policy.proxy_url,
        enabled=policy.enabled,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )


def _identity_out(identity: Identity) -> IdentityOut:
    return IdentityOut(
        id=str(identity.id),
        tenant=identity.tenant,
        label=identity.label,
        fingerprint=identity.fingerprint,
        active=identity.active,
        use_count=identity.use_count,
        failure_count=identity.failure_count,
        last_used_at=identity.last_used_at,
        last_failed_at=identity.last_failed_at,
        created_at=identity.created_at,
        updated_at=identity.updated_at,
    )


def _candidate_out(candidate: SelectorCandidate) -> SelectorCandidateOut:
    return SelectorCandidateOut(
        id=str(candidate.id),
        schema_id=candidate.schema_id,
        group_name=candidate.group_name,
        field=candidate.field,
        selector=candidate.selector,
        item_selector=candidate.item_selector,
        attribute=candidate.attribute,
        data_type=candidate.data_type,
        required=candidate.required,
        success_count=candidate.success_count,
        promoted_at=candidate.promoted_at,
        created_at=candidate.created_at,
        updated_at=candidate.updated_at,
    )


@router.post("/submit", response_model=JobSubmitResponse, status_code=status.HTTP_201_CREATED)
async def submit_job(
    payload: JobSubmitRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> JobSubmitResponse:
    try:
        await ensure_url_allowed(str(payload.url))
    except SecurityError as exc:
        _raise_security_error(exc)
    tenant = resolve_tenant(request, payload.tenant)
    job = Job(
        url=str(payload.url),
        state=JobState.queued.value,
        priority=payload.priority.value,
        schema_id=payload.schema_id,
        tenant=tenant,
        engine=payload.engine.value if payload.engine else None,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    redis = get_redis()
    await enqueue_priority(redis, payload.priority.value, str(job.id))
    record_job_state(
        JobState.queued.value,
        payload.engine.value if payload.engine else "auto",
        job.url,
    )

    return JobSubmitResponse(job_id=str(job.id), state=JobState.queued)


@router.get("/status/{job_id}", response_model=JobStatusResponse)
async def get_status(
    job_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> JobStatusResponse:
    result = await session.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    assert_tenant_access(request, job.tenant)

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
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> JobResultResponse:
    result = await session.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    assert_tenant_access(request, job.tenant)

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


@router.get("/proxy-policies", response_model=list[ProxyPolicyOut])
async def list_proxy_policies(
    domain: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[ProxyPolicyOut]:
    query = select(ProxyPolicy).order_by(ProxyPolicy.domain)
    if domain:
        query = query.where(ProxyPolicy.domain == domain)
    result = await session.execute(query)
    return [_proxy_policy_out(policy) for policy in result.scalars().all()]


@router.post("/proxy-policies", response_model=ProxyPolicyOut, status_code=status.HTTP_201_CREATED)
async def create_proxy_policy(
    payload: ProxyPolicyCreate,
    session: AsyncSession = Depends(get_session),
) -> ProxyPolicyOut:
    existing = await session.execute(
        select(ProxyPolicy).where(ProxyPolicy.domain == payload.domain)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="policy already exists")
    if payload.mode == ProxyMode.custom and not payload.proxy_url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="proxy_url required")

    policy = ProxyPolicy(
        domain=payload.domain,
        mode=payload.mode.value,
        proxy_url=payload.proxy_url,
        enabled=payload.enabled,
    )
    session.add(policy)
    await session.commit()
    await session.refresh(policy)
    return _proxy_policy_out(policy)


@router.patch("/proxy-policies/{policy_id}", response_model=ProxyPolicyOut)
async def update_proxy_policy(
    policy_id: UUID,
    payload: ProxyPolicyUpdate,
    session: AsyncSession = Depends(get_session),
) -> ProxyPolicyOut:
    result = await session.execute(select(ProxyPolicy).where(ProxyPolicy.id == policy_id))
    policy = result.scalar_one_or_none()
    if policy is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="policy not found")

    if payload.mode is not None:
        policy.mode = payload.mode.value
    if payload.proxy_url is not None:
        policy.proxy_url = payload.proxy_url
    if payload.enabled is not None:
        policy.enabled = payload.enabled
    if policy.mode == ProxyMode.custom.value and not policy.proxy_url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="proxy_url required")

    await session.commit()
    await session.refresh(policy)
    return _proxy_policy_out(policy)


@router.delete("/proxy-policies/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_proxy_policy(
    policy_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> Response:
    result = await session.execute(select(ProxyPolicy).where(ProxyPolicy.id == policy_id))
    policy = result.scalar_one_or_none()
    if policy is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="policy not found")
    await session.delete(policy)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/artifacts/{artifact_id}")
async def get_artifact(
    artifact_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Response:
    result = await session.execute(
        select(Artifact, Job)
        .join(Job, Artifact.job_id == Job.id)
        .where(Artifact.id == artifact_id)
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="artifact not found")
    artifact, job = row
    assert_tenant_access(request, job.tenant)

    content_type = {
        "html": "text/html",
        "screenshot": "image/png",
        "har": "application/json",
    }.get(artifact.type, "application/octet-stream")
    store = ArtifactStore()
    try:
        data = store.load_bytes(artifact.location)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="artifact not found")
    return Response(data, media_type=content_type)


@router.post("/preview/html", response_model=PreviewHtmlResponse)
async def preview_html(payload: PreviewHtmlRequest, request: Request) -> PreviewHtmlResponse:
    await _enforce_ui_rate_limit(request, "preview")
    try:
        await ensure_url_allowed(payload.url)
    except SecurityError as exc:
        _raise_security_error(exc)
    tenant = resolve_tenant(request, payload.tenant)
    engine_value = payload.engine.value if payload.engine else select_engine(payload.url)
    engine = EngineType(engine_value)
    if engine == EngineType.stealth and not is_stealth_allowed(payload.url):
        engine = EngineType.fast
    if engine == EngineType.browser:
        html, _, _ = await render_preview_html(payload.url, tenant)
    elif engine == EngineType.external:
        try:
            result = await fetch_external_html(payload.url, tenant)
        except ExternalProviderError as exc:
            detail = exc.code
            status_code = status.HTTP_403_FORBIDDEN if detail == "external_not_allowed" else None
            if detail == "external_budget_exceeded":
                status_code = status.HTTP_429_TOO_MANY_REQUESTS
            if detail in {
                "external_disabled",
                "external_circuit_open",
                "external_api_key_missing",
                "external_provider_unconfigured",
            }:
                status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            raise HTTPException(
                status_code=status_code or status.HTTP_502_BAD_GATEWAY,
                detail=detail,
            ) from exc
        html = result.html
    else:
        redis = get_redis()
        error = await guard_request_async(redis, payload.url)
        if error:
            status_code = (
                status.HTTP_429_TOO_MANY_REQUESTS
                if error == "rate_limited"
                else status.HTTP_503_SERVICE_UNAVAILABLE
            )
            raise HTTPException(status_code=status_code, detail=error)
        assignment = await acquire_identity_for_url_async(payload.url, tenant)
        identity = assignment.identity
        headers = identity_headers(
            identity.fingerprint if identity else None,
            settings.fetch_user_agent,
        )
        identity_cookies = list(identity.cookies) if identity else []
        request_cookies = filter_cookies_for_url(identity_cookies, payload.url)
        max_chars = settings.preview_html_max_chars
        backend = (
            "stealth"
            if engine == EngineType.stealth and is_stealth_allowed(payload.url)
            else "fast"
        )
        try:
            result = await fetch_html(
                payload.url,
                backend=backend,
                headers=headers,
                cookies=request_cookies,
                proxy_url=assignment.proxy_url,
                timeout_ms=settings.fetch_timeout_ms,
                max_bytes=max_chars + 1,
                impersonate=settings.fetch_curl_impersonate,
            )
        except FetcherError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=exc.code,
            ) from exc

        if identity and result.cookies:
            merged = merge_cookies(identity_cookies, result.cookies)
            if merged != identity_cookies:
                await store_identity_cookies_async(identity.id, merged)

        if result.status in {403, 429}:
            domain = extract_domain(result.url or payload.url)
            if domain:
                await record_failure_async(redis, domain, result.status)
            if identity:
                await record_identity_failure_async(identity.id, f"http_{result.status}", url=payload.url)
            raise HTTPException(
                status_code=(
                    status.HTTP_429_TOO_MANY_REQUESTS
                    if result.status == 429
                    else status.HTTP_403_FORBIDDEN
                ),
                detail=f"http_{result.status}",
            )
        html = result.html
    truncated_html, truncated = _truncate_html(html, settings.preview_html_max_chars)
    return PreviewHtmlResponse(
        url=payload.url,
        engine=engine,
        html=truncated_html,
        truncated=truncated,
    )


@router.post("/schemas", response_model=SchemaOut, status_code=status.HTTP_201_CREATED)
async def create_schema(
    payload: SchemaCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> SchemaOut:
    await _enforce_ui_rate_limit(request, "schema")
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
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> SchemaOut:
    await _enforce_ui_rate_limit(request, "schema")
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
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Response:
    await _enforce_ui_rate_limit(request, "schema")
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


@router.get("/schemas/{schema_id}/candidates", response_model=list[SelectorCandidateOut])
async def list_selector_candidates(
    schema_id: str,
    include_promoted: bool = False,
    session: AsyncSession = Depends(get_session),
) -> list[SelectorCandidateOut]:
    query = select(SelectorCandidate).where(SelectorCandidate.schema_id == schema_id)
    if not include_promoted:
        query = query.where(SelectorCandidate.promoted_at.is_(None))
    query = query.order_by(SelectorCandidate.created_at.desc())
    result = await session.execute(query)
    return [_candidate_out(candidate) for candidate in result.scalars().all()]


@router.post(
    "/schemas/{schema_id}/candidates/{candidate_id}/promote",
    response_model=SelectorCandidateOut,
)
async def promote_selector_candidate(
    schema_id: str,
    candidate_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> SelectorCandidateOut:
    await _enforce_ui_rate_limit(request, "schema")
    result = await session.execute(
        select(SelectorCandidate)
        .where(SelectorCandidate.id == candidate_id)
        .where(SelectorCandidate.schema_id == schema_id)
    )
    candidate = result.scalar_one_or_none()
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="candidate not found")

    existing = await session.execute(
        select(Selector)
        .where(Selector.schema_id == candidate.schema_id)
        .where(Selector.group_name == candidate.group_name)
        .where(Selector.field == candidate.field)
        .where(Selector.selector == candidate.selector)
        .where(Selector.item_selector == candidate.item_selector)
        .where(Selector.attribute == candidate.attribute)
        .where(Selector.active.is_(True))
    )
    if existing.scalar_one_or_none() is None:
        session.add(
            Selector(
                schema_id=candidate.schema_id,
                group_name=candidate.group_name,
                field=candidate.field,
                selector=candidate.selector,
                item_selector=candidate.item_selector,
                attribute=candidate.attribute,
                data_type=candidate.data_type,
                required=candidate.required,
                active=True,
            )
        )

    candidate.promoted_at = candidate.promoted_at or _now()
    candidate.updated_at = _now()
    await session.commit()
    await session.refresh(candidate)
    return _candidate_out(candidate)


@router.delete("/schemas/{schema_id}/candidates/{candidate_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_selector_candidate(
    schema_id: str,
    candidate_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Response:
    await _enforce_ui_rate_limit(request, "schema")
    result = await session.execute(
        select(SelectorCandidate)
        .where(SelectorCandidate.id == candidate_id)
        .where(SelectorCandidate.schema_id == schema_id)
    )
    candidate = result.scalar_one_or_none()
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="candidate not found")
    await session.delete(candidate)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/schemas/{schema_id}/selectors",
    response_model=SelectorOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_selector(
    schema_id: str,
    payload: SelectorCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> SelectorOut:
    await _enforce_ui_rate_limit(request, "schema")
    schema_result = await session.execute(select(Schema).where(Schema.id == schema_id))
    schema = schema_result.scalar_one_or_none()
    if schema is None:
        schema = Schema(id=schema_id, name=schema_id)
        session.add(schema)

    existing = await session.execute(
        select(Selector)
        .where(Selector.schema_id == schema_id)
        .where(Selector.group_name == payload.group_name)
        .where(Selector.field == payload.field)
        .where(Selector.selector == payload.selector)
        .where(Selector.item_selector == payload.item_selector)
        .where(Selector.attribute == payload.attribute)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="selector already exists")

    selector = Selector(
        schema_id=schema_id,
        group_name=payload.group_name,
        field=payload.field,
        selector=payload.selector,
        item_selector=payload.item_selector,
        attribute=payload.attribute,
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
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> SelectorOut:
    await _enforce_ui_rate_limit(request, "schema")
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
    if payload.group_name is not None:
        selector.group_name = payload.group_name
    if payload.item_selector is not None:
        selector.item_selector = payload.item_selector
    if payload.attribute is not None:
        selector.attribute = payload.attribute
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
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Response:
    await _enforce_ui_rate_limit(request, "schema")
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


@router.get("/identities", response_model=list[IdentityOut])
async def list_identities(
    request: Request,
    tenant: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[IdentityOut]:
    query = select(Identity).order_by(Identity.created_at.desc())
    tenant_filter = resolve_tenant(request, tenant)
    if tenant_filter is not None:
        query = query.where(Identity.tenant == tenant_filter)
    result = await session.execute(query)
    return [_identity_out(identity) for identity in result.scalars().all()]


@router.post("/identities", response_model=IdentityOut, status_code=status.HTTP_201_CREATED)
async def create_identity(
    payload: IdentityCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> IdentityOut:
    tenant_key = resolve_tenant(request, payload.tenant) or "default"
    identity = Identity(
        tenant=tenant_key,
        label=payload.label,
        fingerprint=payload.fingerprint,
        active=payload.active,
    )
    if payload.cookies is not None:
        try:
            identity.cookies_encrypted = encrypt_payload(payload.cookies)
        except IdentityCryptoError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.code)
    if payload.storage_state is not None:
        try:
            identity.storage_state_encrypted = encrypt_payload(payload.storage_state)
        except IdentityCryptoError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.code)
    session.add(identity)
    await session.commit()
    await session.refresh(identity)
    return _identity_out(identity)


@router.get("/identities/{identity_id}", response_model=IdentityOut)
async def get_identity(
    identity_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> IdentityOut:
    result = await session.execute(select(Identity).where(Identity.id == identity_id))
    identity = result.scalar_one_or_none()
    if identity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="identity not found")
    assert_tenant_access(request, identity.tenant)
    return _identity_out(identity)


@router.patch("/identities/{identity_id}", response_model=IdentityOut)
async def update_identity(
    identity_id: UUID,
    payload: IdentityUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> IdentityOut:
    result = await session.execute(select(Identity).where(Identity.id == identity_id))
    identity = result.scalar_one_or_none()
    if identity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="identity not found")
    assert_tenant_access(request, identity.tenant)

    if payload.label is not None:
        identity.label = payload.label
    if payload.fingerprint is not None:
        identity.fingerprint = payload.fingerprint
    if payload.active is not None:
        identity.active = payload.active
    if payload.cookies is not None:
        try:
            identity.cookies_encrypted = encrypt_payload(payload.cookies)
        except IdentityCryptoError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.code)
    if payload.storage_state is not None:
        try:
            identity.storage_state_encrypted = encrypt_payload(payload.storage_state)
        except IdentityCryptoError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.code)

    await session.commit()
    await session.refresh(identity)
    return _identity_out(identity)


@router.delete("/identities/{identity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_identity(
    identity_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Response:
    result = await session.execute(select(Identity).where(Identity.id == identity_id))
    identity = result.scalar_one_or_none()
    if identity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="identity not found")
    assert_tenant_access(request, identity.tenant)
    await session.delete(identity)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/schemas/{schema_id}/preview", response_model=JobResultResponse)
async def preview_schema(
    schema_id: str,
    payload: PreviewRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> JobResultResponse:
    await _enforce_ui_rate_limit(request, "preview")
    try:
        await ensure_url_allowed(payload.url)
    except SecurityError as exc:
        _raise_security_error(exc)
    selector_result = await session.execute(
        select(Selector.id)
        .where(Selector.schema_id == schema_id)
        .where(Selector.active.is_(True))
        .limit(1)
    )
    if selector_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no selectors for schema")

    engine = payload.engine.value if payload.engine else select_engine(payload.url)
    tenant = resolve_tenant(request, None)
    job = Job(
        url=str(payload.url),
        state=JobState.queued.value,
        priority=JobPriority.standard.value,
        schema_id=schema_id,
        engine=engine,
        tenant=tenant,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    record_job_state(JobState.queued.value, engine, job.url)

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


def _truncate_html(html: str, max_chars: int) -> tuple[str, bool]:
    if len(html) <= max_chars:
        return html, False
    return html[:max_chars], True


def _now():
    return datetime.now(timezone.utc)
