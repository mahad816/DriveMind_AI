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


# ── Filename signal detection ──────────────────────────────────────────────────

@pytest.mark.parametrize(
    "question",
    [
        "What is in Resume_2024.pdf?",
        "Summarize notes.docx",
        "Read report.txt",
        "open CoreChain_AI.pdf",
        "what does internship_report.pdf say",
    ],
)
def test_has_filename_signal_detects_file_extensions(question: str) -> None:
    assert KeywordRetriever._has_filename_signal(question) is True


@pytest.mark.parametrize(
    "question",
    [
        "What is tensile strength?",
        "Find my latest resume",
        "Summarize my documents",
        "Tell me about CoreChain",
    ],
)
def test_has_filename_signal_false_for_non_file_queries(question: str) -> None:
    assert KeywordRetriever._has_filename_signal(question) is False


@pytest.mark.asyncio
async def test_retrieve_merges_filename_only_hits_when_fts_empty(
    mock_db: AsyncMock,
    settings: Settings,
) -> None:
    """Chunks from a named file must be included even when FTS finds nothing."""
    retriever = KeywordRetriever(db=mock_db, settings=settings)

    fn_chunk_id = uuid.uuid4()

    # FTS search returns nothing (search_vector mismatch for filename query)
    mock_db.execute = AsyncMock(
        side_effect=[
            [],                              # FTS hits → empty
            [(fn_chunk_id,)],                # filename-only hits → one result
        ]
    )
    mock_db.scalars = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=[_chunk()])),
    )

    await retriever.retrieve("What is in Resume_2024.pdf?")

    # Should have called execute twice: once for FTS, once for filename-only
    assert mock_db.execute.await_count == 2


@pytest.mark.asyncio
async def test_retrieve_filename_only_not_triggered_without_extension(
    mock_db: AsyncMock,
    settings: Settings,
) -> None:
    """Filename-only path should NOT run when query has no file extension."""
    retriever = KeywordRetriever(db=mock_db, settings=settings)

    mock_db.execute = AsyncMock(return_value=[])

    await retriever.retrieve("What is tensile strength?")

    # Only one db.execute call (FTS), no filename-only path
    assert mock_db.execute.await_count == 1


@pytest.mark.asyncio
async def test_fts_score_kept_when_higher_than_filename_score(
    mock_db: AsyncMock,
    settings: Settings,
) -> None:
    """When a chunk appears in both FTS and filename-only, the higher score wins."""
    retriever = KeywordRetriever(db=mock_db, settings=settings)
    high_fts_score = 0.85

    # Use the module-level CHUNK_ID so _load_chunks finds the right chunk object.
    mock_db.execute = AsyncMock(
        side_effect=[
            [(CHUNK_ID, high_fts_score)],   # FTS hits with high score
            [(CHUNK_ID,)],                  # filename-only same chunk (lower fixed score)
        ]
    )
    mock_db.scalars = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=[_chunk()])),
    )

    results = await retriever.retrieve("what is in notes.txt?")

    assert len(results) == 1
    assert results[0].score == high_fts_score  # FTS score preserved, not overwritten
