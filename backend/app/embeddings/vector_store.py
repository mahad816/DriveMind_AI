"""Qdrant vector store for chunk embeddings."""

from __future__ import annotations

import math
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TypedDict

from qdrant_client import AsyncQdrantClient
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from qdrant_client.models import (
    Condition,
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    MatchAny,
    PayloadSchemaType,
    PointIdsList,
    PointStruct,
    VectorParams,
    UpdateStatus,
)

from app.core.config import Settings, get_settings
from app.embeddings.qdrant_connection import create_qdrant_client

DEFAULT_QDRANT_COLLECTION = "drivemind_chunks"
DEFAULT_QDRANT_UPSERT_BATCH_SIZE = 100
DEFAULT_RETRIEVAL_TOP_K = 8
DEFAULT_RETRIEVAL_SCORE_THRESHOLD = 0.35


class _SearchFilterArguments(TypedDict, total=False):
    query_filter: Filter


class VectorStoreError(Exception):
    """Base error raised when vector store operations fail."""


class CollectionCompatibilityError(VectorStoreError):
    """Collection configuration was rejected before any point mutation."""


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
        verify_writes: bool = False,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client
        self.verify_writes = verify_writes
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
        return create_qdrant_client(self.settings)

    async def ensure_collection(self, *, vector_size: int) -> None:
        """Create missing vector storage and reconcile indexes used by payload filters."""
        client = self._get_client()
        try:
            if not await client.collection_exists(self.collection_name):
                try:
                    await client.create_collection(
                        collection_name=self.collection_name,
                        vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
                    )
                except UnexpectedResponse as exc:
                    # Independent owners can discover the same absent collection.
                    # Accept only a now-existing, compatible collection; never
                    # replace it or mask other provider failures.
                    if exc.status_code not in (400, 409) or not await client.collection_exists(
                        self.collection_name
                    ):
                        raise
        except (UnexpectedResponse, ResponseHandlingException) as exc:
            raise VectorStoreError(
                f"Failed to ensure Qdrant collection '{self.collection_name}': {exc}"
            ) from exc
        await self._ensure_required_payload_indexes(client, vector_size=vector_size)

    async def _ensure_required_payload_indexes(
        self, client: AsyncQdrantClient, *, vector_size: int
    ) -> None:
        """Reconcile filter indexes; never silently replace an incompatible schema."""
        fields = ["drive_file_id"]
        if not self.settings.demo_mode:
            fields.append("user_id")
        field = "drive_file_id"
        try:
            info = await client.get_collection(self.collection_name)
            # The same authoritative check covers existing, newly created and
            # concurrently created collections, before even payload-index writes.
            vectors = info.config.params.vectors
            if (
                not isinstance(vectors, VectorParams)
                or vectors.size != vector_size
                or vectors.distance != Distance.COSINE
            ):
                raise CollectionCompatibilityError(
                    "Qdrant collection requires unnamed COSINE vectors "
                    f"with dimension {vector_size}; inspect its configuration."
                )
            for field in fields:
                existing = info.payload_schema.get(field)
                if existing is not None:
                    if existing.data_type in (PayloadSchemaType.KEYWORD, PayloadSchemaType.UUID):
                        continue
                    raise VectorStoreError(
                        f"Qdrant payload index '{field}' must have keyword or UUID schema "
                        f"in collection '{self.collection_name}'"
                    )
                await client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name=field,
                    field_schema=PayloadSchemaType.KEYWORD,
                    wait=True,
                )
        except (UnexpectedResponse, ResponseHandlingException) as exc:
            raise VectorStoreError(
                f"Failed to ensure Qdrant payload index '{field}' "
                f"in collection '{self.collection_name}': {exc}"
            ) from exc

    def _validate_owner(self, user_id: uuid.UUID) -> str:
        """Server runtime selects the realm; neither client input nor failures may switch it."""
        if not isinstance(user_id, uuid.UUID):
            raise VectorStoreError("Vector operations require an explicit owner UUID")
        if self.settings.demo_mode:
            try:
                demo_owner = uuid.UUID(self.settings.demo_user_id)
            except ValueError:
                raise VectorStoreError("Demo vector configuration is invalid") from None
            if user_id != demo_owner or self.collection_name == DEFAULT_QDRANT_COLLECTION:
                raise VectorStoreError("Demo vector operations require the isolated demo corpus")
        return str(user_id)

    async def upsert_points(
        self,
        points: list[VectorPoint],
        *,
        user_id: uuid.UUID,
        expected_vector_size: int | None = None,
    ) -> None:
        """Insert or update chunk vectors in bounded batches."""
        owner = self._validate_owner(user_id)
        if not points:
            return

        for point in points:
            _validate_vector(point.vector, expected_size=expected_vector_size)
            if not self.settings.demo_mode and point.payload.get("user_id") != owner:
                raise VectorStoreError(
                    "Normal vector upserts require the authoritative owner payload"
                )

        client = self._get_client()
        for start in range(0, len(points), self.upsert_batch_size):
            batch = points[start : start + self.upsert_batch_size]
            try:
                existing_payloads: dict[uuid.UUID, dict[str, object]] = {}
                if not self.settings.demo_mode:
                    records = await client.retrieve(
                        collection_name=self.collection_name,
                        ids=[str(point.chunk_id) for point in batch],
                        with_payload=True,
                        with_vectors=False,
                    )
                    for record in records:
                        point_id = _parse_point_id(record.id)
                        if point_id is not None and record.payload is not None:
                            existing_payloads[point_id] = record.payload
                result = await client.upsert(
                    collection_name=self.collection_name,
                    points=[
                        PointStruct(
                            id=str(point.chunk_id),
                            vector=point.vector,
                            payload={
                                **existing_payloads.get(point.chunk_id, {}),
                                **_serialize_payload(point.payload),
                            },
                        )
                        for point in batch
                    ],
                    wait=True,
                )
                self._check_write(getattr(result, "status", None))
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
            result = await client.delete(
                collection_name=self.collection_name,
                points_selector=PointIdsList(points=[str(chunk_id) for chunk_id in chunk_ids]),
                wait=True,
            )
            self._check_write(getattr(result, "status", None))
        except (UnexpectedResponse, ResponseHandlingException) as exc:
            raise VectorStoreError(f"Failed to delete vectors from Qdrant: {exc}") from exc

    async def delete_points_for_drive_file_except(
        self,
        *,
        drive_file_id: uuid.UUID,
        keep_chunk_ids: set[uuid.UUID],
        user_id: uuid.UUID,
        validate_stale_ids: Callable[[list[uuid.UUID]], Awaitable[None]],
    ) -> int:
        """Delete stale vectors for one Drive file, keeping only current chunk IDs."""
        owner = self._validate_owner(user_id)
        client = self._get_client()
        stale_ids: list[uuid.UUID] = []
        offset = None
        conditions: list[Condition] = [
            FieldCondition(key="drive_file_id", match=MatchValue(value=str(drive_file_id)))
        ]
        if not self.settings.demo_mode:
            conditions.append(FieldCondition(key="user_id", match=MatchValue(value=owner)))

        try:
            while True:
                records, offset = await client.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=Filter(must=conditions),
                    limit=100,
                    offset=offset,
                    with_vectors=False,
                )
                for record in records:
                    point_id = _parse_point_id(record.id)
                    payload = record.payload or {}
                    if (
                        point_id is None
                        or payload.get("chunk_id") != str(point_id)
                        or payload.get("drive_file_id") != str(drive_file_id)
                        or (not self.settings.demo_mode and payload.get("user_id") != owner)
                        or not isinstance(payload.get("extracted_text_hash"), str)
                        or not payload["extracted_text_hash"]
                    ):
                        raise VectorStoreError("Stale vector provenance could not be verified")
                    if point_id not in keep_chunk_ids:
                        stale_ids.append(point_id)
                if offset is None:
                    break
        except (UnexpectedResponse, ResponseHandlingException) as exc:
            raise VectorStoreError(
                f"Failed to scan Qdrant vectors for drive file {drive_file_id}: {exc}"
            ) from exc

        # Validate the complete scan before any deletion. Surviving SQL chunks
        # must belong to this file/owner; replaced chunks may no longer exist.
        if stale_ids:
            await validate_stale_ids(stale_ids)
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
                chunk_id = _parse_point_id(record.id)
                if chunk_id not in batch_ids or _parse_chunk_id(record.payload) != chunk_id:
                    raise VectorStoreError("Stored vector identity could not be verified")
                text_hash = record.payload.get("extracted_text_hash") if record.payload else None
                if chunk_id is not None and isinstance(text_hash, str):
                    stored[chunk_id] = text_hash
        return stored

    async def update_unchanged_point_owners(
        self,
        expected_hashes: dict[uuid.UUID, str],
        *,
        user_id: uuid.UUID,
        drive_file_id: uuid.UUID,
    ) -> None:
        """Repair only inspected unchanged points, without replacing vectors or other payloads.

        PostgreSQL supplies the row/file/owner identities and expected content hashes.
        This is ordinary per-document indexing, not a collection migration.
        """
        owner = self._validate_owner(user_id)
        if self.settings.demo_mode or not expected_hashes:
            return
        client = self._get_client()
        ids = list(expected_hashes)
        try:
            for start in range(0, len(ids), self.upsert_batch_size):
                batch = ids[start : start + self.upsert_batch_size]
                records = await client.retrieve(
                    collection_name=self.collection_name,
                    ids=[str(i) for i in batch],
                    with_payload=True,
                    with_vectors=False,
                )
                by_id = {_parse_point_id(record.id): record.payload for record in records}
                for chunk_id in batch:
                    payload = by_id.get(chunk_id)
                    if (
                        payload is None
                        or _parse_chunk_id(payload) != chunk_id
                        or payload.get("drive_file_id") != str(drive_file_id)
                        or payload.get("extracted_text_hash") != expected_hashes[chunk_id]
                    ):
                        raise VectorStoreError("Unchanged vector linkage could not be verified")
                result = await client.set_payload(
                    collection_name=self.collection_name,
                    payload={"user_id": owner},
                    points=[str(i) for i in batch],
                    wait=True,
                )
                self._check_write(getattr(result, "status", None))
        except (UnexpectedResponse, ResponseHandlingException) as exc:
            raise VectorStoreError("Failed to update unchanged vector ownership") from exc

    def _check_write(self, status: object) -> None:
        if self.verify_writes and status != UpdateStatus.COMPLETED:
            raise VectorStoreError("Vector write completion could not be confirmed")

    async def search_similar(
        self,
        query_vector: list[float],
        *,
        user_id: uuid.UUID,
        limit: int,
        score_threshold: float | None = None,
        expected_vector_size: int | None = None,
        file_ids: tuple[uuid.UUID, ...] | None = None,
    ) -> list[ScoredChunkHit]:
        """Return chunk IDs ranked by vector similarity to the query embedding."""
        owner = self._validate_owner(user_id)
        _validate_vector(query_vector, expected_size=expected_vector_size)

        if file_ids is not None and (
            not file_ids or any(not isinstance(i, uuid.UUID) for i in file_ids)
        ):
            raise VectorStoreError("Exact-file search requires resolved non-empty UUID identities")
        conditions: list[Condition] = []
        if not self.settings.demo_mode:
            conditions.append(FieldCondition(key="user_id", match=MatchValue(value=owner)))
        if file_ids is not None:
            conditions.append(
                FieldCondition(key="drive_file_id", match=MatchAny(any=[str(i) for i in file_ids]))
            )
        filters: _SearchFilterArguments = (
            {"query_filter": Filter(must=conditions)} if conditions else {}
        )
        client = self._get_client()
        try:
            response = await client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                limit=limit,
                score_threshold=score_threshold,
                with_payload=False,
                with_vectors=False,
                **filters,
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
