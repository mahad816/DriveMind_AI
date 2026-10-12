"""Indexing job model."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import IndexingJobStatus, IndexingOperation
from app.db.mixins import TimestampMixin


class IndexingJob(TimestampMixin, Base):
    """Tracks indexing/sync job execution state and errors."""

    __tablename__ = "indexing_jobs"
    __table_args__ = (
        Index("ix_indexing_jobs_user_id_status", "user_id", "status"),
        Index(
            "uq_indexing_jobs_unresolved_owner",
            "user_id",
            unique=True,
            postgresql_where=text(
                "operation IS NOT NULL AND (status IN ('QUEUED', 'RUNNING') OR recovery_required)"
            ),
        ),
        CheckConstraint(
            "operation IS NULL OR operation IN ('SYNC', 'INGEST', 'CHUNK', 'BUILD')",
            name="ck_indexing_jobs_operation",
        ),
        CheckConstraint(
            "operation IS NULL OR (operation != 'SYNC' OR file_id IS NULL)",
            name="ck_indexing_jobs_sync_target",
        ),
        CheckConstraint(
            "operation IS NULL OR operation = 'SYNC' OR NOT full_sync",
            name="ck_indexing_jobs_full_sync",
        ),
        CheckConstraint(
            "NOT recovery_required OR operation IS NOT NULL",
            name="ck_indexing_jobs_recovery_operation",
        ),
        CheckConstraint(
            "total >= 0 AND processed >= 0 AND succeeded >= 0 AND failed >= 0 AND skipped >= 0",
            name="ck_indexing_jobs_progress",
        ),
    )

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

    # NULL operation is historical, never an executable managed job. file_id is
    # a historical target: deleting it must never turn this into an all-files job.
    operation: Mapped[IndexingOperation | None] = mapped_column(
        Enum(IndexingOperation, native_enum=False, create_constraint=False), nullable=True
    )
    file_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    full_sync: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    claim_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    worker_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    recovery_required: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    attempt_manifest: Mapped[dict[str, object] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )

    total: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    processed: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    succeeded: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    failed: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    skipped: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )

    user = relationship("User", back_populates="indexing_jobs")
