"""Schemas for Drive metadata sync API responses."""

from uuid import UUID

from pydantic import Field

from app.schemas.common import SchemaBase
from app.schemas.file import DriveFileRead
from app.schemas.indexing import IndexingJobRead


class DriveSyncResponse(SchemaBase):
    """Result returned after a Drive metadata sync completes."""

    job_id: UUID
    user_id: UUID
    created: int = Field(ge=0)
    updated: int = Field(ge=0)
    unchanged: int = Field(ge=0)
    total_seen: int = Field(ge=0)
    message: str


class DriveFileListResponse(SchemaBase):
    """Paginated-style list wrapper for synced Drive file metadata."""

    files: list[DriveFileRead]
    total: int = Field(ge=0)


class DriveSyncStatusResponse(SchemaBase):
    """Latest sync job status for the connected user."""

    job: IndexingJobRead | None = None
    connected: bool = False
