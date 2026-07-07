"""Document ingestion service — fetch Drive content, extract text, persist documents."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.google_drive.client import DriveClientError
from app.connectors.google_drive.constants import SUPPORTED_MIME_TYPES, is_supported_mime_type
from app.core.config import Settings, get_settings
from app.db.enums import DriveFileStatus, IndexingJobStatus
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.db.models.google_oauth_token import GoogleOAuthToken
from app.db.models.indexing_job import IndexingJob
from app.db.models.user import User
from app.ingestion.extractors import (
    ExtractionError,
    UnsupportedMimeTypeError,
    get_extractor,
)
from app.ingestion.hash_util import compute_extracted_text_hash
from app.services.drive_content_service import DriveContentService


@dataclass
class IngestionResult:
    """Internal result from a text ingestion run."""

    job_id: uuid.UUID
    user_id: uuid.UUID
    ingested: int
    unchanged: int
    failed: int
    skipped: int
    total: int


class IngestionService:
    """Orchestrates Drive content fetch, text extraction, and document persistence."""

    def __init__(
        self,
        db: AsyncSession,
        settings: Settings | None = None,
        content_service: DriveContentService | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.content_service = content_service or DriveContentService(db, self.settings)

    async def _resolve_user(self, user_id: uuid.UUID | None) -> User:
        if user_id is not None:
            user = await self.db.get(User, user_id)
            if user is None:
                raise ValueError("User not found")
            return user

        token_row = await self.db.scalar(select(GoogleOAuthToken).limit(1))
        if token_row is None:
            raise ValueError("No Google Drive connection found. Complete OAuth first.")
        user = await self.db.get(User, token_row.user_id)
        if user is None:
            raise ValueError("Connected Google account has no user record")
        return user

    async def _get_drive_file(self, user_id: uuid.UUID, file_id: uuid.UUID) -> DriveFile:
        drive_file = await self.db.scalar(
            select(DriveFile).where(DriveFile.id == file_id, DriveFile.user_id == user_id)
        )
        if drive_file is None:
            raise ValueError("Synced file not found")
        return drive_file

    async def _list_ingestible_files(self, user_id: uuid.UUID) -> list[DriveFile]:
        result = await self.db.scalars(
            select(DriveFile)
            .where(
                DriveFile.user_id == user_id,
                DriveFile.status != DriveFileStatus.SKIPPED,
                DriveFile.mime_type.in_(list(SUPPORTED_MIME_TYPES)),
            )
            .order_by(DriveFile.modified_at.desc())
        )
        return list(result.all())

    async def _get_latest_document(self, drive_file_id: uuid.UUID) -> Document | None:
        document = await self.db.scalar(
            select(Document)
            .where(Document.drive_file_id == drive_file_id)
            .order_by(Document.updated_at.desc())
            .limit(1)
        )
        return document

    async def _ingest_single_file(
        self,
        drive_file: DriveFile,
    ) -> str:
        """Ingest one drive file. Returns 'ingested', 'unchanged', 'failed', or 'skipped'."""
        if drive_file.status == DriveFileStatus.SKIPPED:
            return "skipped"

        if not is_supported_mime_type(drive_file.mime_type):
            return "skipped"

        drive_file.status = DriveFileStatus.INDEXING

        try:
            content = await self.content_service.fetch_file_content(
                drive_file.id,
                user_id=drive_file.user_id,
            )
            extractor = get_extractor(drive_file.mime_type)
            extraction = await asyncio.to_thread(
                extractor.extract,
                content.data,
                mime_type=drive_file.mime_type,
                filename=drive_file.name,
            )
        except (ValueError, DriveClientError, UnsupportedMimeTypeError, ExtractionError):
            drive_file.status = DriveFileStatus.FAILED
            return "failed"

        text_hash = compute_extracted_text_hash(extraction.text)
        existing = await self._get_latest_document(drive_file.id)
        now = datetime.now(UTC)

        if existing is not None and existing.extracted_text_hash == text_hash:
            drive_file.status = DriveFileStatus.INDEXED
            drive_file.indexed_at = now
            return "unchanged"

        if existing is not None:
            existing.extracted_text = extraction.text
            existing.extracted_text_hash = text_hash
            existing.page_count = extraction.page_count
        else:
            self.db.add(
                Document(
                    drive_file_id=drive_file.id,
                    extracted_text=extraction.text,
                    extracted_text_hash=text_hash,
                    page_count=extraction.page_count,
                )
            )

        drive_file.status = DriveFileStatus.INDEXED
        drive_file.indexed_at = now
        return "ingested"

    async def ingest_files(
        self,
        user_id: uuid.UUID | None = None,
        *,
        file_id: uuid.UUID | None = None,
    ) -> IngestionResult:
        """Ingest one synced file or all supported files for the connected user."""
        user = await self._resolve_user(user_id)

        if file_id is not None:
            drive_files = [await self._get_drive_file(user.id, file_id)]
        else:
            drive_files = await self._list_ingestible_files(user.id)

        job = IndexingJob(user_id=user.id, status=IndexingJobStatus.QUEUED)
        self.db.add(job)
        await self.db.flush()

        job.status = IndexingJobStatus.RUNNING
        job.started_at = datetime.now(UTC)

        ingested = unchanged = failed = skipped = 0

        try:
            for drive_file in drive_files:
                outcome = await self._ingest_single_file(drive_file)
                if outcome == "ingested":
                    ingested += 1
                elif outcome == "unchanged":
                    unchanged += 1
                elif outcome == "failed":
                    failed += 1
                else:
                    skipped += 1

            job.status = IndexingJobStatus.COMPLETED
            job.completed_at = datetime.now(UTC)
            await self.db.commit()
        except Exception as exc:
            job.status = IndexingJobStatus.FAILED
            job.error = str(exc)
            job.completed_at = datetime.now(UTC)
            await self.db.commit()
            raise

        return IngestionResult(
            job_id=job.id,
            user_id=user.id,
            ingested=ingested,
            unchanged=unchanged,
            failed=failed,
            skipped=skipped,
            total=len(drive_files),
        )
