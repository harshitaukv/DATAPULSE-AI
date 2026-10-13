"""SQLAlchemy ORM models.

Entities: users, datasets, pipelines, pipeline_runs, incidents, recovery_logs,
audit_logs. Structured evidence and metrics are stored in JSON columns, which
map to `json` on PostgreSQL and TEXT-backed JSON on SQLite.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index,
                        Integer, String, Text)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


ROLES = ("admin", "engineer", "viewer")
RUN_STATUSES = ("queued", "running", "succeeded", "warning", "failed")
SEVERITIES = ("low", "medium", "high", "critical")
INCIDENT_STATUSES = ("open", "under_review", "resolved", "closed")
RECOVERY_RESULTS = ("success", "failure", "pending", "skipped", "requires_manual")
APPROVAL_STATUSES = ("not_required", "pending", "approved", "rejected")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint(f"role IN {ROLES}", name="ck_users_role"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="viewer")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    file_format: Mapped[str] = mapped_column(String(8), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    columns: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    uploader: Mapped[User | None] = relationship()


class Pipeline(Base):
    __tablename__ = "pipelines"
    __table_args__ = (CheckConstraint("status IN ('active', 'inactive')", name="ck_pipelines_status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, default="csv")
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    __table_args__ = (
        CheckConstraint(f"status IN {RUN_STATUSES}", name="ck_runs_status"),
        CheckConstraint("quality_score IS NULL OR (quality_score >= 0 AND quality_score <= 100)",
                        name="ck_runs_quality_range"),
        Index("ix_runs_pipeline_started", "pipeline_id", "started_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    pipeline_id: Mapped[int] = mapped_column(ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False)
    dataset_id: Mapped[str | None] = mapped_column(ForeignKey("datasets.id", ondelete="SET NULL"))
    parent_run_id: Mapped[str | None] = mapped_column(ForeignKey("pipeline_runs.id", ondelete="SET NULL"))
    triggered_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    input_records: Mapped[int | None] = mapped_column(Integer)
    output_records: Mapped[int | None] = mapped_column(Integer)
    quarantined_records: Mapped[int | None] = mapped_column(Integer)
    quality_score: Mapped[float | None] = mapped_column(Float)
    failed_stage: Mapped[str | None] = mapped_column(String(32))
    error_type: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    stage_log: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    anomaly: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    report: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    run_options: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    summary: Mapped[str] = mapped_column(Text, default="")
    processed_filename: Mapped[str | None] = mapped_column(String(255))
    quarantine_filename: Mapped[str | None] = mapped_column(String(255))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    pipeline: Mapped[Pipeline] = relationship()
    dataset: Mapped[Dataset | None] = relationship()
    incidents: Mapped[list["Incident"]] = relationship(back_populates="run")


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        CheckConstraint(f"severity IN {SEVERITIES}", name="ck_incidents_severity"),
        CheckConstraint(f"status IN {INCIDENT_STATUSES}", name="ck_incidents_status"),
        Index("ix_incidents_status_severity", "status", "severity"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    pipeline_id: Mapped[int] = mapped_column(ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False, index=True)
    incident_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    rule_id: Mapped[str] = mapped_column(String(48), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    probable_cause: Mapped[str] = mapped_column(Text, default="")
    recommended_action: Mapped[str] = mapped_column(Text, default="")
    recovery_policy: Mapped[str] = mapped_column(String(48), nullable=False, default="manual_investigation")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_notes: Mapped[str] = mapped_column(Text, default="")
    ai_analysis: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    run: Mapped[PipelineRun] = relationship(back_populates="incidents")
    pipeline: Mapped[Pipeline] = relationship()
    recovery_logs: Mapped[list["RecoveryLog"]] = relationship(back_populates="incident",
                                                             order_by="RecoveryLog.executed_at")


class RecoveryLog(Base):
    __tablename__ = "recovery_logs"
    __table_args__ = (
        CheckConstraint(f"result IN {RECOVERY_RESULTS}", name="ck_recovery_result"),
        CheckConstraint(f"approval_status IN {APPROVAL_STATUSES}", name="ck_recovery_approval"),
        CheckConstraint("attempt_number >= 1", name="ck_recovery_attempt_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True)
    recovery_run_id: Mapped[str | None] = mapped_column(ForeignKey("pipeline_runs.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(48), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")  # automatic | manual
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), unique=True)
    approval_status: Mapped[str] = mapped_column(String(16), nullable=False, default="not_required")
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)

    incident: Mapped[Incident] = relationship(back_populates="recovery_logs")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    username: Mapped[str] = mapped_column(String(64), default="system")
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(32), default="")
    resource_id: Mapped[str] = mapped_column(String(64), default="")
    outcome: Mapped[str] = mapped_column(String(16), default="success")
    ip_address: Mapped[str] = mapped_column(String(64), default="")
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
