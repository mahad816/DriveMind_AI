"""Tests for document ingestion service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.connectors.google_drive.constants import PDF_MIME, TXT_MIME
from app.db.enums import DriveFileStatus, IndexingJobStatus
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.db.models.google_oauth_token import GoogleOAuthToken
from app.db.models.indexing_job import IndexingJob
from app.db.models.user import User
from app.ingestion.extractors.base import ExtractionError, ExtractionResult
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


def _added_jobs(mock_db: AsyncMock) -> list[IndexingJob]:
    return [
        call.args[0] for call in mock_db.add.call_args_list if isinstance(call.args[0], IndexingJob)
    ]


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
    assert drive_file.status == DriveFileStatus.INDEXING
    assert _added_jobs(mock_db)[0].status == IndexingJobStatus.COMPLETED
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
    assert drive_file.status == DriveFileStatus.INDEXING


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
        mock_get_extractor.return_value.extract.side_effect = ExtractionError("bad pdf")

        result = await service.ingest_files(file_id=FILE_ID)

    assert result.failed == 1
    assert drive_file.status == DriveFileStatus.FAILED
    job = _added_jobs(mock_db)[0]
    assert job.status == IndexingJobStatus.FAILED
    assert job.error == "1 of 1 files failed during ingestion."


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
    assert _added_jobs(mock_db)[0].status == IndexingJobStatus.COMPLETED


@pytest.mark.asyncio
async def test_ingest_files_partial_extraction_failure_fails_job_and_preserves_success(
    service: IngestionService,
    mock_db: AsyncMock,
    mock_content_service: AsyncMock,
) -> None:
    successful = _drive_file(file_id=uuid.uuid4())
    failed = _drive_file(file_id=uuid.uuid4(), mime_type=PDF_MIME)
    mock_db.get = AsyncMock(return_value=USER)
    mock_db.scalar = AsyncMock(side_effect=[TOKEN_ROW, None, None])
    mock_db.scalars = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=[successful, failed])),
    )
    mock_content_service.fetch_file_content = AsyncMock(
        return_value=DriveFileContent(
            data=b"content",
            mime_type=TXT_MIME,
            filename="notes.txt",
            drive_file_id="gdrive-file-1",
        )
    )

    with patch("app.services.ingestion_service.get_extractor") as mock_get_extractor:
        mock_get_extractor.return_value.extract.side_effect = [
            ExtractionResult(text="searchable text"),
            ExtractionError("bad pdf"),
        ]
        result = await service.ingest_files()

    assert result.ingested == 1
    assert result.failed == 1
    assert successful.status == DriveFileStatus.INDEXING
    assert failed.status == DriveFileStatus.FAILED
    job = _added_jobs(mock_db)[0]
    assert job.status == IndexingJobStatus.FAILED
    assert job.error == "1 of 2 files failed during ingestion."


@pytest.mark.asyncio
async def test_ingest_files_all_extraction_failures_fail_job(
    service: IngestionService,
    mock_db: AsyncMock,
    mock_content_service: AsyncMock,
) -> None:
    files = [_drive_file(file_id=uuid.uuid4()), _drive_file(file_id=uuid.uuid4())]
    mock_db.get = AsyncMock(return_value=USER)
    mock_db.scalar = AsyncMock(side_effect=[TOKEN_ROW, None, None])
    mock_db.scalars = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=files)),
    )
    mock_content_service.fetch_file_content = AsyncMock(
        return_value=DriveFileContent(
            data=b"broken",
            mime_type=TXT_MIME,
            filename="notes.txt",
            drive_file_id="gdrive-file-1",
        )
    )

    with patch("app.services.ingestion_service.get_extractor") as mock_get_extractor:
        mock_get_extractor.return_value.extract.side_effect = [
            ExtractionError("first failure"),
            ExtractionError("second failure"),
        ]
        result = await service.ingest_files()

    assert result.failed == 2
    assert all(drive_file.status == DriveFileStatus.FAILED for drive_file in files)
    job = _added_jobs(mock_db)[0]
    assert job.status == IndexingJobStatus.FAILED
    assert job.error == "2 of 2 files failed during ingestion."


@pytest.mark.asyncio
@pytest.mark.parametrize("extracted_text", ["", "  \n\t  "])
async def test_ingest_files_empty_content_is_skipped_without_failing_job(
    service: IngestionService,
    mock_db: AsyncMock,
    mock_content_service: AsyncMock,
    extracted_text: str,
) -> None:
    drive_file = _drive_file(status=DriveFileStatus.INDEXING)
    mock_db.get = AsyncMock(return_value=USER)
    mock_db.scalar = AsyncMock(side_effect=[TOKEN_ROW, drive_file, None])
    mock_content_service.fetch_file_content = AsyncMock(
        return_value=DriveFileContent(
            data=b"empty",
            mime_type=TXT_MIME,
            filename="notes.txt",
            drive_file_id="gdrive-file-1",
        )
    )

    with patch("app.services.ingestion_service.get_extractor") as mock_get_extractor:
        mock_get_extractor.return_value.extract.return_value = ExtractionResult(text=extracted_text)
        result = await service.ingest_files(file_id=FILE_ID)

    assert result.skipped == 1
    assert result.failed == 0
    assert drive_file.status == DriveFileStatus.SKIPPED
    assert not any(isinstance(call.args[0], Document) for call in mock_db.add.call_args_list)
    job = _added_jobs(mock_db)[0]
    assert job.status == IndexingJobStatus.COMPLETED
    assert job.error is None


@pytest.mark.asyncio
async def test_ingest_files_can_reprocess_skipped_file_after_rediscovery(
    service: IngestionService,
    mock_db: AsyncMock,
    mock_content_service: AsyncMock,
) -> None:
    drive_file = _drive_file()
    mock_db.get = AsyncMock(return_value=USER)
    mock_db.scalar = AsyncMock(
        side_effect=[TOKEN_ROW, drive_file, None, TOKEN_ROW, drive_file, None]
    )
    mock_content_service.fetch_file_content = AsyncMock(
        return_value=DriveFileContent(
            data=b"content",
            mime_type=TXT_MIME,
            filename="notes.txt",
            drive_file_id="gdrive-file-1",
        )
    )

    with patch("app.services.ingestion_service.get_extractor") as mock_get_extractor:
        mock_get_extractor.return_value.extract.side_effect = [
            ExtractionResult(text=""),
            ExtractionResult(text="now searchable"),
        ]
        first = await service.ingest_files(file_id=FILE_ID)
        assert first.skipped == 1
        assert drive_file.status == DriveFileStatus.SKIPPED

        # Drive sync restores a modified skipped file to DISCOVERED.
        drive_file.status = DriveFileStatus.DISCOVERED
        second = await service.ingest_files(file_id=FILE_ID)

    assert second.ingested == 1
    assert second.failed == 0
    assert drive_file.status == DriveFileStatus.INDEXING
    assert len(_added_jobs(mock_db)) == 2
    assert _added_jobs(mock_db)[1].status == IndexingJobStatus.COMPLETED


@pytest.mark.asyncio
async def test_ingest_files_unexpected_exception_fails_job_with_error(
    service: IngestionService,
    mock_db: AsyncMock,
    mock_content_service: AsyncMock,
) -> None:
    drive_file = _drive_file()
    mock_db.get = AsyncMock(return_value=USER)
    mock_db.scalar = AsyncMock(side_effect=[TOKEN_ROW, drive_file, None])
    mock_content_service.fetch_file_content = AsyncMock(
        return_value=DriveFileContent(
            data=b"content",
            mime_type=TXT_MIME,
            filename="notes.txt",
            drive_file_id="gdrive-file-1",
        )
    )

    with patch("app.services.ingestion_service.get_extractor") as mock_get_extractor:
        mock_get_extractor.return_value.extract.side_effect = RuntimeError("unexpected failure")
        with pytest.raises(RuntimeError, match="unexpected failure"):
            await service.ingest_files(file_id=FILE_ID)

    job = _added_jobs(mock_db)[0]
    assert job.status == IndexingJobStatus.FAILED
    assert job.error == "unexpected failure"
