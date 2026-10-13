"""Pipeline error taxonomy. `retryable` drives the recovery policies."""
from __future__ import annotations


class PipelineError(Exception):
    error_type = "pipeline_error"
    retryable = False

    def __init__(self, message: str, evidence: dict | None = None):
        super().__init__(message)
        self.evidence = evidence or {}


class TransientError(PipelineError):
    """A failure expected to succeed on retry (connection reset, lock timeout, I/O hiccup)."""
    error_type = "transient_failure"
    retryable = True


class SchemaValidationError(PipelineError):
    error_type = "schema_mismatch"


class IncompleteInputError(PipelineError):
    error_type = "incomplete_input"


class TransformationError(PipelineError):
    error_type = "transformation_failure"
