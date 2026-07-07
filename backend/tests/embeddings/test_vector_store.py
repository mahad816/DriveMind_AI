"""Tests for Qdrant vector store."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.core.config import Settings
from app.embeddings.vector_store import QdrantVectorStore, ScoredChunkHit, VectorPoint, VectorStoreError

CHUNK_ID = uuid.uuid4()
DRIVE_FILE_ID = uuid.uuid4()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        qdrant_host="localhost",
        qdrant_port=6333,
        qdrant_collection="drivemind_chunks",
    )


@pytest.fixture
def mock_client() -> AsyncMock:
    client = AsyncMock()
    client.collection_exists = AsyncMock(return_value=False)
    client.create_collection = AsyncMock()
    client.upsert = AsyncMock()
    client.delete = AsyncMock()
    client.retrieve = AsyncMock(return_value=[])
    client.scroll = AsyncMock(return_value=([], None))
    return client


@pytest.fixture
def store(settings: Settings, mock_client: AsyncMock) -> QdrantVectorStore:
    return QdrantVectorStore(settings=settings, client=mock_client)


@pytest.mark.asyncio
async def test_ensure_collection_creates_missing_collection(
    store: QdrantVectorStore,
    mock_client: AsyncMock,
) -> None:
    await store.ensure_collection(vector_size=1536)

    mock_client.collection_exists.assert_awaited_once_with("drivemind_chunks")
    mock_client.create_collection.assert_awaited_once()


@pytest.mark.asyncio
async def test_ensure_collection_skips_existing_collection(
    store: QdrantVectorStore,
    mock_client: AsyncMock,
) -> None:
    mock_client.collection_exists = AsyncMock(return_value=True)

    await store.ensure_collection(vector_size=1536)

    mock_client.create_collection.assert_not_awaited()


@pytest.mark.asyncio
async def test_upsert_points_sends_chunk_vectors(
    store: QdrantVectorStore,
    mock_client: AsyncMock,
) -> None:
    point = VectorPoint(
        chunk_id=CHUNK_ID,
        vector=[0.1, 0.2],
        payload={
            "chunk_id": str(CHUNK_ID),
            "drive_file_id": str(DRIVE_FILE_ID),
            "filename": "notes.txt",
            "mime_type": "text/plain",
            "modified_at": datetime.now(UTC),
            "chunk_index": 0,
            "extracted_text_hash": "abc123",
        },
    )

    await store.upsert_points([point])

    mock_client.upsert.assert_awaited_once()
    call_kwargs = mock_client.upsert.await_args.kwargs
    assert call_kwargs["collection_name"] == "drivemind_chunks"
    assert call_kwargs["points"][0].id == str(CHUNK_ID)


@pytest.mark.asyncio
async def test_upsert_points_batches_large_inputs(
    store: QdrantVectorStore,
    mock_client: AsyncMock,
) -> None:
    store.upsert_batch_size = 2
    points = [
        VectorPoint(
            chunk_id=uuid.uuid4(),
            vector=[0.1, 0.2],
            payload={"chunk_index": index},
        )
        for index in range(5)
    ]

    await store.upsert_points(points)

    assert mock_client.upsert.await_count == 3


@pytest.mark.asyncio
async def test_upsert_points_rejects_invalid_vector_dimension(
    store: QdrantVectorStore,
    mock_client: AsyncMock,
) -> None:
    point = VectorPoint(chunk_id=CHUNK_ID, vector=[0.1, 0.2], payload={})

    with pytest.raises(VectorStoreError, match="expected 1536"):
        await store.upsert_points([point], expected_vector_size=1536)

    mock_client.upsert.assert_not_awaited()


@pytest.mark.asyncio
async def test_upsert_points_wraps_qdrant_http_errors(
    store: QdrantVectorStore,
    mock_client: AsyncMock,
) -> None:
    from qdrant_client.http.exceptions import UnexpectedResponse

    mock_client.upsert = AsyncMock(
        side_effect=UnexpectedResponse(
            status_code=400,
            reason_phrase="Bad Request",
            content=b"invalid payload",
            headers=httpx.Headers({}),
        ),
    )
    point = VectorPoint(chunk_id=CHUNK_ID, vector=[0.1, 0.2], payload={"chunk_index": 0})

    with pytest.raises(VectorStoreError, match="HTTP 400"):
        await store.upsert_points([point])


@pytest.mark.asyncio
async def test_get_stored_hashes_returns_payload_hashes(
    store: QdrantVectorStore,
    mock_client: AsyncMock,
) -> None:
    mock_client.retrieve = AsyncMock(
        return_value=[
            MagicMock(
                payload={
                    "chunk_id": str(CHUNK_ID),
                    "extracted_text_hash": "hash-1",
                }
            )
        ],
    )

    stored = await store.get_stored_hashes([CHUNK_ID])

    assert stored == {CHUNK_ID: "hash-1"}


@pytest.mark.asyncio
async def test_delete_points_for_drive_file_except_removes_stale_vectors(
    store: QdrantVectorStore,
    mock_client: AsyncMock,
) -> None:
    stale_id = uuid.uuid4()
    mock_client.scroll = AsyncMock(
        return_value=(
            [
                MagicMock(payload={"chunk_id": str(stale_id)}),
                MagicMock(payload={"chunk_id": str(CHUNK_ID)}),
            ],
            None,
        ),
    )

    removed = await store.delete_points_for_drive_file_except(
        drive_file_id=DRIVE_FILE_ID,
        keep_chunk_ids={CHUNK_ID},
    )

    assert removed == 1
    mock_client.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_points_no_ops_for_empty_input(
    store: QdrantVectorStore,
    mock_client: AsyncMock,
) -> None:
    await store.delete_points([])

    mock_client.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_stored_hashes_returns_empty_dict_for_no_ids(
    store: QdrantVectorStore,
    mock_client: AsyncMock,
) -> None:
    stored = await store.get_stored_hashes([])

    assert stored == {}
    mock_client.retrieve.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_similar_returns_scored_chunk_hits(
    store: QdrantVectorStore,
    mock_client: AsyncMock,
) -> None:
    mock_client.query_points = AsyncMock(
        return_value=MagicMock(
            points=[
                MagicMock(id=str(CHUNK_ID), score=0.87, payload=None),
            ],
        ),
    )

    hits = await store.search_similar(
        [0.1] * 1536,
        limit=8,
        score_threshold=0.35,
        expected_vector_size=1536,
    )

    assert hits == [ScoredChunkHit(chunk_id=CHUNK_ID, score=0.87)]
    mock_client.query_points.assert_awaited_once()
    call_kwargs = mock_client.query_points.await_args.kwargs
    assert call_kwargs["collection_name"] == "drivemind_chunks"
    assert call_kwargs["limit"] == 8
    assert call_kwargs["score_threshold"] == 0.35


@pytest.mark.asyncio
async def test_search_similar_rejects_invalid_query_vector(
    store: QdrantVectorStore,
    mock_client: AsyncMock,
) -> None:
    with pytest.raises(VectorStoreError, match="expected 1536"):
        await store.search_similar(
            [0.1, 0.2],
            limit=8,
            expected_vector_size=1536,
        )

    mock_client.query_points.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_similar_wraps_qdrant_http_errors(
    store: QdrantVectorStore,
    mock_client: AsyncMock,
) -> None:
    from qdrant_client.http.exceptions import UnexpectedResponse

    mock_client.query_points = AsyncMock(
        side_effect=UnexpectedResponse(
            status_code=400,
            reason_phrase="Bad Request",
            content=b"invalid search",
            headers=httpx.Headers({}),
        ),
    )

    with pytest.raises(VectorStoreError, match="HTTP 400"):
        await store.search_similar([0.1] * 1536, limit=5)
