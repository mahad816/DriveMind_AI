"""Schemas for citation source viewer responses."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.schemas.common import SchemaBase


class SourceChunkRead(SchemaBase):
    """Full chunk text and file metadata for a citation source viewer."""

    chunk_id: UUID
    drive_file_id: UUID
    filename: str = Field(min_length=1, max_length=1024)
    mime_type: str = Field(min_length=1, max_length=255)
    chunk_index: int = Field(ge=0)
    text: str = Field(min_length=1)
    modified_at: datetime
