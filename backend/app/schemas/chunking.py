"""Schemas for document chunking API responses."""

from uuid import UUID

from pydantic import Field

from app.schemas.common import SchemaBase


class ChunkingResponse(SchemaBase):
    """Result returned after a document chunking run completes."""

    job_id: UUID
    user_id: UUID
    chunked: int = Field(ge=0)
    unchanged: int = Field(ge=0)
    skipped: int = Field(ge=0)
    total: int = Field(ge=0)
    message: str
