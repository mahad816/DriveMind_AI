"""Mocked tests for Drive metadata sync service (Phase 3 Milestone 4)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.connectors.google_drive.client import DriveClientError, DriveFileMetadata
from app.db.enums import DriveFileStatus, IndexingJobStatus
from app.db.models.drive_file import DriveFile
from app.db.models.google_oauth_token import GoogleOAuthToken
from app.db.models.indexing_job import IndexingJob
from app.db.models.user import User
from app.services.drive_sync_service import DriveSyncService

USER_ID = uuid.uuid4()
TOKEN_ROW = GoogleOAuthToken(
    id=uuid.uuid4(),
    user_id=USER_ID,
    access_token="access",
    refresh_token="refresh",
    token_expiry=datetime.now(UTC),
    scopes="https://www.googleapis.com/auth/drive.readonly",
)
USER = User(id=USER_ID, email="user@example.com", google_id="gid-1")


def _metadata(
    file_id: str = "file-1",
    name: str = "doc.pdf",
    mime: str = "application/pdf",
    modified: str = "2026-07-07T10:00:00.000Z",
) -> DriveFileMetadata:
    return DriveFileMetadata(id=file_id, name=name, mime_type=mime, modified_time=modified)


@pytest.fixture
def mock_db() -> AsyncMock:
    db = AsyncMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.fixture
def service(mock_db: AsyncMock) -> DriveSyncService:
    return DriveSyncService(db=mock_db, settings=MagicMock())


def test_parse_drive_timestamp_handles_z_suffix(service: DriveSyncService) -> None:
    parsed = service._parse_drive_timestamp("2026-07-07T10:00:00.000Z")
    assert parsed.tzinfo is not None
    assert parsed.year == 2026


@pytest.mark.asyncio
async def test_upsert_file_creates_new_row(service: DriveSyncService, mock_db: AsyncMock) -> None:
    mock_db.scalar = AsyncMock(return_value=None)

    outcome = await service._upsert_file(USER_ID, _metadata())

    assert outcome == "created"
    mock_db.add.assert_called_once()
    added = mock_db.add.call_args[0][0]
    assert isinstance(added, DriveFile)
    assert added.drive_file_id == "file-1"
    assert added.status == DriveFileStatus.DISCOVERED


@pytest.mark.asyncio
async def test_upsert_file_updates_when_metadata_changed(
    service: DriveSyncService,
    mock_db: AsyncMock,
) -> None:
    existing = DriveFile(
        id=uuid.uuid4(),
        user_id=USER_ID,
        drive_file_id="file-1",
        name="old.pdf",
        mime_type="application/pdf",
        modified_at=datetime(2026, 1, 1, tzinfo=UTC),
        status=DriveFileStatus.DISCOVERED,
    )
    mock_db.scalar = AsyncMock(return_value=existing)

    outcome = await service._upsert_file(USER_ID, _metadata(name="new.pdf"))

    assert outcome == "updated"
    assert existing.name == "new.pdf"


@pytest.mark.asyncio
async def test_upsert_file_unchanged_when_metadata_matches(
    service: DriveSyncService,
    mock_db: AsyncMock,
) -> None:
    modified = service._parse_drive_timestamp("2026-07-07T10:00:00.000Z")
    existing = DriveFile(
        id=uuid.uuid4(),
        user_id=USER_ID,
        drive_file_id="file-1",
        name="doc.pdf",
        mime_type="application/pdf",
        modified_at=modified,
        status=DriveFileStatus.DISCOVERED,
    )
    mock_db.scalar = AsyncMock(return_value=existing)

    outcome = await service._upsert_file(USER_ID, _metadata())

    assert outcome == "unchanged"


@pytest.mark.asyncio
async def test_sync_metadata_no_connection_raises(service: DriveSyncService, mock_db: AsyncMock) -> None:
    mock_db.scalar = AsyncMock(return_value=None)

    with pytest.raises(ValueError, match="No Google Drive connection"):
        await service.sync_metadata()


@pytest.mark.asyncio
async def test_sync_metadata_success(service: DriveSyncService, mock_db: AsyncMock) -> None:
    mock_client = MagicMock()
    mock_client.list_files.return_value = [
        _metadata("file-1"),
        _metadata("file-2", name="notes.txt", mime="text/plain"),
    ]

    mock_db.scalar = AsyncMock(return_value=TOKEN_ROW)
    mock_db.get = AsyncMock(return_value=USER)

    async def always_create(_user_id: uuid.UUID, _meta: DriveFileMetadata) -> str:
        return "created"

    with (
        patch.object(service, "_build_drive_client", return_value=mock_client),
        patch.object(service, "_upsert_file", side_effect=always_create),
    ):
        result = await service.sync_metadata()

    assert result.created == 2
    assert result.updated == 0
    assert result.unchanged == 0
    assert result.total_seen == 2
    mock_db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_sync_metadata_marks_job_failed_on_drive_error(
    service: DriveSyncService,
    mock_db: AsyncMock,
) -> None:
    mock_db.scalar = AsyncMock(return_value=TOKEN_ROW)
    mock_db.get = AsyncMock(return_value=USER)

    mock_client = MagicMock()
    mock_client.list_files.side_effect = DriveClientError("Drive API down")

    with patch.object(service, "_build_drive_client", return_value=mock_client):
        with pytest.raises(DriveClientError, match="Drive API down"):
            await service.sync_metadata()

    mock_db.commit.assert_awaited()
    added_job = mock_db.add.call_args_list[0][0][0]
    assert isinstance(added_job, IndexingJob)
    assert added_job.status == IndexingJobStatus.FAILED
    assert added_job.error == "Drive API down"


@pytest.mark.asyncio
async def test_is_connected_false_when_no_token(service: DriveSyncService, mock_db: AsyncMock) -> None:
    mock_db.scalar = AsyncMock(return_value=None)
    assert await service.is_connected() is False


@pytest.mark.asyncio
async def test_is_connected_true_when_token_exists(
    service: DriveSyncService,
    mock_db: AsyncMock,
) -> None:
    mock_db.scalar = AsyncMock(side_effect=[TOKEN_ROW, TOKEN_ROW])
    mock_db.get = AsyncMock(return_value=USER)
    assert await service.is_connected() is True
