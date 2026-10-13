"""Pydantic request/response schemas for the REST API."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- auth/users
class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: "UserOut"


class UserOut(ORM):
    id: int
    username: str
    role: str
    is_active: bool
    permissions: list[str] = []


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=10, max_length=256)
    role: Literal["admin", "engineer", "viewer"] = "viewer"


# ------------------------------------------------------------------ datasets
class DatasetOut(ORM):
    id: str
    original_filename: str
    file_format: str
    size_bytes: int
    sha256: str
    row_count: int
    columns: list[str]
    is_synthetic: bool
    uploaded_at: datetime
    uploaded_by_username: str | None = None


class UploadResponse(BaseModel):
    dataset: DatasetOut
    preview: dict


# ----------------------------------------------------------------- pipelines
class PipelineOut(ORM):
    id: int
    name: str
    description: str
    source_type: str
    status: str
    config: dict
    created_at: datetime


class PipelineCreate(BaseModel):
    name: str = Field(min_length=3, max_length=100, pattern=r"^[a-z0-9_]+$")
    description: str = Field(default="", max_length=1000)
    source_type: Literal["csv", "json", "database", "api"] = "csv"
    config: dict


class FaultInjection(BaseModel):
    stage: Literal["extract", "validate", "transform", "quality", "load"] = "load"
    fail_times: int = Field(default=1, ge=1, le=10)
    kind: Literal["transient_db", "non_retryable"] = "transient_db"


class RunRequest(BaseModel):
    dataset_id: str = Field(min_length=36, max_length=36)
    fault_injection: FaultInjection | None = None


class RunSummary(ORM):
    id: str
    pipeline_id: int
    pipeline_name: str | None = None
    dataset_id: str | None
    dataset_filename: str | None = None
    parent_run_id: str | None
    trigger_type: str
    status: str
    started_at: datetime
    completed_at: datetime | None
    duration_seconds: float | None
    input_records: int | None
    output_records: int | None
    quarantined_records: int | None
    quality_score: float | None
    failed_stage: str | None
    error_type: str | None
    error_message: str | None
    is_synthetic: bool
    summary: str
    incident_count: int = 0


class RunDetail(RunSummary):
    metrics: dict
    stage_log: list
    anomaly: dict
    report: dict
    run_options: dict
    has_processed_file: bool = False
    has_quarantine_file: bool = False


# ----------------------------------------------------------------- incidents
class IncidentOut(ORM):
    id: str
    run_id: str
    pipeline_id: int
    incident_type: str
    rule_id: str
    severity: str
    title: str
    evidence: dict
    probable_cause: str
    recommended_action: str
    recovery_policy: str
    status: str
    created_at: datetime
    resolved_at: datetime | None
    resolution_notes: str
    ai_analysis: dict
    eligible_actions: list[str] = []
    run_status: str | None = None
    dataset_filename: str | None = None


class IncidentUpdate(BaseModel):
    status: Literal["open", "under_review", "resolved", "closed"] | None = None
    resolution_notes: str | None = Field(default=None, max_length=2000)


class RecoveryRequest(BaseModel):
    action: Literal["retry_run", "rerun_with_dataset", "apply_column_mapping", "escalate"]
    dataset_id: str | None = None
    column_mapping: dict[str, str] | None = None
    notes: str = Field(default="", max_length=1000)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=64)


class ApprovalRequest(BaseModel):
    approve: bool
    reason: str = Field(default="", max_length=500)


class RecoveryLogOut(ORM):
    id: int
    incident_id: str
    recovery_run_id: str | None
    action: str
    mode: str
    attempt_number: int
    result: str
    details: dict
    error_message: str | None
    approval_status: str
    executed_at: datetime
    requested_by_username: str | None = None
    approved_by_username: str | None = None
    incident_title: str | None = None


# ----------------------------------------------------------------- assistant
class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class ChatRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    incident_id: str | None = None
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)


class Page(BaseModel):
    items: list[Any]
    total: int
    limit: int
    offset: int


TokenResponse.model_rebuild()
