"""Metadata-focused retrieval over Drive file attributes."""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.core.config import Settings, get_settings
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.retrieval.types import RetrievedChunk

_LATEST_KEYWORDS = {"latest", "recent", "newest", "last"}

# Extended name-intent hints: added "files", "name", "names" so queries like
# "files named X" or "the file name contains resume" correctly trigger filename
# term extraction without requiring the singular "file" or "filename".
_METADATA_NAME_HINTS = {
    "file",
    "files",
    "filename",
    "name",
    "names",
    "named",
    "called",
    "document",
    "folder",
    "path",
}

_MIME_HINTS: dict[str, str] = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc": "application/vnd.google-apps.document",
    "txt": "text/plain",
}

# Domain file-type terms that should become filename_terms automatically when the
# user is asking for a specific file type by name.  This ensures "latest resume"
# → filename_terms=["resume"] so MetadataRetriever returns only resume-named files,
# not the globally latest files.
_DOMAIN_FILENAME_TERMS: dict[str, str] = {
    "resume": "resume",
    "resumes": "resume",
    "cv": "cv",
    "cvs": "cv",
    "curriculum": "curriculum",
    "certificate": "certificate",
    "certificates": "certificate",
    "certification": "certification",
    "certifications": "certification",
    "transcript": "transcript",
    "transcripts": "transcript",
    "thesis": "thesis",
    "dissertation": "dissertation",
    "report": "report",
    "reports": "report",
    "portfolio": "portfolio",
}


@dataclass(frozen=True)
class MetadataQuerySpec:
    """Parsed metadata hints extracted from a user question."""

    latest_first: bool
    mime_filters: set[str]
    filename_terms: list[str]
    folder_terms: list[str]

    @property
    def has_signals(self) -> bool:
        return bool(
            self.latest_first or self.mime_filters or self.filename_terms or self.folder_terms
        )


class MetadataRetriever:
    """Retrieve representative chunks using Drive file metadata heuristics."""

    def __init__(self, db: AsyncSession, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    async def retrieve(self, question: str) -> list[RetrievedChunk]:
        """Retrieve metadata-matched chunks ranked by heuristic relevance."""
        normalized = question.strip()
        if not normalized:
            return []

        spec = self._parse_query(normalized)
        if not spec.has_signals:
            return []

        matched_chunks = await self._query_chunks(spec)
        if not matched_chunks:
            return []

        scored = self._score_chunks(matched_chunks, spec)
        top_scored = scored[: self.settings.retrieval_candidate_k]

        retrieved: list[RetrievedChunk] = []
        for chunk, score in top_scored:
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
                    score=score,
                    primary_source="metadata",
                    source_scores={"metadata": score},
                )
            )
        return retrieved

    async def _query_chunks(self, spec: MetadataQuerySpec) -> list[Chunk]:
        statement = (
            select(Chunk)
            .join(Document, Chunk.document_id == Document.id)
            .join(DriveFile, Document.drive_file_id == DriveFile.id)
            .where(Chunk.chunk_index == 0)
            .options(selectinload(Chunk.document).selectinload(Document.drive_file))
            .order_by(DriveFile.modified_at.desc())
            .limit(
                max(self.settings.retrieval_candidate_k * 2, self.settings.retrieval_candidate_k)
            )
        )

        filters: list[ColumnElement[bool]] = []
        if spec.mime_filters:
            filters.append(DriveFile.mime_type.in_(spec.mime_filters))

        text_filters = []
        for term in spec.filename_terms:
            text_filters.append(DriveFile.name.ilike(f"%{term}%"))
        for term in spec.folder_terms:
            text_filters.append(DriveFile.folder_path.ilike(f"%{term}%"))
        if text_filters:
            filters.append(or_(*text_filters))

        if filters:
            statement = statement.where(and_(*filters))

        result = await self.db.scalars(statement)
        return list(result.all())

    def _score_chunks(
        self,
        chunks: list[Chunk],
        spec: MetadataQuerySpec,
    ) -> list[tuple[Chunk, float]]:
        scored: list[tuple[Chunk, float]] = []
        for index, chunk in enumerate(chunks):
            document = chunk.document
            drive_file = document.drive_file if document is not None else None
            if drive_file is None:
                continue

            score = 0.05
            if spec.latest_first:
                recency_score = max(0.0, 1.0 - (index / max(len(chunks), 1)))
                score += 0.6 * recency_score
            if spec.mime_filters and drive_file.mime_type in spec.mime_filters:
                score += 0.2
            if spec.filename_terms:
                name = drive_file.name.lower()
                matched = sum(1 for term in spec.filename_terms if term in name)
                if matched:
                    score += 0.2 * (matched / len(spec.filename_terms))
            if spec.folder_terms and drive_file.folder_path:
                folder = drive_file.folder_path.lower()
                matched = sum(1 for term in spec.folder_terms if term in folder)
                if matched:
                    score += 0.2 * (matched / len(spec.folder_terms))

            scored.append((chunk, min(score, 1.0)))
        scored.sort(
            key=lambda item: (
                item[1],
                item[0].document.drive_file.modified_at
                if item[0].document is not None and item[0].document.drive_file is not None
                else 0,
            ),
            reverse=True,
        )
        return scored

    @staticmethod
    def _parse_query(question: str) -> MetadataQuerySpec:
        lowered = question.lower()
        tokens = MetadataRetriever._tokenize(lowered)
        quoted = [match.group(1).strip().lower() for match in re.finditer(r'"([^"]+)"', lowered)]

        latest_first = any(token in _LATEST_KEYWORDS for token in tokens)
        has_name_intent = any(token in _METADATA_NAME_HINTS for token in tokens)
        mime_filters = {mime for token, mime in _MIME_HINTS.items() if token in tokens}

        filename_terms: list[str] = list(dict.fromkeys(quoted))
        if has_name_intent:
            filename_terms.extend(
                [token for token in tokens if len(token) >= 3 and token not in _METADATA_NAME_HINTS]
            )
            filename_terms = list(dict.fromkeys(filename_terms))

        # When asking for latest/recent by file type (e.g. "latest resume", "recent CV"),
        # add the domain term as a filename filter so only that file type is returned —
        # not the globally latest files.  This prevents "latest resume" from returning
        # unrelated recently modified files.
        if latest_first or has_name_intent:
            for token in tokens:
                canonical = _DOMAIN_FILENAME_TERMS.get(token)
                if canonical and canonical not in filename_terms:
                    filename_terms.append(canonical)

        folder_terms = [term for term in tokens if term in {"folder", "class", "course", "notes"}]

        return MetadataQuerySpec(
            latest_first=latest_first,
            mime_filters=mime_filters,
            filename_terms=filename_terms[:6],
            folder_terms=folder_terms[:4],
        )

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        tokens = []
        for raw in text.split():
            cleaned = "".join(ch for ch in raw if ch.isalnum() or ch in {"_", "-"}).strip("-_")
            if len(cleaned) >= 2:
                tokens.append(cleaned)
        return tokens
