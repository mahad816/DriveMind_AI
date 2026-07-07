"""Drive metadata sync service — full and incremental sync into PostgreSQL."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.google_drive.client import (
    DriveChange,
    DriveClientError,
    DriveFileMetadata,
    DriveTokens,
    GoogleDriveClient,
    TokenPersister,
)
from app.connectors.google_drive.constants import is_supported_mime_type
from app.core.config import Settings, get_settings
from app.db.enums import DriveFileStatus, IndexingJobStatus
from app.db.models.drive_file import DriveFile
from app.db.models.drive_sync_state import DriveSyncState
from app.db.models.google_oauth_token import GoogleOAuthToken
from app.db.models.indexing_job import IndexingJob
from app.db.models.user import User

SyncMode = Literal["full", "incremental"]


@dataclass
class DriveSyncResult:
    """Internal result from a metadata sync run."""

    job_id: uuid.UUID
    user_id: uuid.UUID
    mode: SyncMode
    created: int
    updated: int
    unchanged: int
    removed: int
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

    async def _get_sync_state(self, user_id: uuid.UUID) -> DriveSyncState | None:
        state: DriveSyncState | None = await self.db.scalar(
            select(DriveSyncState).where(DriveSyncState.user_id == user_id)
        )
        return state

    async def _save_sync_state(self, user_id: uuid.UUID, changes_page_token: str) -> None:
        state = await self._get_sync_state(user_id)
        if state is None:
            self.db.add(
                DriveSyncState(
                    user_id=user_id,
                    changes_page_token=changes_page_token,
                )
            )
        else:
            state.changes_page_token = changes_page_token

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
            or existing.status == DriveFileStatus.SKIPPED
        )
        if not changed:
            return "unchanged"

        existing.name = metadata.name
        existing.mime_type = metadata.mime_type
        existing.modified_at = modified_at
        if existing.status == DriveFileStatus.SKIPPED:
            existing.status = DriveFileStatus.DISCOVERED
        return "updated"

    async def _mark_file_removed(self, user_id: uuid.UUID, drive_file_id: str) -> int:
        """Mark a synced file as skipped when Drive reports it removed. Returns 1 if updated."""
        if not drive_file_id:
            return 0
        existing = await self.db.scalar(
            select(DriveFile).where(
                DriveFile.drive_file_id == drive_file_id,
                DriveFile.user_id == user_id,
            )
        )
        if existing is None or existing.status == DriveFileStatus.SKIPPED:
            return 0
        existing.status = DriveFileStatus.SKIPPED
        return 1

    async def _apply_metadata(
        self,
        user_id: uuid.UUID,
        metadata: DriveFileMetadata,
    ) -> tuple[int, int, int]:
        outcome = await self._upsert_file(user_id, metadata)
        if outcome == "created":
            return 1, 0, 0
        if outcome == "updated":
            return 0, 1, 0
        return 0, 0, 1

    async def _run_full_sync(
        self,
        user: User,
        client: GoogleDriveClient,
    ) -> tuple[int, int, int, int]:
        drive_files = await asyncio.to_thread(client.list_files, supported_only=True)
        created = updated = unchanged = 0
        for metadata in drive_files:
            c, u, n = await self._apply_metadata(user.id, metadata)
            created += c
            updated += u
            unchanged += n

        page_token = await asyncio.to_thread(client.get_start_page_token)
        await self._save_sync_state(user.id, page_token)
        return created, updated, unchanged, len(drive_files)

    async def _run_incremental_sync(
        self,
        user: User,
        client: GoogleDriveClient,
        sync_state: DriveSyncState,
    ) -> tuple[int, int, int, int]:
        changes, new_token = await asyncio.to_thread(
            client.list_changes,
            sync_state.changes_page_token,
        )
        created = updated = unchanged = removed = 0
        for change in changes:
            removed += await self._process_change(user.id, change)
            if change.removed or change.file is None:
                continue
            if not is_supported_mime_type(change.file.mime_type):
                continue
            c, u, n = await self._apply_metadata(user.id, change.file)
            created += c
            updated += u
            unchanged += n

        await self._save_sync_state(user.id, new_token)
        return created, updated, unchanged, removed

    async def _process_change(self, user_id: uuid.UUID, change: DriveChange) -> int:
        if not change.removed:
            return 0
        return await self._mark_file_removed(user_id, change.file_id)

    async def sync_metadata(
        self,
        user_id: uuid.UUID | None = None,
        *,
        full: bool = False,
    ) -> DriveSyncResult:
        """Sync Drive metadata using full scan or incremental Changes API."""
        user = await self._resolve_user(user_id)
        token_row = await self._load_oauth_token(user.id)
        sync_state = await self._get_sync_state(user.id)
        mode: SyncMode = "full" if full or sync_state is None else "incremental"

        job = IndexingJob(user_id=user.id, status=IndexingJobStatus.QUEUED)
        self.db.add(job)
        await self.db.flush()

        job.status = IndexingJobStatus.RUNNING
        job.started_at = datetime.now(UTC)

        refreshed_tokens: list[DriveTokens] = []
        created = updated = unchanged = removed = 0
        total_seen = 0

        try:
            client = self._build_drive_client(token_row, refreshed_tokens)
            if mode == "full":
                created, updated, unchanged, total_seen = await self._run_full_sync(user, client)
            else:
                assert sync_state is not None
                created, updated, unchanged, removed = await self._run_incremental_sync(
                    user,
                    client,
                    sync_state,
                )
                total_seen = created + updated + unchanged + removed

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

        return DriveSyncResult(
            job_id=job.id,
            user_id=user.id,
            mode=mode,
            created=created,
            updated=updated,
            unchanged=unchanged,
            removed=removed,
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
