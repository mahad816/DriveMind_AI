"""Normal-account conversation metadata; no browser history import."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    BigInteger,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("id", "owner_id", name="uq_conversations_id_owner"),
        UniqueConstraint("owner_id", "create_request_id", name="uq_conversations_create_request"),
        CheckConstraint(
            "char_length(title) BETWEEN 1 AND 256 AND title = btrim(title) AND title ~ '[^[:space:]]'",
            name="ck_conversations_title",
        ),
        CheckConstraint(
            "metadata_version > 0 AND content_version >= 0 AND next_sequence > 0",
            name="ck_conversations_versions",
        ),
        CheckConstraint(
            "octet_length(create_payload_hash) = 32", name="ck_conversations_payload_hash"
        ),
        Index(
            "ix_conversations_owner_activity",
            "owner_id",
            text("last_activity_at DESC"),
            text("id DESC"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(
        String(256), nullable=False, default="New chat", server_default="New chat"
    )
    title_is_manual: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    metadata_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    content_version: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    next_sequence: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=1, server_default="1"
    )
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    create_request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    create_payload_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
