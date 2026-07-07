"""Tests for Qdrant vector store."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import Settings
from app.embeddings.vector_store import QdrantVectorStore, VectorPoint

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
