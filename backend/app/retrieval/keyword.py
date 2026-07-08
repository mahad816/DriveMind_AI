"""Keyword retrieval over PostgreSQL full-text search."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import case, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.core.config import Settings, get_settings
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.retrieval.types import RetrievedChunk


@dataclass(frozen=True)
class KeywordHit:
    """A chunk ID and keyword score returned from PostgreSQL search."""

    chunk_id: uuid.UUID
    score: float


class KeywordRetriever:
    """Retrieve chunks using PostgreSQL full-text search and filename matches."""

    def __init__(self, db: AsyncSession, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    async def retrieve(self, question: str) -> list[RetrievedChunk]:
        """Search chunks by keyword and hydrate authoritative text from PostgreSQL."""
        normalized = question.strip()
        if not normalized:
            return []

        hits = await self._search_hits(normalized)
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
            score = score_by_id[chunk.id]
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
                    score=score,
                    primary_source="keyword",
                    source_scores={"keyword": score},
                )
            )
        return retrieved

    async def _search_hits(self, question: str) -> list[KeywordHit]:
        ts_query = self._ts_query(question)
        if ts_query is None:
            return []

        filename_match = self._filename_match_expression(question)
        keyword_rank = self._ts_rank_expression(ts_query)
        combined_score = keyword_rank + case((filename_match, 0.2), else_=0.0)

        result = await self.db.execute(
            select(Chunk.id, combined_score.label("score"))
            .join(Document, Chunk.document_id == Document.id)
            .join(DriveFile, Document.drive_file_id == DriveFile.id)
            .where(Chunk.search_vector.op("@@")(ts_query))
            .order_by(combined_score.desc(), Chunk.chunk_index.asc())
            .limit(self.settings.retrieval_candidate_k)
        )

        hits: list[KeywordHit] = []
        for chunk_id, score in result:
            if isinstance(chunk_id, uuid.UUID):
                hits.append(KeywordHit(chunk_id=chunk_id, score=float(score or 0.0)))
        return hits

    def _ts_query(self, question: str) -> ColumnElement[object] | None:
        query_terms = self._query_terms(question)
        if not query_terms:
            return None
        plain_query = " ".join(query_terms)
        return func.websearch_to_tsquery(self.settings.fts_language, plain_query)

    def _ts_rank_expression(self, ts_query: ColumnElement[object]) -> ColumnElement[float]:
        return func.ts_rank_cd(Chunk.search_vector, ts_query)

    def _filename_match_expression(self, question: str) -> ColumnElement[bool]:
        query_terms = self._query_terms(question)
        if not query_terms:
            return false()
        return or_(*[DriveFile.name.ilike(f"%{term}%") for term in query_terms])

    @staticmethod
    def _query_terms(question: str) -> list[str]:
        """Normalize query into deduplicated keyword terms."""
        terms: list[str] = []
        seen: set[str] = set()
        for token in question.lower().split():
            cleaned = "".join(ch for ch in token if ch.isalnum() or ch in {"_", "-"}).strip("-_")
            if len(cleaned) < 2:
                continue
            if cleaned in seen:
                continue
            seen.add(cleaned)
            terms.append(cleaned)
        return terms

    async def _load_chunks(self, chunk_ids: list[uuid.UUID]) -> dict[uuid.UUID, Chunk]:
        if not chunk_ids:
            return {}
        result = await self.db.scalars(
            select(Chunk)
            .where(Chunk.id.in_(chunk_ids))
            .options(selectinload(Chunk.document).selectinload(Document.drive_file))
        )
        return {chunk.id: chunk for chunk in result.all()}
