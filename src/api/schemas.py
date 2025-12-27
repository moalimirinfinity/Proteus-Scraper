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


class PreviewRequest(BaseModel):
    url: str = Field(..., min_length=1)
    engine: EngineType | None = None
