"""Bounded private conversation metadata, submission and durable status contracts."""

from datetime import datetime
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator

from app.schemas.common import SchemaBase
from app.schemas.query import CitationItem
from app.db.models.conversation_turn import TurnOperation, TurnStatus


class ConversationCreate(SchemaBase):
    model_config = ConfigDict(extra="forbid")
    create_request_id: UUID
    title: str = Field(default="New chat", min_length=1, max_length=256)

    @field_validator("title")
    @classmethod
    def valid_title(cls, value: str) -> str:
        title = value.strip()
        if not title:
            raise ValueError("Title must not be blank")
        return title


class ConversationRename(SchemaBase):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=256)
    expected_metadata_version: int = Field(strict=True, ge=1, le=2147483647)

    @field_validator("title")
    @classmethod
    def valid_title(cls, value: str) -> str:
        return ConversationCreate.valid_title(value)


class ConversationDelete(SchemaBase):
    model_config = ConfigDict(extra="forbid")
    expected_metadata_version: int = Field(strict=True, ge=1, le=2147483647)


class ConversationRead(SchemaBase):
    id: UUID
    title: str = Field(min_length=1, max_length=256)
    title_is_manual: bool
    created_at: datetime
    updated_at: datetime
    last_activity_at: datetime
    metadata_version: int = Field(gt=0)
    content_version: int = Field(ge=0)


class ConversationList(SchemaBase):
    conversations: list[ConversationRead] = Field(max_length=100)
    next_cursor: str | None = None


class SavedCitation(CitationItem):
    snippet: str = Field(min_length=1, max_length=8000)


class ConversationTurnRead(SchemaBase):
    id: UUID
    client_request_id: UUID
    sequence: int = Field(gt=0)
    question: str = Field(min_length=1, max_length=8000)
    operation: TurnOperation
    source_turn_id: UUID | None
    status: TurnStatus
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None
    error_code: str | None = None
    query_id: UUID | None = None
    answer: str | None = Field(default=None, min_length=1, max_length=131072)
    citations: list[SavedCitation] = Field(default_factory=list, max_length=64)
    retrieval_count: int = Field(ge=0)


class ConversationDetail(SchemaBase):
    conversation: ConversationRead
    turns: list[ConversationTurnRead] = Field(max_length=100)
    next_before_sequence: int | None = None


class ConversationSubmit(SchemaBase):
    model_config = ConfigDict(extra="forbid")
    client_request_id: UUID
    question: str = Field(min_length=1, max_length=4000)
    expected_content_version: int = Field(strict=True, ge=0, le=9223372036854775807)

    @field_validator("question")
    @classmethod
    def valid_question(cls, value: str) -> str:
        question = value.strip()
        if not question:
            raise ValueError("Question must not be blank")
        return question


class ConversationTurnStatus(ConversationTurnRead):
    execution_expired: bool = False


class ConversationSubmission(SchemaBase):
    turn: ConversationTurnStatus
    replayed: bool


class ConversationInterrupt(SchemaBase):
    model_config = ConfigDict(extra="forbid")
