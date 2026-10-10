"""Google OAuth token persistence for Drive API access."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin


class GoogleOAuthToken(TimestampMixin, Base):
    """Stored OAuth tokens for a user's Google Drive read-only access."""

    __tablename__ = "google_oauth_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    encrypted_credentials: Mapped[str] = mapped_column(Text, nullable=False)
    grant_status: Mapped[str] = mapped_column(String(24), server_default="ACTIVE", nullable=False)
    credential_revision: Mapped[int] = mapped_column(
        BigInteger, server_default=text("1"), nullable=False
    )
    grant_epoch: Mapped[int] = mapped_column(BigInteger, server_default=text("1"), nullable=False)
    refresh_claim_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    refresh_claim_state: Mapped[str | None] = mapped_column(String(16))
    refresh_claim_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "grant_status IN ('ACTIVE','RECOVERY_REQUIRED','REAUTH_REQUIRED')",
            name="ck_google_grant_status",
        ),
        CheckConstraint(
            "credential_revision >= 1 AND grant_epoch >= 1", name="ck_google_grant_versions"
        ),
        CheckConstraint(
            "length(encrypted_credentials) BETWEEN 1 AND 32768", name="ck_google_envelope_size"
        ),
        CheckConstraint(
            "(refresh_claim_id IS NULL AND refresh_claim_state IS NULL AND refresh_claim_expires_at IS NULL) OR (refresh_claim_id IS NOT NULL AND refresh_claim_state IS NOT NULL AND refresh_claim_state IN ('PREPARED','SUBMITTED') AND refresh_claim_expires_at IS NOT NULL)",
            name="ck_google_refresh_claim",
        ),
    )
    token_expiry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[str] = mapped_column(Text, nullable=False)

    user = relationship("User", back_populates="google_oauth_token")
