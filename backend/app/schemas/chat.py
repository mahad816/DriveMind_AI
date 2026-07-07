"""Schemas for grounded chat API requests and responses."""

from uuid import UUID

from pydantic import Field, field_validator

from app.schemas.common import SchemaBase
from app.schemas.query import CitationItem


class ChatRequest(SchemaBase):
    """Payload for asking a grounded question over indexed Drive content."""

    question: str = Field(min_length=1, description="Natural-language question to answer")

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Question must not be empty")
        return normalized


class ChatResponse(SchemaBase):
    """Grounded answer returned from the chat endpoint."""

    query_id: UUID
    user_id: UUID
    answer: str = Field(min_length=1)
    citations: list[CitationItem] = Field(default_factory=list)
    retrieval_count: int = Field(ge=0)
    message: str
