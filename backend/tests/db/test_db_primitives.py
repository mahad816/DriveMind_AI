"""Tests for shared DB primitives used by Phase 2 models."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.enums import DriveFileStatus, IndexingJobStatus
from app.db.mixins import TimestampMixin


class DummyModel(TimestampMixin, Base):
    """Concrete model only for validating shared mixin behavior."""

    __tablename__ = "dummy_model"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)


def test_drive_file_status_values_are_stable() -> None:
    """Enum values should remain explicit for DB compatibility."""
    assert DriveFileStatus.DISCOVERED.value == "discovered"
    assert DriveFileStatus.INDEXED.value == "indexed"
    assert DriveFileStatus.FAILED.value == "failed"


def test_indexing_job_status_values_are_stable() -> None:
    """Enum values should remain explicit for job-state transitions."""
    assert IndexingJobStatus.QUEUED.value == "queued"
    assert IndexingJobStatus.RUNNING.value == "running"
    assert IndexingJobStatus.COMPLETED.value == "completed"


def test_timestamp_mixin_adds_expected_columns() -> None:
    """Timestamp mixin must provide non-null created_at and updated_at columns."""
    table = DummyModel.__table__
    assert "created_at" in table.columns
    assert "updated_at" in table.columns
    assert table.columns["created_at"].nullable is False
    assert table.columns["updated_at"].nullable is False
