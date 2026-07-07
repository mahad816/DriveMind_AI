"""Tests for document chunking service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.enums import DriveFileStatus
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.db.models.google_oauth_token import GoogleOAuthToken
from app.db.models.indexing_job import IndexingJob
from app.db.models.user import User
from app.ingestion.hash_util import compute_extracted_text_hash
from app.services.chunking_service import ChunkingService

USER_ID = uuid.uuid4()
FILE_ID = uuid.uuid4()
DOCUMENT_ID = uuid.uuid4()
USER = User(id=USER_ID, email="user@example.com", google_id="gid-1")
TOKEN_ROW = GoogleOAuthToken(
    id=uuid.uuid4(),
    user_id=USER_ID,
    access_token="access",
    refresh_token="refresh",
    token_expiry=datetime.now(UTC),
    scopes="https://www.googleapis.com/auth/drive.readonly",
)


def _drive_file() -> DriveFile:
    return DriveFile(
        id=FILE_ID,
        user_id=USER_ID,
        drive_file_id="gdrive-file-1",
        name="notes.txt",
        mime_type="text/plain",
        modified_at=datetime.now(UTC),
        status=DriveFileStatus.INDEXED,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _document(*, text: str = "hello world") -> Document:
    return Document(
        id=DOCUMENT_ID,
        drive_file_id=FILE_ID,
        extracted_text=text,
        extracted_text_hash=compute_extracted_text_hash(text),
        page_count=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _existing_chunk(*, text: str, text_hash: str, chunk_index: int = 0) -> Chunk:
    return Chunk(
        id=uuid.uuid4(),
        document_id=DOCUMENT_ID,
        chunk_index=chunk_index,
        text=text,
        metadata_json={
            "char_start": 0,
            "char_end": len(text),
            "char_length": len(text),
            "extracted_text_hash": text_hash,
        },
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.fixture
def mock_db() -> AsyncMock:
    db = AsyncMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.execute = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.fixture
def service(mock_db: AsyncMock) -> ChunkingService:
    return ChunkingService(db=mock_db, settings=MagicMock())


@pytest.mark.asyncio
async def test_chunk_documents_creates_chunks_for_new_document(
    service: ChunkingService,
    mock_db: AsyncMock,
) -> None:
    drive_file = _drive_file()
    document = _document()
    mock_db.get = AsyncMock(return_value=USER)
    mock_db.scalar = AsyncMock(side_effect=[TOKEN_ROW, drive_file, document])
    mock_db.scalars = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=[])),
    )

    result = await service.chunk_documents(file_id=FILE_ID)

    assert result.chunked == 1
    assert result.unchanged == 0
    assert result.skipped == 0
    assert result.total == 1
    mock_db.execute.assert_awaited_once()
    added = [call.args[0] for call in mock_db.add.call_args_list]
    assert any(isinstance(item, Chunk) for item in added)
    assert any(isinstance(item, IndexingJob) for item in added)
    chunk_rows = [item for item in added if isinstance(item, Chunk)]
    assert len(chunk_rows) == 1
    assert chunk_rows[0].text == "hello world"
    assert chunk_rows[0].metadata_json["extracted_text_hash"] == document.extracted_text_hash


@pytest.mark.asyncio
async def test_chunk_documents_skips_when_hash_unchanged(
    service: ChunkingService,
    mock_db: AsyncMock,
) -> None:
    drive_file = _drive_file()
    document = _document()
    existing = [_existing_chunk(text="hello world", text_hash=document.extracted_text_hash)]
    mock_db.get = AsyncMock(return_value=USER)
    mock_db.scalar = AsyncMock(side_effect=[TOKEN_ROW, drive_file, document])
    mock_db.scalars = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=existing)),
    )

    result = await service.chunk_documents(file_id=FILE_ID)

    assert result.chunked == 0
    assert result.unchanged == 1
    assert result.skipped == 0
    mock_db.execute.assert_not_awaited()
    added = [call.args[0] for call in mock_db.add.call_args_list]
    assert not any(isinstance(item, Chunk) for item in added)


@pytest.mark.asyncio
async def test_chunk_documents_rechunks_when_text_hash_changes(
    service: ChunkingService,
    mock_db: AsyncMock,
) -> None:
    drive_file = _drive_file()
    document = _document(text="updated text for chunking")
    old_hash = compute_extracted_text_hash("stale text")
    existing = [_existing_chunk(text="stale text", text_hash=old_hash)]
    mock_db.get = AsyncMock(return_value=USER)
    mock_db.scalar = AsyncMock(side_effect=[TOKEN_ROW, drive_file, document])
    mock_db.scalars = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=existing)),
    )

    result = await service.chunk_documents(file_id=FILE_ID)

    assert result.chunked == 1
    assert result.unchanged == 0
    mock_db.execute.assert_awaited_once()
    added = [call.args[0] for call in mock_db.add.call_args_list]
    chunk_rows = [item for item in added if isinstance(item, Chunk)]
    assert len(chunk_rows) == 1
    assert chunk_rows[0].text == "updated text for chunking"


@pytest.mark.asyncio
async def test_chunk_documents_skips_file_without_document(
    service: ChunkingService,
    mock_db: AsyncMock,
) -> None:
    drive_file = _drive_file()
    mock_db.get = AsyncMock(return_value=USER)
    mock_db.scalar = AsyncMock(side_effect=[TOKEN_ROW, drive_file, None])

    result = await service.chunk_documents(file_id=FILE_ID)

    assert result.chunked == 0
    assert result.unchanged == 0
    assert result.skipped == 1
    mock_db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_chunk_documents_empty_text_without_existing_chunks_is_unchanged(
    service: ChunkingService,
    mock_db: AsyncMock,
) -> None:
    drive_file = _drive_file()
    document = _document(text="")
    mock_db.get = AsyncMock(return_value=USER)
    mock_db.scalar = AsyncMock(side_effect=[TOKEN_ROW, drive_file, document])
    mock_db.scalars = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=[])),
    )

    result = await service.chunk_documents(file_id=FILE_ID)

    assert result.unchanged == 1
    assert result.chunked == 0
    mock_db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_chunk_documents_empty_text_removes_stale_chunks(
    service: ChunkingService,
    mock_db: AsyncMock,
) -> None:
    drive_file = _drive_file()
    document = _document(text="")
    old_hash = compute_extracted_text_hash("previous content")
    existing = [_existing_chunk(text="previous content", text_hash=old_hash)]
    mock_db.get = AsyncMock(return_value=USER)
    mock_db.scalar = AsyncMock(side_effect=[TOKEN_ROW, drive_file, document])
    mock_db.scalars = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=existing)),
    )

    result = await service.chunk_documents(file_id=FILE_ID)

    assert result.chunked == 1
    assert result.unchanged == 0
    mock_db.execute.assert_awaited_once()
    added = [call.args[0] for call in mock_db.add.call_args_list]
    assert not any(isinstance(item, Chunk) for item in added)


@pytest.mark.asyncio
async def test_chunk_documents_batch_processes_all_documents(
    service: ChunkingService,
    mock_db: AsyncMock,
) -> None:
    documents = [_document(text="doc one"), _document(text="doc two")]
    mock_db.get = AsyncMock(return_value=USER)
    mock_db.scalar = AsyncMock(return_value=TOKEN_ROW)
    mock_db.scalars = AsyncMock(
        side_effect=[
            MagicMock(all=MagicMock(return_value=documents)),
            MagicMock(all=MagicMock(return_value=[])),
            MagicMock(all=MagicMock(return_value=[])),
        ],
    )

    result = await service.chunk_documents()

    assert result.total == 2
    assert result.chunked == 2
    assert result.unchanged == 0
    assert mock_db.execute.await_count == 2


@pytest.mark.asyncio
async def test_chunk_documents_raises_when_no_oauth_connection(
    service: ChunkingService,
    mock_db: AsyncMock,
) -> None:
    mock_db.scalar = AsyncMock(return_value=None)

    with pytest.raises(ValueError, match="No Google Drive connection"):
        await service.chunk_documents()
