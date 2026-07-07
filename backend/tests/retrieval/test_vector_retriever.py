"""Tests for vector similarity retrieval."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import Settings
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.embeddings.vector_store import ScoredChunkHit
from app.retrieval.vector import VectorRetriever

CHUNK_ID = uuid.uuid4()
DOCUMENT_ID = uuid.uuid4()
DRIVE_FILE_ID = uuid.uuid4()
USER_ID = uuid.uuid4()


def _drive_file() -> DriveFile:
    return DriveFile(
        id=DRIVE_FILE_ID,
        user_id=USER_ID,
        drive_file_id="gdrive-file-1",
        name="notes.txt",
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
        text="hello world chunk",
        metadata_json={"extracted_text_hash": "hash-1"},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    chunk.document = _document()
    return chunk


@pytest.fixture
def settings() -> Settings:
    return Settings(
        retrieval_top_k=5,
        retrieval_score_threshold=0.35,
    )


@pytest.fixture
def mock_db() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_embedding() -> AsyncMock:
    embedding = AsyncMock()
    embedding.embedding_dimension = 1536
    embedding.embed_texts = AsyncMock(return_value=[[0.1] * 1536])
    return embedding


@pytest.fixture
def mock_vector_store() -> AsyncMock:
    vector_store = AsyncMock()
    vector_store.search_similar = AsyncMock(
        return_value=[ScoredChunkHit(chunk_id=CHUNK_ID, score=0.91)],
    )
    return vector_store


@pytest.fixture
def retriever(
    mock_db: AsyncMock,
    settings: Settings,
    mock_embedding: AsyncMock,
    mock_vector_store: AsyncMock,
) -> VectorRetriever:
    return VectorRetriever(
        db=mock_db,
        settings=settings,
        embedding_service=mock_embedding,
        vector_store=mock_vector_store,
    )


@pytest.mark.asyncio
async def test_retrieve_returns_hydrated_chunks(
    retriever: VectorRetriever,
    mock_db: AsyncMock,
    mock_embedding: AsyncMock,
    mock_vector_store: AsyncMock,
) -> None:
    chunk = _chunk()
    mock_db.scalars = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=[chunk])),
    )

    results = await retriever.retrieve("What is in my notes?")

    assert len(results) == 1
    assert results[0].chunk_id == CHUNK_ID
    assert results[0].filename == "notes.txt"
    assert results[0].text == "hello world chunk"
    assert results[0].score == 0.91
    mock_embedding.embed_texts.assert_awaited_once_with(["What is in my notes?"])
    mock_vector_store.search_similar.assert_awaited_once()


@pytest.mark.asyncio
async def test_retrieve_returns_empty_for_blank_question(
    retriever: VectorRetriever,
    mock_embedding: AsyncMock,
    mock_vector_store: AsyncMock,
) -> None:
    results = await retriever.retrieve("   ")

    assert results == []
    mock_embedding.embed_texts.assert_not_awaited()
    mock_vector_store.search_similar.assert_not_awaited()


@pytest.mark.asyncio
async def test_retrieve_drops_orphan_qdrant_hits(
    retriever: VectorRetriever,
    mock_db: AsyncMock,
    mock_vector_store: AsyncMock,
) -> None:
    orphan_id = uuid.uuid4()
    mock_vector_store.search_similar = AsyncMock(
        return_value=[
            ScoredChunkHit(chunk_id=CHUNK_ID, score=0.91),
            ScoredChunkHit(chunk_id=orphan_id, score=0.88),
        ],
    )
    mock_db.scalars = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=[_chunk()])),
    )

    results = await retriever.retrieve("orphan test")

    assert len(results) == 1
    assert results[0].chunk_id == CHUNK_ID


@pytest.mark.asyncio
async def test_retrieve_preserves_qdrant_rank_order(
    retriever: VectorRetriever,
    mock_db: AsyncMock,
    mock_vector_store: AsyncMock,
) -> None:
    first_id = uuid.uuid4()
    second_id = uuid.uuid4()
    first_chunk = _chunk()
    first_chunk.id = first_id
    second_chunk = _chunk()
    second_chunk.id = second_id
    second_chunk.chunk_index = 1
    second_chunk.text = "second chunk"

    mock_vector_store.search_similar = AsyncMock(
        return_value=[
            ScoredChunkHit(chunk_id=first_id, score=0.95),
            ScoredChunkHit(chunk_id=second_id, score=0.80),
        ],
    )
    mock_db.scalars = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=[first_chunk, second_chunk])),
    )

    results = await retriever.retrieve("ordered results")

    assert [result.chunk_id for result in results] == [first_id, second_id]
    assert results[0].score == 0.95
    assert results[1].score == 0.80


@pytest.mark.asyncio
async def test_retrieve_passes_retrieval_settings_to_vector_store(
    retriever: VectorRetriever,
    mock_db: AsyncMock,
    mock_vector_store: AsyncMock,
) -> None:
    mock_db.scalars = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=[_chunk()])),
    )

    await retriever.retrieve("settings test")

    call_kwargs = mock_vector_store.search_similar.await_args.kwargs
    assert call_kwargs["limit"] == 5
    assert call_kwargs["score_threshold"] == 0.35
    assert call_kwargs["expected_vector_size"] == 1536
