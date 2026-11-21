"""One admitted paid-question attempt (the quota ledger of M0-SEC ticket 05).

A row is a reservation, not proof that anything ran: it is either finished (a provider request
began, so it keeps counting) or released (deleted). Rows are keyed by a server-generated id; there
is no client-supplied key.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PaidQuestionAttempt(Base):
    __tablename__ = "paid_question_attempts"
    __table_args__ = (Index("ix_paid_question_attempts_owner_started", "owner_id", "started_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Cascade so a ledger row never blocks deleting a user (the KI-033 lesson).
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
