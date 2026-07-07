"""Drive metadata sync service — lists Drive files and upserts into PostgreSQL."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.google_drive.client import (
    DriveClientError,
    DriveFileMetadata,
    DriveTokens,
    GoogleDriveClient,
    TokenPersister,
)
from app.core.config import Settings, get_settings
from app.db.enums import DriveFileStatus, IndexingJobStatus
from app.db.models.drive_file import DriveFile
from app.db.models.google_oauth_token import GoogleOAuthToken
from app.db.models.indexing_job import IndexingJob
from app.db.models.user import User


@dataclass
class DriveSyncResult:
    """Internal result from a metadata sync run."""

    job_id: uuid.UUID
    user_id: uuid.UUID
    created: int
    updated: int
    unchanged: int
    total_seen: int


class DriveSyncService:
    """Syncs supported Google Drive file metadata into the drive_files table."""

    def __init__(self, db: AsyncSession, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

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

    async def _load_oauth_token(self, user_id: uuid.UUID) -> GoogleOAuthToken:
        token_row = await self.db.scalar(
            select(GoogleOAuthToken).where(GoogleOAuthToken.user_id == user_id)
        )
        if token_row is None:
            raise ValueError("No Google Drive connection found. Complete OAuth first.")
        return token_row

    @staticmethod
    def _parse_drive_timestamp(value: str | None) -> datetime:
        if not value:
            return datetime.now(UTC)
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed

    def _build_drive_client(
        self,
        token_row: GoogleOAuthToken,
        on_token_refresh: list[DriveTokens],
    ) -> GoogleDriveClient:
        tokens = DriveTokens(
            access_token=token_row.access_token,
            refresh_token=token_row.refresh_token,
            token_expiry=token_row.token_expiry,
            scopes=token_row.scopes,
        )

        def capture_refresh(updated: DriveTokens) -> None:
            on_token_refresh.append(updated)

        return GoogleDriveClient(
            tokens=tokens,
            settings=self.settings,
            on_token_refresh=cast(TokenPersister, capture_refresh),
        )

    async def _persist_refreshed_tokens(
        self,
        token_row: GoogleOAuthToken,
        refreshed: list[DriveTokens],
    ) -> None:
        if not refreshed:
            return
        latest = refreshed[-1]
        token_row.access_token = latest.access_token
        if latest.refresh_token:
            token_row.refresh_token = latest.refresh_token
        token_row.token_expiry = latest.token_expiry
        token_row.scopes = latest.scopes

    async def _upsert_file(
        self,
        user_id: uuid.UUID,
        metadata: DriveFileMetadata,
    ) -> str:
        """Insert or update a drive_files row. Returns 'created', 'updated', or 'unchanged'."""
        existing = await self.db.scalar(
            select(DriveFile).where(DriveFile.drive_file_id == metadata.id)
        )
        modified_at = self._parse_drive_timestamp(metadata.modified_time)

        if existing is None:
            self.db.add(
                DriveFile(
                    user_id=user_id,
                    drive_file_id=metadata.id,
                    name=metadata.name,
                    mime_type=metadata.mime_type,
                    folder_path=None,
                    modified_at=modified_at,
                    status=DriveFileStatus.DISCOVERED,
                )
            )
            return "created"

        changed = (
            existing.name != metadata.name
            or existing.mime_type != metadata.mime_type
            or existing.modified_at != modified_at
        )
        if not changed:
            return "unchanged"

        existing.name = metadata.name
        existing.mime_type = metadata.mime_type
        existing.modified_at = modified_at
        return "updated"

    async def sync_metadata(self, user_id: uuid.UUID | None = None) -> DriveSyncResult:
        """List supported Drive files and upsert metadata into PostgreSQL."""
        user = await self._resolve_user(user_id)
        token_row = await self._load_oauth_token(user.id)

        job = IndexingJob(user_id=user.id, status=IndexingJobStatus.QUEUED)
        self.db.add(job)
        await self.db.flush()

        job.status = IndexingJobStatus.RUNNING
        job.started_at = datetime.now(UTC)

        refreshed_tokens: list[DriveTokens] = []
        created = updated = unchanged = 0

        try:
            client = self._build_drive_client(token_row, refreshed_tokens)
            drive_files = await asyncio.to_thread(client.list_files, supported_only=True)

            for metadata in drive_files:
                outcome = await self._upsert_file(user.id, metadata)
                if outcome == "created":
                    created += 1
                elif outcome == "updated":
                    updated += 1
                else:
                    unchanged += 1

            await self._persist_refreshed_tokens(token_row, refreshed_tokens)

            job.status = IndexingJobStatus.COMPLETED
            job.completed_at = datetime.now(UTC)
            await self.db.commit()
        except (DriveClientError, ValueError) as exc:
            job.status = IndexingJobStatus.FAILED
            job.error = str(exc)
            job.completed_at = datetime.now(UTC)
            await self.db.commit()
            raise
        except Exception as exc:
            job.status = IndexingJobStatus.FAILED
            job.error = str(exc)
            job.completed_at = datetime.now(UTC)
            await self.db.commit()
            raise DriveClientError(f"Drive metadata sync failed: {exc}") from exc

        total_seen = created + updated + unchanged
        return DriveSyncResult(
            job_id=job.id,
            user_id=user.id,
            created=created,
            updated=updated,
            unchanged=unchanged,
            total_seen=total_seen,
        )

    async def get_latest_sync_job(self, user_id: uuid.UUID | None = None) -> IndexingJob | None:
        """Return the most recent indexing job for the resolved user."""
        user = await self._resolve_user(user_id)
        job = await self.db.scalar(
            select(IndexingJob)
            .where(IndexingJob.user_id == user.id)
            .order_by(IndexingJob.created_at.desc())
            .limit(1)
        )
        return job

    async def list_synced_files(self, user_id: uuid.UUID | None = None) -> list[DriveFile]:
        """Return all drive_files rows for the resolved user."""
        user = await self._resolve_user(user_id)
        result = await self.db.scalars(
            select(DriveFile)
            .where(DriveFile.user_id == user.id)
            .order_by(DriveFile.modified_at.desc())
        )
        return list(result.all())

    async def is_connected(self, user_id: uuid.UUID | None = None) -> bool:
        """Return True when the user has a stored Google OAuth token."""
        try:
            user = await self._resolve_user(user_id)
        except ValueError:
            return False
        token_row = await self.db.scalar(
            select(GoogleOAuthToken).where(GoogleOAuthToken.user_id == user.id)
        )
        return token_row is not None
