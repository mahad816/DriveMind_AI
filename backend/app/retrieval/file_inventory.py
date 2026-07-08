"""File-inventory retrieval — search Drive files by filename pattern.

This module answers two types of inventory questions:

1. **Domain search** — "Find all my resume / CV files — how many are there, which is
   latest, does it mention GPA?"
   Queries ``drive_files`` by ``name ILIKE`` pattern; returns count, sorted list, a
   content excerpt from the latest match, and targeted content checks (GPA, skills…).

2. **Global count** — "List total number of files", "How many files do I have?"
   No filename term needed.  Queries ALL indexed drive_files and groups by MIME type.

Unlike the chunk-based retrievers (vector, keyword, metadata), this retriever
queries ``drive_files`` directly and returns a structured result that the LLM can
report on accurately — including exact file counts, sorted modification dates, and
content checks (e.g. "GPA mentioned: YES — excerpt: GPA: 3.8/4.0").
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

# Stopwords that should never be used as filename search terms.
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

# Human-readable MIME type labels for global inventory breakdown.
_MIME_FRIENDLY: dict[str, str] = {
    "application/pdf": "PDF",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "DOCX",
    "application/vnd.google-apps.document": "Google Doc",
    "application/vnd.google-apps.spreadsheet": "Google Sheet",
    "application/vnd.google-apps.presentation": "Google Slides",
    "text/plain": "Plain Text",
    "image/jpeg": "JPEG Image",
    "image/jpg": "JPEG Image",
    "image/png": "PNG Image",
    "image/gif": "GIF Image",
    "image/webp": "WebP Image",
}

# ── Content-check vocabulary ───────────────────────────────────────────────────
# Maps a normalized keyword that may appear in the question
# to (ilike_search_str, display_label).
# Both key and ilike_search_str are lowercase.
_CONTENT_CHECK_TERMS: dict[str, tuple[str, str]] = {
    "gpa": ("gpa", "GPA"),
    "grade point average": ("gpa", "GPA"),
    "cgpa": ("cgpa", "CGPA"),
    "grades": ("gpa", "GPA/grades"),
    "skill": ("skill", "skills"),
    "skills": ("skill", "skills"),
    "project": ("project", "projects"),
    "projects": ("project", "projects"),
    "experience": ("experience", "work experience"),
    "work experience": ("experience", "work experience"),
    "internship": ("internship", "internship"),
    "internships": ("internship", "internship"),
    "education": ("education", "education"),
    "degree": ("degree", "degree"),
    "phone": ("phone", "phone number"),
    "phone number": ("phone", "phone number"),
    "email": ("email", "email"),
    "address": ("address", "address"),
    "certification": ("certif", "certifications"),
    "certifications": ("certif", "certifications"),
    "award": ("award", "awards"),
    "awards": ("award", "awards"),
    "github": ("github", "GitHub"),
    "linkedin": ("linkedin", "LinkedIn"),
    "publication": ("publication", "publications"),
    "publications": ("publication", "publications"),
    "reference": ("reference", "references"),
}

# Trigger words indicating "does this file have X?" content-check intent.
_CONTENT_CHECK_TRIGGER_RE = re.compile(
    r"\b(mention|mentions|mentioned|mention of|include|includes|included|"
    r"contain|contains|written|note|state|states|does it|any|has any)\b",
    re.IGNORECASE,
)

# ── Sizing constants ───────────────────────────────────────────────────────────
_MAX_FILES = 20
_MAX_GLOBAL_FILES = 1000
_MAX_CONTENT_CHUNKS = 6
_MAX_EXCERPT_CHARS = 200

_QUOTED_RE = re.compile(r'"([^"]+)"')

_COUNT_INTENT_RE = re.compile(
    r"("
    r"\b(how many|count|total|number of)\b.{0,40}\bfiles?\b"
    r"|"
    r"\b(list all|show all|all my|all indexed)\b.{0,30}\bfiles?\b"
    r"|"
    r"\bfiles?\b.{0,40}\b(how many|count|total|number of)\b"
    r")",
    re.IGNORECASE,
)


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class ContentCheckItem:
    """Result of checking whether a specific term appears in the latest matched file."""

    term: str          # Display label, e.g. "GPA"
    found: bool
    excerpt: str | None = None  # Short surrounding context excerpt if found


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
    # Populated for global count queries (no domain term).
    mime_type_counts: dict[str, int] = field(default_factory=dict)
    # Populated when question asks "does it mention X?" — one item per check term.
    content_checks: list[ContentCheckItem] = field(default_factory=list)

    @property
    def has_results(self) -> bool:
        return self.total_count > 0

    @property
    def is_global_count(self) -> bool:
        """True when this is an all-files result (no domain search terms)."""
        return not self.search_terms and bool(self.mime_type_counts)


# ── Retriever ─────────────────────────────────────────────────────────────────

class FileInventoryRetriever:
    """Search drive_files by filename pattern and return a structured inventory."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def search(self, question: str) -> InventoryResult:
        """Extract filename terms from the question then query ``drive_files``.

        Phases:
        1. Extract domain search terms (resume, cv, …).
        2. If no terms but global-count intent → all-files path.
        3. Query files by ILIKE name patterns; hydrate latest file's chunks.
        4. Run targeted content checks when question has "mention/include/contain X".
        """
        search_terms = extract_search_terms(question)

        if not search_terms:
            if _COUNT_INTENT_RE.search(question):
                return await self._search_all_files()
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
        content_checks: list[ContentCheckItem] = []

        if drive_files:
            latest_chunks = await self._fetch_content_chunks(drive_files[0])

            # Targeted content checks — GPA, skills, certifications, etc.
            check_terms = extract_content_check_terms(question)
            if check_terms:
                content_checks = await self._run_content_checks(drive_files[0], check_terms)

        return InventoryResult(
            search_terms=search_terms,
            total_count=len(inventory_files),
            files=inventory_files,
            latest_file=latest_file,
            latest_file_chunks=latest_chunks,
            content_checks=content_checks,
        )

    async def _search_all_files(self) -> InventoryResult:
        """Return a global inventory of all indexed files grouped by MIME type."""
        all_drive_files = await self._query_all_files()
        inventory_files = [
            InventoryFile(
                drive_file_id=f.drive_file_id,
                name=f.name,
                mime_type=f.mime_type,
                modified_at=f.modified_at,
                folder_path=f.folder_path,
            )
            for f in all_drive_files
        ]
        mime_counts = _count_by_mime(all_drive_files)
        return InventoryResult(
            search_terms=[],
            total_count=len(inventory_files),
            files=inventory_files[:_MAX_FILES],
            latest_file=inventory_files[0] if inventory_files else None,
            mime_type_counts=mime_counts,
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

    async def _query_all_files(self) -> list[DriveFile]:
        """Return all INDEXED drive files, most recently modified first."""
        stmt = (
            select(DriveFile)
            .where(DriveFile.status == DriveFileStatus.INDEXED)
            .order_by(DriveFile.modified_at.desc())
            .limit(_MAX_GLOBAL_FILES)
        )
        result = await self.db.scalars(stmt)
        return list(result.all())

    async def _fetch_content_chunks(self, drive_file: DriveFile) -> list[str]:
        """Fetch text chunks from the most recently modified matched file."""
        stmt = (
            select(Chunk)
            .join(Document, Chunk.document_id == Document.id)
            .where(Document.drive_file_id == drive_file.id)
            .order_by(Chunk.chunk_index.asc())
            .limit(_MAX_CONTENT_CHUNKS)
        )
        result = await self.db.scalars(stmt)
        return [c.text for c in result.all() if c.text.strip()]

    async def _run_content_checks(
        self,
        drive_file: DriveFile,
        terms: list[tuple[str, str]],
    ) -> list[ContentCheckItem]:
        """Check if specific terms appear in the latest file's chunks or extracted_text.

        For each term, searches ALL chunks for the file via ILIKE (not just the first 6).
        Falls back to ``documents.extracted_text`` if no chunk matches.

        Args:
            drive_file: The most recently modified matched file.
            terms: List of ``(ilike_search_str, display_label)`` pairs.

        Returns:
            One ``ContentCheckItem`` per term, with ``found`` and optional ``excerpt``.
        """
        results: list[ContentCheckItem] = []

        for search_str, display_label in terms:
            pattern = f"%{search_str}%"

            # 1. Search ALL chunks for this file (case-insensitive ILIKE).
            chunk_text = await self.db.scalar(
                select(Chunk.text)
                .join(Document, Chunk.document_id == Document.id)
                .where(
                    Document.drive_file_id == drive_file.id,
                    Chunk.text.ilike(pattern),
                )
                .order_by(Chunk.chunk_index.asc())
                .limit(1)
            )

            if chunk_text is not None:
                excerpt = _extract_excerpt(str(chunk_text), search_str)
                results.append(
                    ContentCheckItem(term=display_label, found=True, excerpt=excerpt)
                )
                continue

            # 2. Fallback: search documents.extracted_text for this file.
            extracted_text = await self.db.scalar(
                select(Document.extracted_text)
                .where(
                    Document.drive_file_id == drive_file.id,
                    Document.extracted_text.ilike(pattern),
                )
                .limit(1)
            )

            if extracted_text is not None:
                excerpt = _extract_excerpt(str(extracted_text), search_str)
                results.append(
                    ContentCheckItem(term=display_label, found=True, excerpt=excerpt)
                )
            else:
                results.append(
                    ContentCheckItem(term=display_label, found=False, excerpt=None)
                )

        return results


# ── Context builder ───────────────────────────────────────────────────────────

def build_inventory_context(result: InventoryResult) -> str:
    """Render a structured plain-text context block for the LLM.

    For global count queries: shows total, MIME type breakdown, most recent file.
    For domain searches: shows matched file count, numbered list, content excerpt,
    and any targeted content checks (GPA, skills, etc.).
    """
    lines: list[str] = []

    # ── Global count (no search terms, has MIME breakdown) ────────────────────
    if result.is_global_count:
        lines.append(f"Total indexed files: {result.total_count}")
        if result.mime_type_counts:
            lines.append("")
            lines.append("By file type:")
            for mime_label, count in result.mime_type_counts.items():
                lines.append(f"  - {mime_label}: {count}")
        if result.latest_file:
            date_str = result.latest_file.modified_at.strftime("%Y-%m-%d")
            lines.append("")
            lines.append(
                f"Most recently modified: {result.latest_file.name}  |  Modified: {date_str}"
            )
        if result.files:
            lines.append("")
            lines.append(f"Most recently modified files (showing up to {_MAX_FILES}):")
            for i, f in enumerate(result.files, start=1):
                date_str = f.modified_at.strftime("%Y-%m-%d")
                lines.append(f"  {i}. {f.name}  |  {date_str}")
        return "\n".join(lines)

    # ── Domain search ─────────────────────────────────────────────────────────
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

    # ── Content checks (GPA, skills, etc.) ────────────────────────────────────
    if result.content_checks:
        latest_name = result.latest_file.name if result.latest_file else "latest file"
        lines.append("")
        lines.append(f"Content checks on '{latest_name}':")
        for check in result.content_checks:
            if check.found:
                excerpt_str = f' — excerpt: "{check.excerpt}"' if check.excerpt else ""
                lines.append(f"  - {check.term} mentioned: YES{excerpt_str}")
            else:
                lines.append(
                    f"  - {check.term} mentioned: NO — not found in indexed content."
                )

    return "\n".join(lines)


# ── Term extraction ───────────────────────────────────────────────────────────

def extract_search_terms(question: str) -> list[str]:
    """Extract filename search terms from a user question.

    Priority order:
    1. Quoted strings — e.g. ``"resume"`` → ``["resume"]``
    2. Known domain terms present in the question.

    Returns up to 6 deduplicated terms in order of specificity.
    """
    lower = question.lower()

    quoted = [
        m.group(1).strip()
        for m in _QUOTED_RE.finditer(lower)
        if m.group(1).strip()
    ]
    found: list[str] = list(dict.fromkeys(quoted))

    for variants in _DOMAIN_TERMS.values():
        for variant in variants:
            if re.search(rf"\b{re.escape(variant)}\b", lower):
                if variant not in found:
                    found.append(variant)
                break

    return found[:6]


def extract_content_check_terms(question: str) -> list[tuple[str, str]]:
    """Extract ``(ilike_search_str, display_label)`` pairs for targeted content checks.

    Only returns results when the question has a content-check trigger word
    (mention, include, contain, …) AND contains a known checkable term (gpa, skills, …).

    Examples:
        "does it include any mention of GPA" → [("gpa", "GPA")]
        "does it contain skills section"     → [("skill", "skills")]
        "find all my resumes"                → []  (no trigger word)
    """
    lower = question.lower()

    if not _CONTENT_CHECK_TRIGGER_RE.search(lower):
        return []

    found: list[tuple[str, str]] = []
    seen_search: set[str] = set()

    for question_kw, (search_str, display_label) in _CONTENT_CHECK_TERMS.items():
        if re.search(rf"\b{re.escape(question_kw)}\b", lower):
            if search_str not in seen_search:
                found.append((search_str, display_label))
                seen_search.add(search_str)

    return found


# ── Internal helpers ──────────────────────────────────────────────────────────

def _extract_excerpt(text: str, search_term: str, max_chars: int = _MAX_EXCERPT_CHARS) -> str:
    """Return a short context window centred on the first occurrence of search_term."""
    idx = text.lower().find(search_term.lower())
    if idx < 0:
        return text[:max_chars].strip()
    start = max(0, idx - 50)
    end = min(len(text), idx + max_chars - 50)
    excerpt = text[start:end].strip()
    if start > 0:
        excerpt = "\u2026" + excerpt
    if end < len(text):
        excerpt = excerpt + "\u2026"
    return excerpt


def _count_by_mime(files: list[DriveFile]) -> dict[str, int]:
    """Return a count of files grouped by human-readable MIME type label."""
    counts: dict[str, int] = {}
    for f in files:
        label = _MIME_FRIENDLY.get(f.mime_type, "Other")
        counts[label] = counts.get(label, 0) + 1
    return dict(sorted(counts.items(), key=lambda x: x[1], reverse=True))
