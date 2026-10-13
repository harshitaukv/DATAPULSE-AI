"""A small, explicit workflow engine.

Stages run in order. Each stage moves through PENDING -> RUNNING -> SUCCEEDED |
FAILED | SKIPPED. Only errors classified as retryable (TransientError, database
OperationalError) are retried, with exponential backoff and a hard retry limit.
Every attempt is recorded so the recovery history is auditable.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import OperationalError

from app.processing.errors import PipelineError, TransientError


@dataclass
class RetryPolicy:
    max_retries: int = 2
    base_delay: float = 0.5
    factor: float = 2.0

    def delay_for(self, retry_number: int) -> float:
        """Delay before retry #retry_number (1-based): base * factor^(n-1)."""
        return self.base_delay * (self.factor ** (retry_number - 1))


def is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, PipelineError):
        return exc.retryable
    return isinstance(exc, (OperationalError, TimeoutError, ConnectionError))


@dataclass
class AttemptRecord:
    attempt: int
    status: str
    started_at: str
    duration_seconds: float
    error_type: str | None = None
    error: str | None = None
    retry_delay_seconds: float | None = None
    retryable: bool = False


@dataclass
class StageRecord:
    name: str
    status: str = "pending"
    attempts: list[AttemptRecord] = field(default_factory=list)
    duration_seconds: float = 0.0

    def to_dict(self) -> dict:
        return {"name": self.name, "status": self.status, "duration_seconds": round(self.duration_seconds, 4),
                "attempts": [a.__dict__ for a in self.attempts]}


@dataclass
class WorkflowOutcome:
    status: str  # succeeded | failed
    stages: list[StageRecord]
    failed_stage: str | None = None
    error: BaseException | None = None

    @property
    def retries(self) -> list[tuple[str, AttemptRecord]]:
        """Failed attempts whose error was classified as retryable (transient)."""
        return [(s.name, a) for s in self.stages for a in s.attempts if a.status == "failed" and a.retryable]


class FaultInjector:
    """Deterministic failure simulation for testing recovery paths.

    Only enabled when ENABLE_FAULT_INJECTION is true and the caller is authorised.
    Injected errors are labelled 'Simulated' in every message and record.
    """

    def __init__(self, stage: str, fail_times: int, kind: str = "transient_db"):
        self.stage, self.remaining, self.kind = stage, fail_times, kind

    def check(self, stage: str) -> None:
        if stage == self.stage and self.remaining > 0:
            self.remaining -= 1
            if self.kind == "transient_db":
                raise TransientError("Simulated transient failure: database connection reset during write",
                                     {"simulated": True})
            raise PipelineError("Simulated non-retryable stage failure", {"simulated": True})


class WorkflowEngine:
    def __init__(self, stages: list[tuple[str, Callable[[Any], None]]], retry_policy: RetryPolicy,
                 sleep: Callable[[float], None] = time.sleep, fault: FaultInjector | None = None):
        self.stages = stages
        self.retry_policy = retry_policy
        self.sleep = sleep
        self.fault = fault

    def run(self, context: Any) -> WorkflowOutcome:
        records = [StageRecord(name) for name, _ in self.stages]
        for (name, fn), record in zip(self.stages, records):
            record.status = "running"
            attempt = 0
            while True:
                attempt += 1
                started = time.perf_counter()
                stamp = datetime.now(timezone.utc).isoformat()
                try:
                    if self.fault:
                        self.fault.check(name)
                    fn(context)
                    elapsed = time.perf_counter() - started
                    record.attempts.append(AttemptRecord(attempt, "succeeded", stamp, round(elapsed, 4)))
                    record.duration_seconds += elapsed
                    record.status = "succeeded"
                    break
                except Exception as exc:  # noqa: BLE001 - classified below
                    elapsed = time.perf_counter() - started
                    record.duration_seconds += elapsed
                    retryable = is_retryable(exc)
                    retry_allowed = retryable and attempt <= self.retry_policy.max_retries
                    delay = self.retry_policy.delay_for(attempt) if retry_allowed else None
                    record.attempts.append(AttemptRecord(
                        attempt, "failed", stamp, round(elapsed, 4),
                        getattr(exc, "error_type", type(exc).__name__), _safe_message(exc), delay, retryable))
                    if retry_allowed:
                        self.sleep(delay)
                        continue
                    record.status = "failed"
                    for later in records[records.index(record) + 1:]:
                        later.status = "skipped"
                    return WorkflowOutcome("failed", records, failed_stage=name, error=exc)
        return WorkflowOutcome("succeeded", records)


def _safe_message(exc: BaseException) -> str:
    """Error text without local filesystem paths or excessive length."""
    import re
    msg = str(exc) or type(exc).__name__
    msg = re.sub(r"(/[\w.\-]+){2,}", "<path>", msg)
    msg = re.sub(r"[A-Za-z]:\\[^\s'\"]+", "<path>", msg)
    return msg[:500]
