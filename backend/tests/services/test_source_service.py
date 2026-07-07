"""Tests for citation source lookup service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.services.source_service import SourceService

CHUNK_ID = uuid.uuid4()
DOCUMENT_ID = uuid.uuid4()
DRIVE_FILE_ID = uuid.uuid4()


def _chunk_bundle() -> Chunk:
    drive_file = DriveFile(
        id=DRIVE_FILE_ID,
        user_id=uuid.uuid4(),
        drive_file_id="gdrive-file-1",
        name="notes.txt",
        mime_type="text/plain",
        modified_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    document = Document(
        id=DOCUMENT_ID,
        drive_file_id=DRIVE_FILE_ID,
        extracted_text="hello world",
        extracted_text_hash="hash-1",
        page_count=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    document.drive_file = drive_file
    chunk = Chunk(
        id=CHUNK_ID,
        document_id=DOCUMENT_ID,
        chunk_index=0,
        text="Tensile strength is a material property.",
        metadata_json={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    chunk.document = document
    return chunk


@pytest.fixture
def mock_db() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def service(mock_db: AsyncMock) -> SourceService:
    return SourceService(db=mock_db)


@pytest.mark.asyncio
async def test_get_source_chunk_returns_metadata_and_text(
    service: SourceService,
    mock_db: AsyncMock,
) -> None:
    mock_db.scalar = AsyncMock(return_value=_chunk_bundle())

    source = await service.get_source_chunk(CHUNK_ID)

    assert source is not None
    assert source.chunk_id == CHUNK_ID
    assert source.drive_file_id == DRIVE_FILE_ID
    assert source.filename == "notes.txt"
    assert source.mime_type == "text/plain"
    assert source.chunk_index == 0
    assert "Tensile strength" in source.text


@pytest.mark.asyncio
async def test_get_source_chunk_returns_none_when_missing(
    service: SourceService,
    mock_db: AsyncMock,
) -> None:
    mock_db.scalar = AsyncMock(return_value=None)

    source = await service.get_source_chunk(CHUNK_ID)

    assert source is None
