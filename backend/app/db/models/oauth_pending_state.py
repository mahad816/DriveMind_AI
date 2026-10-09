"""Legacy PKCE states and optional browser-bound application-login transactions."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Nullable secure fields preserve legacy OAuth transactions during additive rollout.
BOUND_STATE_CHECK = """
(browser_binding_hash IS NULL AND nonce IS NULL AND intent IS NULL
 AND initiating_session_id IS NULL AND initiating_credential_hash IS NULL)
OR (browser_binding_hash IS NOT NULL AND octet_length(browser_binding_hash) = 32
 AND nonce IS NOT NULL AND length(nonce) = 43 AND intent IS NOT NULL
 AND intent IN ('LOGIN', 'CONNECT_DRIVE')
 AND (initiating_credential_hash IS NULL OR octet_length(initiating_credential_hash) = 32)
 AND (initiating_session_id IS NULL OR initiating_credential_hash IS NOT NULL)
 AND (intent = 'LOGIN' OR
      (initiating_session_id IS NOT NULL AND initiating_credential_hash IS NOT NULL)))
"""


class OAuthPendingState(Base):
    __tablename__ = "oauth_pending_states"
    __table_args__ = (CheckConstraint(BOUND_STATE_CHECK, name="ck_oauth_pending_bound_state"),)

    state: Mapped[str] = mapped_column(String(255), primary_key=True)
    code_verifier: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    browser_binding_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    nonce: Mapped[str | None] = mapped_column(String(43), nullable=True)
    intent: Mapped[str | None] = mapped_column(String(20), nullable=True)
    initiating_session_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("application_sessions.id", ondelete="CASCADE"),
        nullable=True,
    )
    initiating_credential_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
