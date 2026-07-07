"""Mocked tests for Drive file content service (Phase 3 Milestone 5)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.connectors.google_drive.client import DriveClientError
from app.connectors.google_drive.constants import GOOGLE_DOC_MIME, PDF_MIME
from app.db.enums import DriveFileStatus
from app.db.models.drive_file import DriveFile
from app.db.models.google_oauth_token import GoogleOAuthToken
from app.db.models.user import User
from app.services.drive_content_service import DriveContentService

USER_ID = uuid.uuid4()
FILE_ID = uuid.uuid4()
TOKEN_ROW = GoogleOAuthToken(
    id=uuid.uuid4(),
    user_id=USER_ID,
    access_token="access",
    refresh_token="refresh",
    token_expiry=datetime.now(UTC),
    scopes="https://www.googleapis.com/auth/drive.readonly",
)
USER = User(id=USER_ID, email="user@example.com", google_id="gid-1")
DRIVE_FILE = DriveFile(
    id=FILE_ID,
    user_id=USER_ID,
    drive_file_id="gdrive-file-1",
    name="resume.pdf",
    mime_type=PDF_MIME,
    modified_at=datetime.now(UTC),
    status=DriveFileStatus.DISCOVERED,
)


@pytest.fixture
def mock_db() -> AsyncMock:
    db = AsyncMock()
    db.commit = AsyncMock()
    return db


@pytest.fixture
def service(mock_db: AsyncMock) -> DriveContentService:
    return DriveContentService(db=mock_db, settings=MagicMock())


@pytest.mark.asyncio
async def test_fetch_file_content_returns_bytes(service: DriveContentService, mock_db: AsyncMock) -> None:
    mock_db.scalar = AsyncMock(side_effect=[TOKEN_ROW, DRIVE_FILE, TOKEN_ROW])
    mock_db.get = AsyncMock(return_value=USER)

    mock_client = MagicMock()
    mock_client.get_file_content.return_value = b"%PDF-1.4"

    with patch.object(service, "_build_drive_client", return_value=mock_client):
        result = await service.fetch_file_content(file_id=FILE_ID)

    assert result.data == b"%PDF-1.4"
    assert result.mime_type == PDF_MIME
    assert result.filename == "resume.pdf"
    assert result.drive_file_id == "gdrive-file-1"
    mock_client.get_file_content.assert_called_once_with("gdrive-file-1", PDF_MIME)
    mock_db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_fetch_file_content_exports_google_doc(
    service: DriveContentService,
    mock_db: AsyncMock,
) -> None:
    google_doc = DriveFile(
        id=FILE_ID,
        user_id=USER_ID,
        drive_file_id="gdrive-doc",
        name="Notes",
        mime_type=GOOGLE_DOC_MIME,
        modified_at=datetime.now(UTC),
        status=DriveFileStatus.DISCOVERED,
    )
    mock_db.scalar = AsyncMock(side_effect=[TOKEN_ROW, google_doc, TOKEN_ROW])
    mock_db.get = AsyncMock(return_value=USER)

    mock_client = MagicMock()
    mock_client.get_file_content.return_value = b"Hello from doc"

    with patch.object(service, "_build_drive_client", return_value=mock_client):
        result = await service.fetch_file_content(file_id=FILE_ID)

    assert result.mime_type == "text/plain"
    assert result.data == b"Hello from doc"


@pytest.mark.asyncio
async def test_fetch_file_content_not_found(service: DriveContentService, mock_db: AsyncMock) -> None:
    mock_db.scalar = AsyncMock(side_effect=[TOKEN_ROW, None])
    mock_db.get = AsyncMock(return_value=USER)

    with pytest.raises(ValueError, match="Synced file not found"):
        await service.fetch_file_content(file_id=FILE_ID)


@pytest.mark.asyncio
async def test_fetch_file_content_no_oauth_connection(
    service: DriveContentService,
    mock_db: AsyncMock,
) -> None:
    mock_db.scalar = AsyncMock(return_value=None)

    with pytest.raises(ValueError, match="No Google Drive connection"):
        await service.fetch_file_content(file_id=FILE_ID)


@pytest.mark.asyncio
async def test_fetch_file_content_propagates_drive_error(
    service: DriveContentService,
    mock_db: AsyncMock,
) -> None:
    mock_db.scalar = AsyncMock(side_effect=[TOKEN_ROW, DRIVE_FILE, TOKEN_ROW])
    mock_db.get = AsyncMock(return_value=USER)

    mock_client = MagicMock()
    mock_client.get_file_content.side_effect = DriveClientError("Drive file download failed")

    with patch.object(service, "_build_drive_client", return_value=mock_client):
        with pytest.raises(DriveClientError, match="download failed"):
            await service.fetch_file_content(file_id=FILE_ID)
