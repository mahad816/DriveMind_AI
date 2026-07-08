"""File-inventory retrieval — search Drive files by filename pattern.

This module answers questions like:
  "Find all my resume / CV files — how many are there, which is latest, does it mention GPA?"

Unlike the chunk-based retrievers (vector, keyword, metadata), this retriever
queries ``drive_files`` directly by filename ILIKE pattern and returns a
structured result that the LLM can report on accurately — including exact file
counts, sorted modification dates, and content excerpts from the latest match.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import DriveFileStatus
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile


# ── Domain term dictionary ─────────────────────────────────────────────────────
# Maps a canonical key to the search variants the user might say.
# We check each variant against the question and use it as the ILIKE search term.
_DOMAIN_TERMS: dict[str, list[str]] = {
    "resume": ["resume", "resumes"],
    "cv": ["cv", "cvs"],
    "curriculum": ["curriculum vitae", "curriculum"],
    "certificate": ["certificate", "certificates", "certification", "certifications"],
    "transcript": ["transcript", "transcripts"],
    "thesis": ["thesis", "dissertation"],
    "report": ["report", "reports"],
    "cover letter": ["cover letter", "cover letters"],
    "portfolio": ["portfolio"],
}

# Stopwords that should never be used as filename search terms even if they
# appear in the question and don't match a domain entry.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "the", "a", "an", "my", "your", "our", "their", "its",
        "all", "every", "any", "each", "some",
        "and", "or", "in", "on", "at", "for", "of", "to", "from",
        "is", "are", "was", "were", "have", "has", "do", "does", "did",
        "can", "could", "should", "would", "will",
        "find", "show", "list", "check", "get", "tell", "give",
        "how", "many", "which", "what", "who", "when", "where", "why",
        "file", "files", "document", "documents", "latest", "recent",
        "newest", "last", "total", "count", "number", "name", "named",
        "called", "with", "also", "then", "than", "about",
        "me", "i", "it", "no", "not", "yes", "gpa", "date", "time",
        "mention", "mentions", "include", "includes", "contain", "contains",
        "there", "this", "that", "these", "those",
    }
)

# Maximum number of files to list in the inventory.
_MAX_FILES = 20
# Maximum chunks to fetch from the latest match for content questions.
_MAX_CONTENT_CHUNKS = 6

_QUOTED_RE = re.compile(r'"([^"]+)"')


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class InventoryFile:
    """A single file match from the inventory search."""

    drive_file_id: str
    name: str
    mime_type: str
    modified_at: datetime
    folder_path: str | None


@dataclass
class InventoryResult:
    """Structured result from a file inventory search."""

    search_terms: list[str]
    total_count: int
    files: list[InventoryFile]
    latest_file: InventoryFile | None
    latest_file_chunks: list[str] = field(default_factory=list)

    @property
    def has_results(self) -> bool:
        return self.total_count > 0


# ── Retriever ─────────────────────────────────────────────────────────────────

class FileInventoryRetriever:
    """Search drive_files by filename pattern and return a structured inventory."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def search(self, question: str) -> InventoryResult:
        """Extract filename terms from the question then query ``drive_files``."""
        search_terms = extract_search_terms(question)

        if not search_terms:
            return InventoryResult(
                search_terms=[],
                total_count=0,
                files=[],
                latest_file=None,
            )

        drive_files = await self._query_files(search_terms)
        inventory_files = [
            InventoryFile(
                drive_file_id=f.drive_file_id,
                name=f.name,
                mime_type=f.mime_type,
                modified_at=f.modified_at,
                folder_path=f.folder_path,
            )
            for f in drive_files
        ]

        latest_file = inventory_files[0] if inventory_files else None
        latest_chunks: list[str] = []
        if drive_files:
            latest_chunks = await self._fetch_content_chunks(drive_files[0])

        return InventoryResult(
            search_terms=search_terms,
            total_count=len(inventory_files),
            files=inventory_files,
            latest_file=latest_file,
            latest_file_chunks=latest_chunks,
        )

    async def _query_files(self, terms: list[str]) -> list[DriveFile]:
        """Return INDEXED drive files whose name contains any of the given terms."""
        name_filters = [DriveFile.name.ilike(f"%{term}%") for term in terms]
        stmt = (
            select(DriveFile)
            .where(
                DriveFile.status == DriveFileStatus.INDEXED,
                or_(*name_filters),
            )
            .order_by(DriveFile.modified_at.desc())
            .limit(_MAX_FILES)
        )
        result = await self.db.scalars(stmt)
        return list(result.all())

    async def _fetch_content_chunks(self, drive_file: DriveFile) -> list[str]:
        """Fetch text chunks from the most recently modified file."""
        stmt = (
            select(Chunk)
            .join(Document, Chunk.document_id == Document.id)
            .where(Document.drive_file_id == drive_file.id)
            .order_by(Chunk.chunk_index.asc())
            .limit(_MAX_CONTENT_CHUNKS)
        )
        result = await self.db.scalars(stmt)
        return [c.text for c in result.all() if c.text.strip()]


# ── Context builder ───────────────────────────────────────────────────────────

def build_inventory_context(result: InventoryResult) -> str:
    """Render a structured plain-text context block for the LLM.

    The block includes:
    - Total match count
    - Numbered list of all matched files (name + modification date)
    - Most-recent-file callout
    - Content excerpt from the most recent file (for GPA / content questions)
    """
    lines: list[str] = []

    lines.append(f"Search terms used: {', '.join(result.search_terms)}")
    lines.append(f"Total matching files found: {result.total_count}")

    if not result.files:
        lines.append("")
        lines.append("No indexed files matched the search terms.")
        return "\n".join(lines)

    lines.append("")
    lines.append("Matching files (sorted newest to oldest):")
    for i, f in enumerate(result.files, start=1):
        date_str = f.modified_at.strftime("%Y-%m-%d")
        folder = f"  |  Folder: {f.folder_path}" if f.folder_path else ""
        lines.append(f"  {i}. {f.name}  |  Modified: {date_str}{folder}")

    if result.latest_file:
        lines.append("")
        lines.append(f"Most recently modified: {result.latest_file.name}")
        lines.append(
            f"  Modified: {result.latest_file.modified_at.strftime('%Y-%m-%d %H:%M UTC')}"
        )
        if result.latest_file.folder_path:
            lines.append(f"  Folder: {result.latest_file.folder_path}")

    if result.latest_file_chunks:
        lines.append("")
        latest_name = result.latest_file.name if result.latest_file else "latest file"
        lines.append(f"Content excerpt from '{latest_name}':")
        lines.append("---")
        for chunk_text in result.latest_file_chunks:
            stripped = chunk_text.strip()
            if stripped:
                lines.append(stripped)
        lines.append("---")

    return "\n".join(lines)


# ── Term extraction ───────────────────────────────────────────────────────────

def extract_search_terms(question: str) -> list[str]:
    """Extract filename search terms from a user question.

    Priority order:
    1. Quoted strings — e.g. ``"resume"`` → ``["resume"]``
    2. Known domain terms present in the question — ``resume``, ``cv``,
       ``certificate``, etc.

    Returns up to 6 deduplicated terms in order of specificity.
    """
    lower = question.lower()

    # 1. Quoted strings (highest priority — user is explicit)
    quoted = [
        m.group(1).strip()
        for m in _QUOTED_RE.finditer(lower)
        if m.group(1).strip()
    ]
    found: list[str] = list(dict.fromkeys(quoted))

    # 2. Domain terms — check multi-word variants first, then single-word
    for variants in _DOMAIN_TERMS.values():
        for variant in variants:
            if re.search(rf"\b{re.escape(variant)}\b", lower):
                if variant not in found:
                    found.append(variant)
                break  # Only add one variant per canonical (avoid resume+resumes)

    return found[:6]
