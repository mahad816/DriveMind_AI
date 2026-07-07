"""User model for DriveMind single-user MVP."""

import uuid

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin


class User(TimestampMixin, Base):
    """Application user linked to Google account identity."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    google_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)

    drive_files = relationship("DriveFile", back_populates="user")
    indexing_jobs = relationship("IndexingJob", back_populates="user")
    query_history = relationship("QueryHistory", back_populates="user")
