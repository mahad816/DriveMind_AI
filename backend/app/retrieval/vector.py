"""Vector similarity retrieval over Qdrant with Postgres chunk hydration."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings, get_settings
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.embeddings.base import EmbeddingService
from app.embeddings.factory import get_embedding_service
from app.embeddings.vector_store import QdrantVectorStore
from app.retrieval.types import RetrievedChunk


class VectorRetriever:
    """Retrieve ranked chunks for a natural-language question."""

    def __init__(
        self,
        db: AsyncSession,
        settings: Settings | None = None,
        *,
        embedding_service: EmbeddingService | None = None,
        vector_store: QdrantVectorStore | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.embedding_service = embedding_service or get_embedding_service(self.settings)
        self.vector_store = vector_store or QdrantVectorStore(self.settings)

    async def retrieve(self, question: str) -> list[RetrievedChunk]:
        """Embed the question, search Qdrant, and hydrate chunk text from PostgreSQL."""
        normalized = question.strip()
        if not normalized:
            return []

        query_vector = (await self.embedding_service.embed_texts([normalized]))[0]
        hits = await self.vector_store.search_similar(
            query_vector,
            limit=self.settings.retrieval_candidate_k,
            score_threshold=self.settings.retrieval_score_threshold,
            expected_vector_size=self.embedding_service.embedding_dimension,
        )
        if not hits:
            return []

        chunk_ids = [hit.chunk_id for hit in hits]
        chunks_by_id = await self._load_chunks(chunk_ids)
        score_by_id = {hit.chunk_id: hit.score for hit in hits}

        retrieved: list[RetrievedChunk] = []
        for hit in hits:
            chunk = chunks_by_id.get(hit.chunk_id)
            if chunk is None:
                continue
            document = chunk.document
            drive_file = document.drive_file if document is not None else None
            if document is None or drive_file is None:
                continue
            retrieved.append(
                RetrievedChunk(
                    chunk_id=chunk.id,
                    document_id=document.id,
                    drive_file_id=drive_file.id,
                    filename=drive_file.name,
                    mime_type=drive_file.mime_type,
                    modified_at=drive_file.modified_at,
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    score=score_by_id[chunk.id],
                    primary_source="vector",
                    source_scores={"vector": score_by_id[chunk.id]},
                )
            )
        return retrieved

    async def _load_chunks(self, chunk_ids: list[uuid.UUID]) -> dict[uuid.UUID, Chunk]:
        if not chunk_ids:
            return {}

        result = await self.db.scalars(
            select(Chunk)
            .where(Chunk.id.in_(chunk_ids))
            .options(
                selectinload(Chunk.document).selectinload(Document.drive_file),
            )
        )
        return {chunk.id: chunk for chunk in result.all()}
