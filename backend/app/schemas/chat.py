"""Schemas for grounded chat API requests and responses."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field, StrictBool, field_validator, model_validator

from app.schemas.common import SchemaBase
from app.schemas.query import CitationItem


class ChatHistoryTurn(SchemaBase):
    """Untrusted prior message supplied by the current chat client."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=8_000)

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("History text must not be blank")
        return value


class ChatRequest(SchemaBase):
    """Payload for asking a grounded question over indexed Drive content."""

    question: str = Field(min_length=1, description="Natural-language question to answer")
    conversation_id: str | None = None
    history: list[ChatHistoryTurn] = Field(default_factory=list, max_length=8)
    history_window_complete: StrictBool = False

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Question must not be empty")
        return normalized

    @field_validator("conversation_id")
    @classmethod
    def validate_conversation_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Conversation ID must not be empty")
        return normalized

    @model_validator(mode="after")
    def validate_history_scope(self) -> ChatRequest:
        if self.history and self.conversation_id is None:
            raise ValueError("Non-empty history requires a conversation ID")
        if sum(len(turn.text) for turn in self.history) > 24_000:
            raise ValueError("History exceeds the 24,000-character limit")
        return self


class ChatResponse(SchemaBase):
    """Grounded answer returned from the chat endpoint."""

    query_id: UUID
    user_id: UUID
    answer: str = Field(min_length=1)
    citations: list[CitationItem] = Field(default_factory=list)
    retrieval_count: int = Field(ge=0)
    message: str
