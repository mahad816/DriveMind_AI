"""Tests for direct retrieval of explicitly named files."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.enums import DriveFileStatus
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.db.models.user import User
from app.retrieval.file_target import FileTargetRetriever

USER_ID = uuid.uuid4()
DRIVE_FILE_ID = uuid.uuid4()
DOCUMENT_ID = uuid.uuid4()
CHUNK_ID = uuid.uuid4()


def _drive_file(status: DriveFileStatus) -> DriveFile:
    return DriveFile(
        id=DRIVE_FILE_ID,
        user_id=USER_ID,
        drive_file_id="gdrive-notes",
        name="notes.txt",
        mime_type="text/plain",
        modified_at=datetime.now(UTC),
        status=status,
    )


def _chunk(drive_file: DriveFile) -> Chunk:
    document = Document(
        id=DOCUMENT_ID,
        drive_file_id=drive_file.id,
        extracted_text="indexed notes",
        extracted_text_hash="hash-1",
    )
    document.drive_file = drive_file
    chunk = Chunk(
        id=CHUNK_ID,
        document_id=document.id,
        chunk_index=0,
        text="indexed notes",
        metadata_json={"extracted_text_hash": "hash-1"},
    )
    chunk.document = document
    return chunk


@pytest.fixture
def mock_db() -> AsyncMock:
    db = AsyncMock()
    db.get = AsyncMock(
        return_value=User(
            id=USER_ID,
            email="user@example.com",
            google_id="google-user-1",
        )
    )
    return db


@pytest.mark.asyncio
async def test_search_excludes_skipped_named_file(mock_db: AsyncMock) -> None:
    mock_db.scalar = AsyncMock(return_value=_drive_file(DriveFileStatus.SKIPPED))
    retriever = FileTargetRetriever(mock_db)

    result = await retriever.search('Tell me about "notes.txt"', user_id=USER_ID)

    assert result.files == []
    assert result.chunks == []
    assert result.targets == ["notes.txt", "notes"]
    mock_db.scalars.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_preserves_not_indexed_result_for_active_file(mock_db: AsyncMock) -> None:
    drive_file = _drive_file(DriveFileStatus.DISCOVERED)
    mock_db.scalar = AsyncMock(return_value=drive_file)
    retriever = FileTargetRetriever(mock_db)

    result = await retriever.search('Tell me about "notes.txt"', user_id=USER_ID)

    assert result.files == [drive_file]
    assert result.chunks == []
    assert result.not_indexed is True
    mock_db.scalars.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_returns_chunks_for_indexed_file(mock_db: AsyncMock) -> None:
    drive_file = _drive_file(DriveFileStatus.INDEXED)
    mock_db.scalar = AsyncMock(return_value=drive_file)
    mock_db.scalars = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=[_chunk(drive_file)]))
    )
    retriever = FileTargetRetriever(mock_db)

    result = await retriever.search('Tell me about "notes.txt"', user_id=USER_ID)

    assert result.files == [drive_file]
    assert len(result.chunks) == 1
    assert result.chunks[0].chunk_id == CHUNK_ID
    assert result.found is True
