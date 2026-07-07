"""Indexing job model."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import IndexingJobStatus
from app.db.mixins import TimestampMixin


class IndexingJob(TimestampMixin, Base):
    """Tracks indexing/sync job execution state and errors."""

    __tablename__ = "indexing_jobs"
    __table_args__ = (Index("ix_indexing_jobs_user_id_status", "user_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[IndexingJobStatus] = mapped_column(
        Enum(IndexingJobStatus, name="indexing_job_status", native_enum=False),
        default=IndexingJobStatus.QUEUED,
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    user = relationship("User", back_populates="indexing_jobs")
