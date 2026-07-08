"""Tests for keyword full-text retrieval."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import Settings
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.retrieval.keyword import KeywordRetriever

CHUNK_ID = uuid.uuid4()
DOCUMENT_ID = uuid.uuid4()
DRIVE_FILE_ID = uuid.uuid4()
USER_ID = uuid.uuid4()


def _drive_file() -> DriveFile:
    return DriveFile(
        id=DRIVE_FILE_ID,
        user_id=USER_ID,
        drive_file_id="gdrive-file-1",
        name="materials_notes.txt",
        mime_type="text/plain",
        modified_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _document() -> Document:
    document = Document(
        id=DOCUMENT_ID,
        drive_file_id=DRIVE_FILE_ID,
        extracted_text="hello world",
        extracted_text_hash="hash-1",
        page_count=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    document.drive_file = _drive_file()
    return document


def _chunk() -> Chunk:
    chunk = Chunk(
        id=CHUNK_ID,
        document_id=DOCUMENT_ID,
        chunk_index=0,
        text="keyword hit chunk",
        metadata_json={"extracted_text_hash": "hash-1"},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    chunk.document = _document()
    return chunk


@pytest.fixture
def settings() -> Settings:
    return Settings(retrieval_candidate_k=17)


@pytest.fixture
def mock_db() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def retriever(mock_db: AsyncMock, settings: Settings) -> KeywordRetriever:
    return KeywordRetriever(db=mock_db, settings=settings)


@pytest.mark.asyncio
async def test_retrieve_returns_empty_for_blank_question(retriever: KeywordRetriever) -> None:
    results = await retriever.retrieve("   ")
    assert results == []


@pytest.mark.asyncio
async def test_retrieve_returns_keyword_scored_chunks(
    retriever: KeywordRetriever,
    mock_db: AsyncMock,
) -> None:
    mock_db.execute = AsyncMock(return_value=[(CHUNK_ID, 0.77)])
    mock_db.scalars = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=[_chunk()])),
    )

    results = await retriever.retrieve("materials tensile")

    assert len(results) == 1
    assert results[0].chunk_id == CHUNK_ID
    assert results[0].score == 0.77
    assert results[0].primary_source == "keyword"
    assert results[0].source_scores == {"keyword": 0.77}


@pytest.mark.asyncio
async def test_retrieve_drops_missing_chunks_from_hydration(
    retriever: KeywordRetriever,
    mock_db: AsyncMock,
) -> None:
    missing_id = uuid.uuid4()
    mock_db.execute = AsyncMock(return_value=[(CHUNK_ID, 0.77), (missing_id, 0.22)])
    mock_db.scalars = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=[_chunk()])),
    )

    results = await retriever.retrieve("materials tensile")

    assert len(results) == 1
    assert results[0].chunk_id == CHUNK_ID


@pytest.mark.asyncio
async def test_search_hits_uses_candidate_k_limit(
    retriever: KeywordRetriever,
    mock_db: AsyncMock,
) -> None:
    mock_db.execute = AsyncMock(return_value=[])

    await retriever._search_hits("materials science")

    statement = mock_db.execute.await_args.args[0]
    assert statement._limit_clause.value == 17


def test_query_terms_normalize_and_deduplicate() -> None:
    assert KeywordRetriever._query_terms("  Tensile, tensile strength!!  ") == [
        "tensile",
        "strength",
    ]
