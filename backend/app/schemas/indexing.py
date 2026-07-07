"""Schemas for indexing job requests and status responses."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.db.enums import IndexingJobStatus
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


class IndexingStatusSummary(SchemaBase):
    """Aggregate status counters for indexing dashboard endpoints."""

    queued: int = Field(default=0, ge=0)
    running: int = Field(default=0, ge=0)
    completed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    canceled: int = Field(default=0, ge=0)
