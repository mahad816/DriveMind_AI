"""Tests for metadata-based retrieval."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import Settings
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.retrieval.metadata import MetadataRetriever

USER_ID = uuid.uuid4()
DOC_A_ID = uuid.uuid4()
DOC_B_ID = uuid.uuid4()
FILE_A_ID = uuid.uuid4()
FILE_B_ID = uuid.uuid4()
CHUNK_A_ID = uuid.uuid4()
CHUNK_B_ID = uuid.uuid4()


def _drive_file(
    *,
    file_id: uuid.UUID,
    name: str,
    mime_type: str,
    modified_at: datetime,
    folder_path: str | None = None,
) -> DriveFile:
    return DriveFile(
        id=file_id,
        user_id=USER_ID,
        drive_file_id=str(file_id),
        name=name,
        mime_type=mime_type,
        folder_path=folder_path,
        modified_at=modified_at,
        created_at=modified_at,
        updated_at=modified_at,
    )


def _chunk(
    *,
    chunk_id: uuid.UUID,
    document_id: uuid.UUID,
    drive_file: DriveFile,
    text: str,
) -> Chunk:
    document = Document(
        id=document_id,
        drive_file_id=drive_file.id,
        extracted_text=text,
        extracted_text_hash="hash",
        page_count=None,
        created_at=drive_file.modified_at,
        updated_at=drive_file.modified_at,
    )
    document.drive_file = drive_file
    chunk = Chunk(
        id=chunk_id,
        document_id=document_id,
        chunk_index=0,
        text=text,
        metadata_json={"extracted_text_hash": "hash"},
        created_at=drive_file.modified_at,
        updated_at=drive_file.modified_at,
    )
    chunk.document = document
    return chunk


@pytest.fixture
def settings() -> Settings:
    return Settings(retrieval_candidate_k=4)


@pytest.fixture
def mock_db() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def retriever(mock_db: AsyncMock, settings: Settings) -> MetadataRetriever:
    return MetadataRetriever(db=mock_db, settings=settings)


@pytest.mark.asyncio
async def test_retrieve_returns_empty_without_metadata_signals(
    retriever: MetadataRetriever,
) -> None:
    results = await retriever.retrieve("what is tensile strength")
    assert results == []


@pytest.mark.asyncio
async def test_retrieve_scores_latest_files_higher(
    retriever: MetadataRetriever,
    mock_db: AsyncMock,
) -> None:
    now = datetime.now(UTC)
    newer_file = _drive_file(
        file_id=FILE_A_ID,
        name="materials_latest.pdf",
        mime_type="application/pdf",
        modified_at=now,
        folder_path="/Course",
    )
    older_file = _drive_file(
        file_id=FILE_B_ID,
        name="materials_old.pdf",
        mime_type="application/pdf",
        modified_at=now - timedelta(days=2),
        folder_path="/Course",
    )
    chunk_new = _chunk(
        chunk_id=CHUNK_A_ID,
        document_id=DOC_A_ID,
        drive_file=newer_file,
        text="new file chunk",
    )
    chunk_old = _chunk(
        chunk_id=CHUNK_B_ID,
        document_id=DOC_B_ID,
        drive_file=older_file,
        text="old file chunk",
    )
    mock_db.scalars = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=[chunk_new, chunk_old])),
    )

    results = await retriever.retrieve("latest pdf notes")

    assert len(results) == 2
    assert results[0].chunk_id == CHUNK_A_ID
    assert results[0].primary_source == "metadata"
    assert results[0].score >= results[1].score


@pytest.mark.asyncio
async def test_retrieve_limits_results_to_candidate_k(
    retriever: MetadataRetriever,
    mock_db: AsyncMock,
    settings: Settings,
) -> None:
    now = datetime.now(UTC)
    chunks = []
    for index in range(6):
        drive_file = _drive_file(
            file_id=uuid.uuid4(),
            name=f"latest_{index}.pdf",
            mime_type="application/pdf",
            modified_at=now - timedelta(minutes=index),
            folder_path="/Course",
        )
        chunks.append(
            _chunk(
                chunk_id=uuid.uuid4(),
                document_id=uuid.uuid4(),
                drive_file=drive_file,
                text=f"chunk {index}",
            )
        )
    mock_db.scalars = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=chunks)),
    )

    results = await retriever.retrieve("latest pdf")

    assert len(results) == settings.retrieval_candidate_k


def test_parse_query_extracts_mime_and_latest_signals() -> None:
    spec = MetadataRetriever._parse_query('latest pdf from "materials" folder')

    assert spec.latest_first is True
    assert "application/pdf" in spec.mime_filters
    assert "materials" in spec.filename_terms
