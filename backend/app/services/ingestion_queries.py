"""Shared SQL conditions for deciding which files still need to be read from Drive."""

from __future__ import annotations

from sqlalchemy import and_, exists, select
from sqlalchemy.sql.elements import ColumnElement

from app.db.enums import DriveFileStatus
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.ingestion.pipeline_version import EXTRACTION_PIPELINE_VERSION


def stale_pipeline_clause() -> ColumnElement[bool]:
    """Indexed files whose text was extracted by an older pipeline and should be read again.

    One definition for the ingest list and the "pending work" counts, so the frontend starts an
    ingest exactly when there is something for it to do.
    """
    return and_(
        DriveFile.status == DriveFileStatus.INDEXED,
        exists(
            select(Document.id).where(
                Document.drive_file_id == DriveFile.id,
                Document.pipeline_version < EXTRACTION_PIPELINE_VERSION,
            )
        ),
    )
