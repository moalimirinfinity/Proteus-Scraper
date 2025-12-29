from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class JobPriority(str, Enum):
    high = "high"
    standard = "standard"
    low = "low"


class JobState(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    retried = "retried"
    dead_letter = "dead_letter"
    unknown = "unknown"


class EngineType(str, Enum):
    fast = "fast"
    browser = "browser"
    stealth = "stealth"
    external = "external"


class ProxyMode(str, Enum):
    direct = "direct"
    gateway = "gateway"
    custom = "custom"


class JobSubmitRequest(BaseModel):
    url: str = Field(..., min_length=1)
    schema_id: str | None = None
    priority: JobPriority = JobPriority.standard
    tenant: str | None = None
    engine: EngineType | None = None


class JobSubmitResponse(BaseModel):
    job_id: str
    state: JobState


class JobStatusResponse(BaseModel):
    job_id: str
    state: JobState
    priority: JobPriority
    engine: EngineType | None = None
    schema_id: str | None = None
    tenant: str | None = None
    created_at: datetime
    updated_at: datetime | None = None


class ArtifactOut(BaseModel):
    id: str
    type: str
    location: str
    checksum: str | None = None
    created_at: datetime


class ProxyPolicyCreate(BaseModel):
    domain: str = Field(..., min_length=1)
    mode: ProxyMode = ProxyMode.gateway
    proxy_url: str | None = None
    enabled: bool = True


class ProxyPolicyUpdate(BaseModel):
    mode: ProxyMode | None = None
    proxy_url: str | None = None
    enabled: bool | None = None


class ProxyPolicyOut(BaseModel):
    id: str
    domain: str
    mode: ProxyMode
    proxy_url: str | None = None
    enabled: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None


class JobResultResponse(BaseModel):
    job_id: str
    state: JobState
    data: dict[str, Any] | None = None
    artifacts: list[ArtifactOut] = Field(default_factory=list)
    error: str | None = None


class SchemaCreate(BaseModel):
    schema_id: str = Field(..., min_length=1)
    name: str | None = None
    description: str | None = None


class SchemaUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class SchemaOut(BaseModel):
    schema_id: str
    name: str | None = None
    description: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SelectorCreate(BaseModel):
    group_name: str | None = None
    field: str = Field(..., min_length=1)
    selector: str = Field(..., min_length=1)
    item_selector: str | None = None
    attribute: str | None = None
    data_type: str = "string"
    required: bool = True
    active: bool = True


class SelectorUpdate(BaseModel):
    group_name: str | None = None
    field: str | None = None
    selector: str | None = None
    item_selector: str | None = None
    attribute: str | None = None
    data_type: str | None = None
    required: bool | None = None
    active: bool | None = None


class SelectorOut(BaseModel):
    id: str
    schema_id: str
    group_name: str | None = None
    field: str
    selector: str
    item_selector: str | None = None
    attribute: str | None = None
    data_type: str
    required: bool
    active: bool
    created_at: datetime | None = None


class SelectorCandidateOut(BaseModel):
    id: str
    schema_id: str
    group_name: str | None = None
    field: str
    selector: str
    item_selector: str | None = None
    attribute: str | None = None
    data_type: str
    required: bool
    success_count: int
    promoted_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class IdentityCreate(BaseModel):
    tenant: str | None = None
    label: str | None = None
    fingerprint: dict[str, Any] | None = None
    cookies: list[dict[str, Any]] | None = None
    storage_state: dict[str, Any] | None = None
    active: bool = True


class IdentityUpdate(BaseModel):
    label: str | None = None
    fingerprint: dict[str, Any] | None = None
    cookies: list[dict[str, Any]] | None = None
    storage_state: dict[str, Any] | None = None
    active: bool | None = None


class IdentityOut(BaseModel):
    id: str
    tenant: str
    label: str | None = None
    fingerprint: dict[str, Any] | None = None
    active: bool
    use_count: int
    failure_count: int
    last_used_at: datetime | None = None
    last_failed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PreviewHtmlRequest(BaseModel):
    url: str = Field(..., min_length=1)
    engine: EngineType | None = None
    tenant: str | None = None


class PreviewHtmlResponse(BaseModel):
    url: str
    engine: EngineType
    html: str
    truncated: bool = False


class PreviewRequest(BaseModel):
    url: str = Field(..., min_length=1)
    engine: EngineType | None = None
