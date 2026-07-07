"""Database enums shared across persistence models."""

from enum import StrEnum


class DriveFileStatus(StrEnum):
    """Lifecycle status for a synced Drive file record."""

    DISCOVERED = "discovered"
    INDEXING = "indexing"
    INDEXED = "indexed"
    FAILED = "failed"
    SKIPPED = "skipped"


class IndexingJobStatus(StrEnum):
    """Execution status for indexing and sync jobs."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"
