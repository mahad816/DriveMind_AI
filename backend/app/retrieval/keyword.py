"""Keyword retrieval over PostgreSQL full-text search."""

from __future__ import annotations

import re
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

# Regex to detect queries that explicitly name a file with an extension.
# Examples: "Resume_2024.pdf", "notes.docx", "report.txt"
_FILENAME_EXT_RE = re.compile(
    r"\b[\w][\w\-_]*\.(?:pdf|docx|doc|txt|pptx|xlsx|csv|png|jpg|jpeg|md)\b",
    re.IGNORECASE,
)

# Score given to chunks returned via filename-only path (no FTS rank available).
# Positioned above the evidence_min_fusion_score (0.15) but below typical strong
# FTS matches so FTS hits still win when they overlap.
_FILENAME_ONLY_SCORE = 0.4

# ── Phrase search constants ────────────────────────────────────────────────────

# Minimum character length for a phrase to trigger phrase-level ILIKE search.
_MIN_PHRASE_LEN = 10

# Score assigned to phrase-matched chunks.  High enough to beat stopword-heavy
# FTS scores for long exact-phrase queries (evidence_min_fusion_score is 0.15).
_PHRASE_SCORE = 0.6

# Extracts a quoted phrase of at least MIN_PHRASE_LEN chars.
# e.g. `'which file has "Connects to a user\'s Google Drive"'`
_QUOTED_PHRASE_RE = re.compile(r'"([^"]{10,})"')

# Extracts a phrase that follows a semantic cue such as "this line:", "which file has:"
_PHRASE_CUE_RE = re.compile(
    r"\b(?:"
    r"this (?:exact )?(?:line|text|sentence|phrase|passage|quote)|"
    r"which (?:file )?(?:has|contains?)|"
    r"find (?:the )?(?:file )?(?:that )?(?:has|contains?)|"
    r"find where it says?|"
    r"file that (?:has|contains?)"
    r")\s*[:\-]?\s+(.{10,})",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class KeywordHit:
    """A chunk ID and keyword score returned from PostgreSQL search."""

    chunk_id: uuid.UUID
    score: float


class KeywordRetriever:
    """Retrieve chunks using PostgreSQL full-text search, filename matches, and phrase search."""

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
        """Return scored hits by merging FTS, filename-only, and phrase-search results.

        Three paths:
        - **FTS path**: ``search_vector @@ ts_query`` ranking via ``websearch_to_tsquery``.
        - **Filename-only path**: ``DriveFile.name ILIKE %term%`` — activated when the
          question names a file with an extension.
        - **Phrase-search path**: ``Chunk.text ILIKE '%exact phrase%'`` — activated when
          the question contains a quoted phrase or a phrase-cue prefix.  Scores at
          ``_PHRASE_SCORE`` (0.6) so long phrases win even when FTS fails due to stopwords.
        """
        ts_query = self._ts_query(question)
        has_filename = self._has_filename_signal(question)
        phrase = self._extract_phrase(question)

        if ts_query is None and not has_filename and phrase is None:
            return []

        hits_by_id: dict[uuid.UUID, KeywordHit] = {}

        # FTS path
        if ts_query is not None:
            for hit in await self._fts_hits(question, ts_query):
                hits_by_id[hit.chunk_id] = hit

        # Filename-only path — supplement FTS with chunks from explicitly named files
        if has_filename:
            for hit in await self._filename_only_hits(question):
                existing = hits_by_id.get(hit.chunk_id)
                if existing is None or hit.score > existing.score:
                    hits_by_id[hit.chunk_id] = hit

        # Phrase-search path — exact substring match on chunk text
        if phrase is not None:
            for hit in await self._phrase_hits(phrase):
                existing = hits_by_id.get(hit.chunk_id)
                if existing is None or hit.score > existing.score:
                    hits_by_id[hit.chunk_id] = hit

        return list(hits_by_id.values())

    async def _fts_hits(
        self,
        question: str,
        ts_query: ColumnElement[object],
    ) -> list[KeywordHit]:
        """Run PostgreSQL full-text search and return ranked hits."""
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

    async def _filename_only_hits(self, question: str) -> list[KeywordHit]:
        """Return chunk IDs from files whose name matches query terms.

        Used when the user mentions a file by name (e.g. ``Resume_2024.pdf``).
        No full-text search is required — only the filename ILIKE filter is applied.
        """
        query_terms = self._query_terms(question)
        if not query_terms:
            return []

        name_filters = [DriveFile.name.ilike(f"%{term}%") for term in query_terms]
        result = await self.db.execute(
            select(Chunk.id)
            .join(Document, Chunk.document_id == Document.id)
            .join(DriveFile, Document.drive_file_id == DriveFile.id)
            .where(or_(*name_filters))
            .order_by(DriveFile.modified_at.desc(), Chunk.chunk_index.asc())
            .limit(self.settings.retrieval_candidate_k)
        )

        return [
            KeywordHit(chunk_id=row[0], score=_FILENAME_ONLY_SCORE)
            for row in result
            if isinstance(row[0], uuid.UUID)
        ]

    async def _phrase_hits(self, phrase: str) -> list[KeywordHit]:
        """Return chunks whose text contains the exact phrase via ILIKE substring match.

        Handles apostrophes and special characters safely via SQLAlchemy parameterised
        binding.  ILIKE wildcards (% and _) present in the phrase are escaped so they
        are treated as literals.

        Args:
            phrase: The raw (un-escaped) phrase extracted from the user question.
        """
        # Escape ILIKE wildcard characters within the phrase literal.
        escaped = phrase.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

        result = await self.db.execute(
            select(Chunk.id)
            .where(Chunk.text.ilike(f"%{escaped}%", escape="\\"))
            .order_by(Chunk.chunk_index.asc())
            .limit(self.settings.retrieval_candidate_k)
        )

        return [
            KeywordHit(chunk_id=row[0], score=_PHRASE_SCORE)
            for row in result
            if isinstance(row[0], uuid.UUID)
        ]

    @staticmethod
    def _extract_phrase(question: str) -> str | None:
        """Extract an exact phrase from a quoted string or after a phrase-cue word.

        Returns the raw phrase (not SQL-escaped) or ``None`` if no phrase is found.

        Priority:
        1. Quoted text: ``"Connects to a user's Google Drive"``
        2. After a cue: ``this line: Connects to a user's Google Drive``
        """
        # Priority 1: quoted phrase
        m = _QUOTED_PHRASE_RE.search(question)
        if m:
            phrase = m.group(1).strip()
            if len(phrase) >= _MIN_PHRASE_LEN:
                return phrase

        # Priority 2: phrase after a semantic cue
        m = _PHRASE_CUE_RE.search(question)
        if m:
            phrase = m.group(1).strip()
            # Trim trailing punctuation / question marks
            phrase = re.sub(r"[?.!]+$", "", phrase).strip()
            if len(phrase) >= _MIN_PHRASE_LEN:
                return phrase

        return None

    @staticmethod
    def _has_filename_signal(question: str) -> bool:
        """Return True when the question explicitly names a file with an extension."""
        return bool(_FILENAME_EXT_RE.search(question))

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
