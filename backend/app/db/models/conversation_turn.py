"""Ordered immutable submissions with owner-bound successful result references."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class TurnStatus(StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"


class TurnOperation(StrEnum):
    ASK = "ASK"
    RETRY = "RETRY"
    REGENERATE = "REGENERATE"


class ConversationTurn(TimestampMixin, Base):
    __tablename__ = "conversation_turns"
    __table_args__ = (
        ForeignKeyConstraint(
            ["conversation_id", "owner_id"],
            ["conversations.id", "conversations.owner_id"],
            ondelete="CASCADE",
            name="fk_turns_conversation_owner",
        ),
        ForeignKeyConstraint(
            ["source_turn_id", "conversation_id", "owner_id"],
            [
                "conversation_turns.id",
                "conversation_turns.conversation_id",
                "conversation_turns.owner_id",
            ],
            name="fk_turns_source_owner",
        ),
        ForeignKeyConstraint(
            ["query_history_id", "owner_id"],
            ["query_history.id", "query_history.user_id"],
            name="fk_turns_result_owner",
        ),
        ForeignKeyConstraint(
            ["initiating_session_id", "owner_id"],
            ["application_sessions.id", "application_sessions.user_id"],
            name="fk_turns_session_owner",
        ),
        UniqueConstraint(
            "id", "conversation_id", "owner_id", name="uq_turns_id_conversation_owner"
        ),
        UniqueConstraint("owner_id", "client_request_id", name="uq_turns_owner_request"),
        UniqueConstraint("conversation_id", "sequence", name="uq_turns_conversation_sequence"),
        UniqueConstraint("query_history_id", name="uq_turns_result"),
        CheckConstraint(
            "status IN ('RUNNING', 'COMPLETED', 'FAILED', 'INTERRUPTED')", name="ck_turns_status"
        ),
        CheckConstraint("operation IN ('ASK', 'RETRY', 'REGENERATE')", name="ck_turns_operation"),
        CheckConstraint(
            "(operation = 'ASK' AND source_turn_id IS NULL) OR (operation IN ('RETRY', 'REGENERATE') AND source_turn_id IS NOT NULL AND source_turn_id <> id)",
            name="ck_turns_source",
        ),
        CheckConstraint(
            "sequence > 0 AND history_end_sequence >= 0 AND history_end_sequence < sequence",
            name="ck_turns_sequence",
        ),
        CheckConstraint("original_question ~ '[^[:space:]]'", name="ck_turns_question"),
        CheckConstraint("octet_length(payload_hash) = 32", name="ck_turns_payload_hash"),
        CheckConstraint("retrieval_count >= 0", name="ck_turns_retrieval_count"),
        CheckConstraint(
            "(status = 'COMPLETED') = (query_history_id IS NOT NULL)", name="ck_turns_result"
        ),
        CheckConstraint(
            "(status = 'RUNNING' AND finished_at IS NULL AND error_code IS NULL) OR (status = 'COMPLETED' AND finished_at IS NOT NULL AND error_code IS NULL) OR (status IN ('FAILED', 'INTERRUPTED') AND finished_at IS NOT NULL AND error_code IS NOT NULL)",
            name="ck_turns_terminal",
        ),
        CheckConstraint(
            "error_code IS NULL OR error_code ~ '^[A-Z][A-Z0-9_]{0,63}$'",
            name="ck_turns_error_code",
        ),
        CheckConstraint("execution_deadline > created_at", name="ck_turns_deadline"),
        Index(
            "uq_turns_running_conversation",
            "conversation_id",
            unique=True,
            postgresql_where=text("status = 'RUNNING'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    client_request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payload_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    original_question: Mapped[str] = mapped_column(Text, nullable=False)
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    source_turn_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    history_end_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="RUNNING", server_default="RUNNING"
    )
    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    execution_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    initiating_session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    retrieval_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    query_history_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
