"""Tests for document ingestion service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.connectors.google_drive.constants import PDF_MIME, TXT_MIME
from app.db.enums import DriveFileStatus
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.db.models.google_oauth_token import GoogleOAuthToken
from app.db.models.indexing_job import IndexingJob
from app.db.models.user import User
from app.ingestion.extractors.base import ExtractionResult
from app.ingestion.hash_util import compute_extracted_text_hash
from app.services.drive_content_service import DriveFileContent
from app.services.ingestion_service import IngestionService

USER_ID = uuid.uuid4()
FILE_ID = uuid.uuid4()
USER = User(id=USER_ID, email="user@example.com", google_id="gid-1")
TOKEN_ROW = GoogleOAuthToken(
    id=uuid.uuid4(),
    user_id=USER_ID,
    access_token="access",
    refresh_token="refresh",
    token_expiry=datetime.now(UTC),
    scopes="https://www.googleapis.com/auth/drive.readonly",
)


def _drive_file(
    *,
    file_id: uuid.UUID = FILE_ID,
    mime_type: str = TXT_MIME,
    status: DriveFileStatus = DriveFileStatus.DISCOVERED,
) -> DriveFile:
    return DriveFile(
        id=file_id,
        user_id=USER_ID,
        drive_file_id="gdrive-file-1",
        name="notes.txt",
        mime_type=mime_type,
        modified_at=datetime.now(UTC),
        status=status,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.fixture
def mock_db() -> AsyncMock:
    db = AsyncMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.fixture
def mock_content_service() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def service(mock_db: AsyncMock, mock_content_service: AsyncMock) -> IngestionService:
    return IngestionService(db=mock_db, settings=MagicMock(), content_service=mock_content_service)


@pytest.mark.asyncio
async def test_ingest_files_creates_document_for_new_file(
    service: IngestionService,
    mock_db: AsyncMock,
    mock_content_service: AsyncMock,
) -> None:
    drive_file = _drive_file()
    mock_db.get = AsyncMock(return_value=USER)
    mock_db.scalar = AsyncMock(side_effect=[TOKEN_ROW, drive_file, None])
    mock_content_service.fetch_file_content = AsyncMock(
        return_value=DriveFileContent(
            data=b"hello world",
            mime_type=TXT_MIME,
            filename="notes.txt",
            drive_file_id="gdrive-file-1",
        )
    )

    with patch(
        "app.services.ingestion_service.get_extractor",
    ) as mock_get_extractor:
        mock_get_extractor.return_value.extract.return_value = ExtractionResult(text="hello world")

        result = await service.ingest_files(file_id=FILE_ID)

    assert result.ingested == 1
    assert result.unchanged == 0
    assert result.failed == 0
    assert result.total == 1
    assert drive_file.status == DriveFileStatus.INDEXED
    assert drive_file.indexed_at is not None
    added = [call.args[0] for call in mock_db.add.call_args_list]
    assert any(isinstance(item, Document) for item in added)
    assert any(isinstance(item, IndexingJob) for item in added)


@pytest.mark.asyncio
async def test_ingest_files_skips_when_text_hash_unchanged(
    service: IngestionService,
    mock_db: AsyncMock,
    mock_content_service: AsyncMock,
) -> None:
    drive_file = _drive_file()
    existing = Document(
        id=uuid.uuid4(),
        drive_file_id=FILE_ID,
        extracted_text="hello world",
        extracted_text_hash=compute_extracted_text_hash("hello world"),
        page_count=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    mock_db.get = AsyncMock(return_value=USER)
    mock_db.scalar = AsyncMock(side_effect=[TOKEN_ROW, drive_file, existing])
    mock_content_service.fetch_file_content = AsyncMock(
        return_value=DriveFileContent(
            data=b"hello world",
            mime_type=TXT_MIME,
            filename="notes.txt",
            drive_file_id="gdrive-file-1",
        )
    )

    with patch(
        "app.services.ingestion_service.get_extractor",
    ) as mock_get_extractor:
        mock_get_extractor.return_value.extract.return_value = ExtractionResult(text="hello world")

        result = await service.ingest_files(file_id=FILE_ID)

    assert result.ingested == 0
    assert result.unchanged == 1
    assert result.failed == 0
    assert drive_file.status == DriveFileStatus.INDEXED


@pytest.mark.asyncio
async def test_ingest_files_marks_failed_on_extraction_error(
    service: IngestionService,
    mock_db: AsyncMock,
    mock_content_service: AsyncMock,
) -> None:
    drive_file = _drive_file(mime_type=PDF_MIME)
    mock_db.get = AsyncMock(return_value=USER)
    mock_db.scalar = AsyncMock(side_effect=[TOKEN_ROW, drive_file, None])
    mock_content_service.fetch_file_content = AsyncMock(
        return_value=DriveFileContent(
            data=b"%PDF",
            mime_type=PDF_MIME,
            filename="broken.pdf",
            drive_file_id="gdrive-file-1",
        )
    )

    with patch(
        "app.services.ingestion_service.get_extractor",
    ) as mock_get_extractor:
        from app.ingestion.extractors.base import ExtractionError

        mock_get_extractor.return_value.extract.side_effect = ExtractionError("bad pdf")

        result = await service.ingest_files(file_id=FILE_ID)

    assert result.failed == 1
    assert drive_file.status == DriveFileStatus.FAILED


@pytest.mark.asyncio
async def test_ingest_files_batch_processes_all_ingestible_files(
    service: IngestionService,
    mock_db: AsyncMock,
    mock_content_service: AsyncMock,
) -> None:
    files = [_drive_file(file_id=uuid.uuid4()), _drive_file(file_id=uuid.uuid4())]
    mock_db.get = AsyncMock(return_value=USER)
    mock_db.scalar = AsyncMock(side_effect=[TOKEN_ROW, None, None, None, None])
    mock_db.scalars = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=files)),
    )
    mock_content_service.fetch_file_content = AsyncMock(
        return_value=DriveFileContent(
            data=b"batch text",
            mime_type=TXT_MIME,
            filename="notes.txt",
            drive_file_id="gdrive-file-1",
        )
    )

    with patch(
        "app.services.ingestion_service.get_extractor",
    ) as mock_get_extractor:
        mock_get_extractor.return_value.extract.return_value = ExtractionResult(text="batch text")

        result = await service.ingest_files()

    assert result.total == 2
    assert result.ingested == 2
