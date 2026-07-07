"""Schemas for indexed Drive file and extracted content state."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.db.enums import DriveFileStatus
from app.schemas.common import IdentifierSchema, SchemaBase, TimestampedSchema


class DriveFileBase(SchemaBase):
    """Shared fields for Drive file representations."""

    drive_file_id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=1024)
    mime_type: str = Field(min_length=1, max_length=255)
    folder_path: str | None = Field(default=None, max_length=2048)
    modified_at: datetime
    indexed_at: datetime | None = None
    status: DriveFileStatus


class DriveFileRead(IdentifierSchema, TimestampedSchema, DriveFileBase):
    """Read model for indexed Drive file metadata."""

    user_id: UUID


class DocumentBase(SchemaBase):
    """Shared document fields after extraction step."""

    extracted_text_hash: str = Field(min_length=1, max_length=128)
    page_count: int | None = Field(default=None, ge=0)


class DocumentRead(IdentifierSchema, TimestampedSchema, DocumentBase):
    """Read model for extracted document metadata."""

    drive_file_id: UUID


class ChunkBase(SchemaBase):
    """Shared chunk fields used for retrieval and citations."""

    chunk_index: int = Field(ge=0)
    text: str = Field(min_length=1)
    metadata_json: dict[str, object]


class ChunkRead(IdentifierSchema, TimestampedSchema, ChunkBase):
    """Read model for chunk rows stored in PostgreSQL."""

    document_id: UUID
