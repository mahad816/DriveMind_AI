"""Shared browser sessions; corpus ownership is derived by server code."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    LargeBinary,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.enums import ApplicationSessionKind


class ApplicationSession(Base):
    __tablename__ = "application_sessions"
    __table_args__ = (
        CheckConstraint(
            "(kind = 'GOOGLE_ACCOUNT' AND user_id IS NOT NULL) OR "
            "(kind = 'DEMO_VISITOR' AND user_id IS NULL)",
            name="ck_application_sessions_owner",
        ),
        CheckConstraint(
            "octet_length(credential_hash) = 32", name="ck_application_sessions_digest"
        ),
        CheckConstraint("octet_length(csrf_secret) = 32", name="ck_application_sessions_csrf"),
        CheckConstraint("expires_at > created_at", name="ck_application_sessions_expiry"),
        UniqueConstraint("credential_hash", name="uq_application_sessions_credential_hash"),
        Index("ix_application_sessions_user_id", "user_id"),
        Index("ix_application_sessions_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    credential_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    kind: Mapped[ApplicationSessionKind] = mapped_column(
        Enum(
            ApplicationSessionKind,
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            name="ck_application_sessions_kind",
        ),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    csrf_secret: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
