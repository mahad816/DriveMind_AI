"""Schemas for indexing job requests and status responses."""

from datetime import datetime
from uuid import UUID
from typing import Literal

from pydantic import Field, field_validator

from app.db.enums import IndexingJobStatus, IndexingOperation
from app.schemas.common import IdentifierSchema, SchemaBase, TimestampedSchema


class IndexingJobCreate(SchemaBase):
    """Payload to create an indexing job record."""

    user_id: UUID
    status: IndexingJobStatus = IndexingJobStatus.QUEUED


class IndexingJobRead(IdentifierSchema, TimestampedSchema):
    """Read model for indexing job lifecycle state."""

    user_id: UUID
    status: IndexingJobStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None

    operation: IndexingOperation | None = None
    file_id: UUID | None = None
    full_sync: bool = False
    recovery_required: bool = False
    total: int = 0
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0

    @field_validator("error", mode="before")
    @classmethod
    def safe_error(cls, value: object) -> str | None:
        # Historical/provider strings are not a public diagnostic contract.
        if value is None:
            return None
        # Only complete fixed application diagnostics are eligible for exposure.
        allowed = {
            f"{operation} failed ({category})."
            for operation in (
                "Drive sync",
                "drive sync job",
                "ingestion job",
                "chunking job",
                "indexing job",
            )
            for category in (
                "authentication_expired",
                "reauthorization_required",
                "temporary_provider_failure",
                "configuration_error",
                "unexpected_failure",
            )
        }
        return (
            value
            if isinstance(value, str) and value in allowed
            else "Indexing job failed. Review its status before retrying."
        )


class IndexingJobAccepted(SchemaBase):
    job_id: UUID
    status: Literal["queued"] = "queued"
    message: str = "Job accepted; poll /index/status with this job_id."


class IndexingStatusSummary(SchemaBase):
    """Aggregate status counters for indexing dashboard endpoints."""

    queued: int = Field(default=0, ge=0)
    running: int = Field(default=0, ge=0)
    completed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    canceled: int = Field(default=0, ge=0)
