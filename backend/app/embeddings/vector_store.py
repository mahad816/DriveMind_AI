"""Qdrant vector store for chunk embeddings."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointIdsList,
    PointStruct,
    VectorParams,
)

from app.core.config import Settings, get_settings

DEFAULT_QDRANT_COLLECTION = "drivemind_chunks"


class VectorStoreError(Exception):
    """Base error raised when vector store operations fail."""


@dataclass(frozen=True)
class VectorPoint:
    """A chunk vector and retrieval payload for Qdrant."""

    chunk_id: uuid.UUID
    vector: list[float]
    payload: dict[str, object]


class QdrantVectorStore:
    """Manage chunk vectors in a Qdrant collection."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: AsyncQdrantClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client

    @property
    def collection_name(self) -> str:
        return self.settings.qdrant_collection or DEFAULT_QDRANT_COLLECTION

    def _get_client(self) -> AsyncQdrantClient:
        if self._client is not None:
            return self._client
        return AsyncQdrantClient(
            host=self.settings.qdrant_host,
            port=self.settings.qdrant_port,
        )

    async def ensure_collection(self, *, vector_size: int) -> None:
        """Create the collection when missing."""
        client = self._get_client()
        if await client.collection_exists(self.collection_name):
            return
        await client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )

    async def upsert_points(self, points: list[VectorPoint]) -> None:
        """Insert or update chunk vectors."""
        if not points:
            return

        client = self._get_client()
        await client.upsert(
            collection_name=self.collection_name,
            points=[
                PointStruct(
                    id=str(point.chunk_id),
                    vector=point.vector,
                    payload=_serialize_payload(point.payload),
                )
                for point in points
            ],
        )

    async def delete_points(self, chunk_ids: list[uuid.UUID]) -> None:
        """Delete vectors for the given chunk IDs."""
        if not chunk_ids:
            return

        client = self._get_client()
        await client.delete(
            collection_name=self.collection_name,
            points_selector=PointIdsList(points=[str(chunk_id) for chunk_id in chunk_ids]),
        )

    async def delete_points_for_drive_file_except(
        self,
        *,
        drive_file_id: uuid.UUID,
        keep_chunk_ids: set[uuid.UUID],
    ) -> int:
        """Delete stale vectors for one Drive file, keeping only current chunk IDs."""
        client = self._get_client()
        stale_ids: list[uuid.UUID] = []
        offset = None

        while True:
            records, offset = await client.scroll(
                collection_name=self.collection_name,
                scroll_filter=Filter(
                    must=[
                        FieldCondition(
                            key="drive_file_id",
                            match=MatchValue(value=str(drive_file_id)),
                        )
                    ]
                ),
                limit=100,
                offset=offset,
                with_vectors=False,
            )
            for record in records:
                chunk_id = _parse_chunk_id(record.payload)
                if chunk_id is not None and chunk_id not in keep_chunk_ids:
                    stale_ids.append(chunk_id)
            if offset is None:
                break

        await self.delete_points(stale_ids)
        return len(stale_ids)

    async def get_stored_hashes(self, chunk_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        """Return stored extracted-text hashes for chunk IDs present in Qdrant."""
        if not chunk_ids:
            return {}

        client = self._get_client()
        records = await client.retrieve(
            collection_name=self.collection_name,
            ids=[str(chunk_id) for chunk_id in chunk_ids],
            with_payload=True,
            with_vectors=False,
        )

        stored: dict[uuid.UUID, str] = {}
        for record in records:
            chunk_id = _parse_chunk_id(record.payload)
            text_hash = record.payload.get("extracted_text_hash") if record.payload else None
            if chunk_id is not None and isinstance(text_hash, str):
                stored[chunk_id] = text_hash
        return stored


def _serialize_payload(payload: dict[str, object]) -> dict[str, object]:
    serialized: dict[str, object] = {}
    for key, value in payload.items():
        if isinstance(value, datetime):
            serialized[key] = value.isoformat()
        elif isinstance(value, uuid.UUID):
            serialized[key] = str(value)
        else:
            serialized[key] = value
    return serialized


def _parse_chunk_id(payload: dict[str, object] | None) -> uuid.UUID | None:
    if payload is None:
        return None
    raw = payload.get("chunk_id")
    if not isinstance(raw, str):
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None
