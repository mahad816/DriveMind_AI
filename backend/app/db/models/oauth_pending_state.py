"""Short-lived OAuth PKCE state storage for Google login callback validation."""

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OAuthPendingState(Base):
    """Stores OAuth state + PKCE verifier between login redirect and callback.

    Survives uvicorn reloads (unlike in-memory storage). Rows are single-use
    and should expire after a short TTL.
    """

    __tablename__ = "oauth_pending_states"

    state: Mapped[str] = mapped_column(String(255), primary_key=True)
    code_verifier: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
