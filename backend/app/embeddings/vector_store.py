"""Qdrant vector store for chunk embeddings."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import datetime

from qdrant_client import AsyncQdrantClient
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
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
DEFAULT_QDRANT_UPSERT_BATCH_SIZE = 100
DEFAULT_RETRIEVAL_TOP_K = 8
DEFAULT_RETRIEVAL_SCORE_THRESHOLD = 0.35


class VectorStoreError(Exception):
    """Base error raised when vector store operations fail."""


@dataclass(frozen=True)
class VectorPoint:
    """A chunk vector and retrieval payload for Qdrant."""

    chunk_id: uuid.UUID
    vector: list[float]
    payload: dict[str, object]


@dataclass(frozen=True)
class ScoredChunkHit:
    """A chunk ID and similarity score returned from Qdrant search."""

    chunk_id: uuid.UUID
    score: float


class QdrantVectorStore:
    """Manage chunk vectors in a Qdrant collection."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: AsyncQdrantClient | None = None,
        upsert_batch_size: int | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client
        self.upsert_batch_size = (
            upsert_batch_size
            if upsert_batch_size is not None
            else self.settings.qdrant_upsert_batch_size or DEFAULT_QDRANT_UPSERT_BATCH_SIZE
        )

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
        try:
            if await client.collection_exists(self.collection_name):
                return
            await client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            )
        except (UnexpectedResponse, ResponseHandlingException) as exc:
            raise VectorStoreError(
                f"Failed to ensure Qdrant collection '{self.collection_name}': {exc}"
            ) from exc

    async def upsert_points(
        self,
        points: list[VectorPoint],
        *,
        expected_vector_size: int | None = None,
    ) -> None:
        """Insert or update chunk vectors in bounded batches."""
        if not points:
            return

        for point in points:
            _validate_vector(point.vector, expected_size=expected_vector_size)

        client = self._get_client()
        for start in range(0, len(points), self.upsert_batch_size):
            batch = points[start : start + self.upsert_batch_size]
            try:
                await client.upsert(
                    collection_name=self.collection_name,
                    points=[
                        PointStruct(
                            id=str(point.chunk_id),
                            vector=point.vector,
                            payload=_serialize_payload(point.payload),
                        )
                        for point in batch
                    ],
                )
            except UnexpectedResponse as exc:
                raise VectorStoreError(
                    f"Qdrant rejected vector upsert (HTTP {exc.status_code}): {exc.content}"
                ) from exc
            except ResponseHandlingException as exc:
                raise VectorStoreError(
                    "Qdrant connection failed during vector upsert. "
                    "Large documents are upserted in batches; if this persists, "
                    "check that Qdrant is healthy and reachable."
                ) from exc

    async def delete_points(self, chunk_ids: list[uuid.UUID]) -> None:
        """Delete vectors for the given chunk IDs."""
        if not chunk_ids:
            return

        client = self._get_client()
        try:
            await client.delete(
                collection_name=self.collection_name,
                points_selector=PointIdsList(points=[str(chunk_id) for chunk_id in chunk_ids]),
            )
        except (UnexpectedResponse, ResponseHandlingException) as exc:
            raise VectorStoreError(f"Failed to delete vectors from Qdrant: {exc}") from exc

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

        try:
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
        except (UnexpectedResponse, ResponseHandlingException) as exc:
            raise VectorStoreError(
                f"Failed to scan Qdrant vectors for drive file {drive_file_id}: {exc}"
            ) from exc

        await self.delete_points(stale_ids)
        return len(stale_ids)

    async def get_stored_hashes(self, chunk_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        """Return stored extracted-text hashes for chunk IDs present in Qdrant."""
        if not chunk_ids:
            return {}

        client = self._get_client()
        stored: dict[uuid.UUID, str] = {}
        for start in range(0, len(chunk_ids), self.upsert_batch_size):
            batch_ids = chunk_ids[start : start + self.upsert_batch_size]
            try:
                records = await client.retrieve(
                    collection_name=self.collection_name,
                    ids=[str(chunk_id) for chunk_id in batch_ids],
                    with_payload=True,
                    with_vectors=False,
                )
            except (UnexpectedResponse, ResponseHandlingException) as exc:
                raise VectorStoreError(
                    f"Failed to read stored vector hashes from Qdrant: {exc}"
                ) from exc

            for record in records:
                chunk_id = _parse_chunk_id(record.payload)
                text_hash = record.payload.get("extracted_text_hash") if record.payload else None
                if chunk_id is not None and isinstance(text_hash, str):
                    stored[chunk_id] = text_hash
        return stored

    async def search_similar(
        self,
        query_vector: list[float],
        *,
        limit: int,
        score_threshold: float | None = None,
        expected_vector_size: int | None = None,
    ) -> list[ScoredChunkHit]:
        """Return chunk IDs ranked by vector similarity to the query embedding."""
        _validate_vector(query_vector, expected_size=expected_vector_size)

        client = self._get_client()
        try:
            response = await client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                limit=limit,
                score_threshold=score_threshold,
                with_payload=False,
                with_vectors=False,
            )
        except UnexpectedResponse as exc:
            raise VectorStoreError(
                f"Qdrant rejected vector search (HTTP {exc.status_code}): {exc.content}"
            ) from exc
        except ResponseHandlingException as exc:
            raise VectorStoreError(
                "Qdrant connection failed during vector search. "
                "Check that Qdrant is healthy and reachable."
            ) from exc

        hits: list[ScoredChunkHit] = []
        for point in response.points:
            chunk_id = _parse_point_id(point.id)
            if chunk_id is None or point.score is None:
                continue
            hits.append(ScoredChunkHit(chunk_id=chunk_id, score=float(point.score)))
        return hits


def _parse_point_id(raw: object) -> uuid.UUID | None:
    if isinstance(raw, uuid.UUID):
        return raw
    if isinstance(raw, str):
        try:
            return uuid.UUID(raw)
        except ValueError:
            return None
    return None


def _validate_vector(vector: list[float], *, expected_size: int | None) -> None:
    if not vector:
        raise VectorStoreError("Cannot upsert an empty embedding vector")
    if expected_size is not None and len(vector) != expected_size:
        raise VectorStoreError(
            f"Embedding vector has dimension {len(vector)}, expected {expected_size}"
        )
    if not all(math.isfinite(value) for value in vector):
        raise VectorStoreError("Embedding vector contains non-finite values")


def _serialize_payload(payload: dict[str, object]) -> dict[str, object]:
    serialized: dict[str, object] = {}
    for key, value in payload.items():
        if value is None:
            continue
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
