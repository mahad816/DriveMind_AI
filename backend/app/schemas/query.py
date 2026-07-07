"""Schemas for persisted query history and citation traces."""

from uuid import UUID

from pydantic import Field

from app.schemas.common import IdentifierSchema, SchemaBase, TimestampedSchema


class CitationItem(SchemaBase):
    """Single citation entry associated with an answer."""

    chunk_id: UUID
    drive_file_id: UUID
    filename: str = Field(min_length=1, max_length=1024)
    snippet: str = Field(min_length=1)
    score: float | None = Field(default=None, ge=0.0, le=1.0)


class QueryHistoryCreate(SchemaBase):
    """Payload for storing a completed question/answer interaction."""

    user_id: UUID
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    citations: list[CitationItem] = Field(default_factory=list)


class QueryHistoryRead(IdentifierSchema, TimestampedSchema):
    """Read model for query history records."""

    user_id: UUID
    question: str
    answer: str
    citations_json: list[dict[str, object]]
