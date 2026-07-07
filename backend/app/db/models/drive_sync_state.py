"""Persisted Drive Changes API cursor for incremental metadata sync."""

import uuid

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin


class DriveSyncState(TimestampMixin, Base):
    """Stores the Google Drive Changes API page token per user."""

    __tablename__ = "drive_sync_states"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    changes_page_token: Mapped[str] = mapped_column(Text, nullable=False)

    user = relationship("User", back_populates="drive_sync_state")
