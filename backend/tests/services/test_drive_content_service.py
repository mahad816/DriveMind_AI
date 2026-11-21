"""Mocked tests for Drive file content service (Phase 3 Milestone 5)."""

from __future__ import annotations

import uuid
from collections.abc import Generator
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.credential_fixtures import synthetic_oauth_row

from app.connectors.google_drive.client import DriveClientError
from app.connectors.google_drive.constants import DOCX_MIME, GOOGLE_DOC_MIME, PDF_MIME
from app.db.enums import DriveFileStatus
from app.db.models.drive_file import DriveFile
from app.db.models.user import User
from app.services.drive_content_service import DriveContentService

USER_ID = uuid.uuid4()
FILE_ID = uuid.uuid4()
TOKEN_ROW = synthetic_oauth_row(
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
def service(mock_db: AsyncMock) -> Generator[DriveContentService, None, None]:
    instance = DriveContentService(db=mock_db, settings=MagicMock(demo_mode=False))

    async def load(owner):
        row = await mock_db.scalar(None)
        if row is None:
            raise DriveClientError("No Google Drive connection found. Complete OAuth first.")
        return SimpleNamespace(record=row)

    # Metadata orchestration unit tests mock encrypted credential I/O. The real
    # repository/coordinator is exercised against isolated PostgreSQL separately.
    with patch.object(instance, "_load_oauth_token", side_effect=load):
        yield instance


@pytest.mark.asyncio
async def test_fetch_file_content_returns_bytes(
    service: DriveContentService, mock_db: AsyncMock
) -> None:
    mock_db.scalar = AsyncMock(side_effect=[DRIVE_FILE, TOKEN_ROW])
    mock_db.get = AsyncMock(return_value=USER)

    mock_client = MagicMock()
    mock_client.get_file_content_with_type.return_value = (b"%PDF-1.4", PDF_MIME)

    with patch.object(service, "_build_drive_client", return_value=mock_client):
        result = await service.fetch_file_content(file_id=FILE_ID, user_id=USER_ID)

    assert result.data == b"%PDF-1.4"
    assert result.mime_type == PDF_MIME
    assert result.filename == "resume.pdf"
    assert result.drive_file_id == "gdrive-file-1"
    assert result.grant_id == TOKEN_ROW.id and result.grant_epoch == TOKEN_ROW.grant_epoch
    mock_client.get_file_content_with_type.assert_called_once_with("gdrive-file-1", PDF_MIME)
    # Reads must not commit writes accumulated by the caller (managed ingestion
    # additionally supplies an independent download session).
    mock_db.commit.assert_not_awaited()


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
    mock_db.scalar = AsyncMock(side_effect=[google_doc, TOKEN_ROW])
    mock_db.get = AsyncMock(return_value=USER)

    mock_client = MagicMock()
    mock_client.get_file_content_with_type.return_value = (b"docx bytes", DOCX_MIME)

    with patch.object(service, "_build_drive_client", return_value=mock_client):
        result = await service.fetch_file_content(file_id=FILE_ID, user_id=USER_ID)

    assert result.mime_type == DOCX_MIME
    assert result.data == b"docx bytes"


@pytest.mark.asyncio
async def test_fetch_file_content_reports_the_type_that_was_really_returned(
    service: DriveContentService,
    mock_db: AsyncMock,
) -> None:
    """A big Google Doc comes back as plain text; the caller must read it as text, not DOCX."""
    google_doc = DriveFile(
        id=FILE_ID,
        user_id=USER_ID,
        drive_file_id="gdrive-doc",
        name="Big notes",
        mime_type=GOOGLE_DOC_MIME,
        modified_at=datetime.now(UTC),
        status=DriveFileStatus.DISCOVERED,
    )
    mock_db.scalar = AsyncMock(side_effect=[google_doc, TOKEN_ROW])
    mock_db.get = AsyncMock(return_value=USER)
    mock_client = MagicMock()
    mock_client.get_file_content_with_type.return_value = (b"just text", "text/plain")

    with patch.object(service, "_build_drive_client", return_value=mock_client):
        result = await service.fetch_file_content(file_id=FILE_ID, user_id=USER_ID)

    assert result.mime_type == "text/plain"


@pytest.mark.asyncio
async def test_fetch_file_content_not_found(
    service: DriveContentService, mock_db: AsyncMock
) -> None:
    mock_db.scalar = AsyncMock(side_effect=[None])
    mock_db.get = AsyncMock(return_value=USER)

    with pytest.raises(ValueError, match="Synced file not found"):
        await service.fetch_file_content(file_id=FILE_ID, user_id=USER_ID)


@pytest.mark.asyncio
async def test_fetch_file_content_no_oauth_connection(
    service: DriveContentService,
    mock_db: AsyncMock,
) -> None:
    mock_db.scalar = AsyncMock(side_effect=[DRIVE_FILE, None])
    mock_db.get = AsyncMock(return_value=USER)

    with pytest.raises(DriveClientError, match="No Google Drive connection"):
        await service.fetch_file_content(file_id=FILE_ID, user_id=USER_ID)


@pytest.mark.asyncio
async def test_fetch_file_content_propagates_drive_error(
    service: DriveContentService,
    mock_db: AsyncMock,
) -> None:
    mock_db.scalar = AsyncMock(side_effect=[DRIVE_FILE, TOKEN_ROW])
    mock_db.get = AsyncMock(return_value=USER)

    mock_client = MagicMock()
    mock_client.get_file_content_with_type.side_effect = DriveClientError(
        "Drive file download failed"
    )

    with patch.object(service, "_build_drive_client", return_value=mock_client):
        with pytest.raises(DriveClientError, match="download failed"):
            await service.fetch_file_content(file_id=FILE_ID, user_id=USER_ID)


@pytest.mark.asyncio
@pytest.mark.parametrize("owner", [None, "not-a-uuid"])
async def test_fetch_file_content_refuses_a_missing_owner_without_a_query(
    service: DriveContentService, mock_db: AsyncMock, owner: object
) -> None:
    with pytest.raises(ValueError, match="An explicit corpus owner is required"):
        await service.fetch_file_content(file_id=FILE_ID, user_id=owner)  # type: ignore[arg-type]

    for method in (mock_db.scalar, mock_db.scalars, mock_db.execute, mock_db.get):
        method.assert_not_awaited()
