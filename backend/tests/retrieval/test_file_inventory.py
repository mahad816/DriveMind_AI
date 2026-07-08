"""Tests for file inventory retrieval and context building."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.enums import DriveFileStatus
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.retrieval.file_inventory import (
    ContentCheckItem,
    FileInventoryRetriever,
    InventoryFile,
    InventoryResult,
    build_inventory_context,
    extract_content_check_terms,
    extract_search_terms,
)

USER_ID = uuid.uuid4()
NOW = datetime.now(UTC)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _drive_file(
    *,
    name: str,
    modified_at: datetime,
    folder_path: str | None = None,
    status: DriveFileStatus = DriveFileStatus.INDEXED,
) -> DriveFile:
    fid = uuid.uuid4()
    return DriveFile(
        id=fid,
        user_id=USER_ID,
        drive_file_id=str(fid),
        name=name,
        mime_type="application/pdf",
        folder_path=folder_path,
        modified_at=modified_at,
        created_at=modified_at,
        updated_at=modified_at,
        status=status,
    )


def _chunk(*, drive_file: DriveFile, text: str, index: int = 0) -> Chunk:
    doc_id = uuid.uuid4()
    doc = Document(
        id=doc_id,
        drive_file_id=drive_file.id,
        extracted_text=text,
        extracted_text_hash="hash",
        page_count=None,
        created_at=drive_file.modified_at,
        updated_at=drive_file.modified_at,
    )
    doc.drive_file = drive_file
    chunk = Chunk(
        id=uuid.uuid4(),
        document_id=doc_id,
        chunk_index=index,
        text=text,
        metadata_json={},
        created_at=drive_file.modified_at,
        updated_at=drive_file.modified_at,
    )
    chunk.document = doc
    return chunk


@pytest.fixture
def mock_db() -> AsyncMock:
    return AsyncMock()


# ── extract_search_terms ──────────────────────────────────────────────────────

def test_extract_terms_from_resume_and_cv_question() -> None:
    q = "can you check all files which have resume name or CV and tell how many in total"
    terms = extract_search_terms(q)
    assert "resume" in terms
    assert "cv" in terms


def test_extract_terms_from_find_latest_resume() -> None:
    terms = extract_search_terms("Find my latest resume")
    assert "resume" in terms


def test_extract_terms_from_certificates() -> None:
    terms = extract_search_terms("show all my certificates")
    # "certificates" is a variant of "certificate"
    assert any("certif" in t for t in terms)


def test_extract_terms_from_quoted_string() -> None:
    terms = extract_search_terms('find files named "my custom file"')
    assert "my custom file" in terms


def test_extract_terms_returns_empty_for_generic_question() -> None:
    terms = extract_search_terms("What does tensile strength mean?")
    assert terms == []


def test_extract_terms_caps_at_six() -> None:
    q = 'find "a" "b" "c" "d" "e" "f" "g" files'
    terms = extract_search_terms(q)
    assert len(terms) <= 6


def test_extract_terms_no_duplicates() -> None:
    q = "find resume and resume files"
    terms = extract_search_terms(q)
    assert len([t for t in terms if t == "resume"]) == 1


def test_extract_terms_multi_word_variant() -> None:
    terms = extract_search_terms("find my curriculum vitae")
    assert "curriculum vitae" in terms


# ── FileInventoryRetriever ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_returns_empty_for_non_inventory_question(mock_db: AsyncMock) -> None:
    retriever = FileInventoryRetriever(db=mock_db)
    result = await retriever.search("What does tensile strength mean?")
    assert result.has_results is False
    assert result.total_count == 0
    assert result.files == []
    assert result.latest_file is None
    mock_db.scalars.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_returns_correct_count_and_latest(mock_db: AsyncMock) -> None:
    newer = _drive_file(name="Resume_2024.pdf", modified_at=NOW)
    older = _drive_file(name="Resume_2022.pdf", modified_at=NOW - timedelta(days=365))
    oldest = _drive_file(name="CV_old.pdf", modified_at=NOW - timedelta(days=730))

    # First scalars call: query_files
    # Second scalars call: fetch_content_chunks (empty for simplicity)
    mock_db.scalars = AsyncMock(
        side_effect=[
            MagicMock(all=MagicMock(return_value=[newer, older, oldest])),
            MagicMock(all=MagicMock(return_value=[])),
        ]
    )

    retriever = FileInventoryRetriever(db=mock_db)
    result = await retriever.search("find all resume and CV files")

    assert result.total_count == 3
    assert result.files[0].name == "Resume_2024.pdf"  # most recent first
    assert result.latest_file is not None
    assert result.latest_file.name == "Resume_2024.pdf"


@pytest.mark.asyncio
async def test_search_fetches_content_chunks_from_latest_file(mock_db: AsyncMock) -> None:
    file = _drive_file(name="Resume_2024.pdf", modified_at=NOW)
    chunk1 = _chunk(drive_file=file, text="Education: BSc Computer Science. GPA: 3.8/4.0", index=0)
    chunk2 = _chunk(drive_file=file, text="Experience: Software Engineer at CoreChain.", index=1)

    mock_db.scalars = AsyncMock(
        side_effect=[
            MagicMock(all=MagicMock(return_value=[file])),
            MagicMock(all=MagicMock(return_value=[chunk1, chunk2])),
        ]
    )
    # "mentions GPA" triggers content check; scalar returns matching chunk text
    mock_db.scalar = AsyncMock(
        return_value="Education: BSc Computer Science. GPA: 3.8/4.0"
    )

    retriever = FileInventoryRetriever(db=mock_db)
    result = await retriever.search("find my latest resume and check if it mentions GPA")

    assert result.total_count == 1
    assert len(result.latest_file_chunks) == 2
    assert "GPA" in result.latest_file_chunks[0]
    # Content check should be populated
    assert len(result.content_checks) == 1
    assert result.content_checks[0].term == "GPA"
    assert result.content_checks[0].found is True
    assert result.content_checks[0].excerpt is not None
    assert "GPA" in result.content_checks[0].excerpt


@pytest.mark.asyncio
async def test_search_no_results_when_no_files_matched(mock_db: AsyncMock) -> None:
    mock_db.scalars = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=[]))
    )
    retriever = FileInventoryRetriever(db=mock_db)
    result = await retriever.search("find all my resumes")

    assert result.has_results is False
    assert result.total_count == 0
    assert result.latest_file is None
    assert result.latest_file_chunks == []


# ── build_inventory_context ───────────────────────────────────────────────────

def test_build_inventory_context_no_results() -> None:
    result = InventoryResult(
        search_terms=["resume"],
        total_count=0,
        files=[],
        latest_file=None,
    )
    context = build_inventory_context(result)
    assert "Total matching files found: 0" in context
    assert "No indexed files matched" in context


def test_build_inventory_context_lists_files() -> None:
    files = [
        InventoryFile(
            drive_file_id="id1",
            name="Resume_2024.pdf",
            mime_type="application/pdf",
            modified_at=NOW,
            folder_path=None,
        ),
        InventoryFile(
            drive_file_id="id2",
            name="CV_old.pdf",
            mime_type="application/pdf",
            modified_at=NOW - timedelta(days=365),
            folder_path="/Documents",
        ),
    ]
    result = InventoryResult(
        search_terms=["resume", "cv"],
        total_count=2,
        files=files,
        latest_file=files[0],
        latest_file_chunks=["Education: BSc. GPA: 3.9"],
    )
    context = build_inventory_context(result)

    assert "Total matching files found: 2" in context
    assert "Resume_2024.pdf" in context
    assert "CV_old.pdf" in context
    assert "Most recently modified: Resume_2024.pdf" in context
    assert "GPA" in context


def test_build_inventory_context_includes_folder_path() -> None:
    files = [
        InventoryFile(
            drive_file_id="id1",
            name="Certificate_AWS.pdf",
            mime_type="application/pdf",
            modified_at=NOW,
            folder_path="/Certifications",
        ),
    ]
    result = InventoryResult(
        search_terms=["certificate"],
        total_count=1,
        files=files,
        latest_file=files[0],
    )
    context = build_inventory_context(result)
    assert "/Certifications" in context


def test_build_inventory_context_search_terms_shown() -> None:
    result = InventoryResult(
        search_terms=["resume", "cv"],
        total_count=0,
        files=[],
        latest_file=None,
    )
    context = build_inventory_context(result)
    assert "resume" in context
    assert "cv" in context


# ── Global file-count path (Phase B) ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_global_count_triggers_all_files_query(mock_db: AsyncMock) -> None:
    """'list total number of files' with no domain terms should use _query_all_files."""
    file1 = _drive_file(name="Resume_2024.pdf", modified_at=NOW)
    file2 = _drive_file(name="Notes.txt", modified_at=NOW - timedelta(days=1))

    mock_db.scalars = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=[file1, file2]))
    )

    retriever = FileInventoryRetriever(db=mock_db)
    result = await retriever.search("list total number of files")

    assert result.total_count == 2
    assert result.is_global_count is True
    assert result.search_terms == []
    mock_db.scalars.assert_awaited()


@pytest.mark.asyncio
async def test_search_global_count_returns_mime_breakdown(mock_db: AsyncMock) -> None:
    """Global count should include a MIME type breakdown."""
    pdf_file = _drive_file(name="Resume.pdf", modified_at=NOW)
    gdoc_file = _drive_file(name="Notes.gdoc", modified_at=NOW - timedelta(days=1))
    gdoc_file.mime_type = "application/vnd.google-apps.document"

    mock_db.scalars = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=[pdf_file, gdoc_file]))
    )

    retriever = FileInventoryRetriever(db=mock_db)
    result = await retriever.search("how many files do I have")

    assert result.total_count == 2
    assert result.is_global_count is True
    assert "PDF" in result.mime_type_counts
    assert "Google Doc" in result.mime_type_counts
    assert result.mime_type_counts["PDF"] == 1
    assert result.mime_type_counts["Google Doc"] == 1


@pytest.mark.asyncio
async def test_search_non_count_question_without_domain_term_stays_empty(
    mock_db: AsyncMock,
) -> None:
    """Non-count questions with no domain term should not trigger any DB query."""
    retriever = FileInventoryRetriever(db=mock_db)
    result = await retriever.search("What does tensile strength mean?")

    assert result.has_results is False
    assert result.is_global_count is False
    mock_db.scalars.assert_not_awaited()


def test_inventory_result_is_global_count_false_when_search_terms_present() -> None:
    result = InventoryResult(
        search_terms=["resume"],
        total_count=2,
        files=[],
        latest_file=None,
    )
    assert result.is_global_count is False


def test_build_inventory_context_global_count_format() -> None:
    """Global count context should show total + breakdown, not 'Search terms used'."""
    files = [
        InventoryFile(
            drive_file_id="id1",
            name="Resume.pdf",
            mime_type="application/pdf",
            modified_at=NOW,
            folder_path=None,
        ),
    ]
    result = InventoryResult(
        search_terms=[],
        total_count=5,
        files=files,
        latest_file=files[0],
        mime_type_counts={"PDF": 3, "Google Doc": 2},
    )
    context = build_inventory_context(result)

    assert "Total indexed files: 5" in context
    assert "PDF: 3" in context
    assert "Google Doc: 2" in context
    assert "Search terms used:" not in context


# ── Content checks (Phase C) ──────────────────────────────────────────────────

def test_extract_content_check_terms_gpa_mention() -> None:
    """'does it include any mention of GPA' should extract GPA check."""
    terms = extract_content_check_terms("does it include any mention of GPA or no")
    assert len(terms) == 1
    search_str, display_label = terms[0]
    assert search_str == "gpa"
    assert display_label == "GPA"


def test_extract_content_check_terms_skills_contains() -> None:
    terms = extract_content_check_terms("does it contain a skills section?")
    assert any(label.lower() == "skills" for _, label in terms)


def test_extract_content_check_terms_no_trigger_returns_empty() -> None:
    """No trigger word → no content checks extracted."""
    terms = extract_content_check_terms("find all my resumes")
    assert terms == []


def test_extract_content_check_terms_no_known_term_returns_empty() -> None:
    """Trigger word but no recognised content term → empty."""
    terms = extract_content_check_terms("does it include anything random xyz")
    assert terms == []


def test_extract_content_check_terms_deduplicates() -> None:
    """Asking 'skills' and 'skill' should produce only one entry."""
    terms = extract_content_check_terms("does it mention skills or any skill")
    search_strs = [s for s, _ in terms]
    assert search_strs.count("skill") == 1


@pytest.mark.asyncio
async def test_run_content_checks_found_in_chunk(mock_db: AsyncMock) -> None:
    """When a chunk contains the search term, ContentCheckItem is found=True."""
    file = _drive_file(name="Resume.pdf", modified_at=NOW)
    mock_db.scalar = AsyncMock(
        return_value="Education: BSc Computer Science. GPA: 3.8/4.0"
    )

    retriever = FileInventoryRetriever(db=mock_db)
    results = await retriever._run_content_checks(file, [("gpa", "GPA")])

    assert len(results) == 1
    assert results[0].term == "GPA"
    assert results[0].found is True
    assert results[0].excerpt is not None
    assert "GPA" in results[0].excerpt


@pytest.mark.asyncio
async def test_run_content_checks_fallback_to_extracted_text(mock_db: AsyncMock) -> None:
    """When no chunk matches, falls back to documents.extracted_text."""
    file = _drive_file(name="Resume.pdf", modified_at=NOW)
    # First scalar call (chunk search) → None (not found in chunks)
    # Second scalar call (extracted_text) → found there
    mock_db.scalar = AsyncMock(
        side_effect=[None, "Full document text — GPA: 3.9/4.0 — Dean's list"]
    )

    retriever = FileInventoryRetriever(db=mock_db)
    results = await retriever._run_content_checks(file, [("gpa", "GPA")])

    assert results[0].found is True
    assert results[0].excerpt is not None
    assert "GPA" in results[0].excerpt
    assert mock_db.scalar.await_count == 2  # chunk search + extracted_text fallback


@pytest.mark.asyncio
async def test_run_content_checks_not_found_returns_false(mock_db: AsyncMock) -> None:
    """When the term is in neither chunks nor extracted_text, found=False."""
    file = _drive_file(name="Resume.pdf", modified_at=NOW)
    # Both scalar calls return None
    mock_db.scalar = AsyncMock(return_value=None)

    retriever = FileInventoryRetriever(db=mock_db)
    results = await retriever._run_content_checks(file, [("gpa", "GPA")])

    assert len(results) == 1
    assert results[0].term == "GPA"
    assert results[0].found is False
    assert results[0].excerpt is None


@pytest.mark.asyncio
async def test_run_content_checks_multiple_terms(mock_db: AsyncMock) -> None:
    """Each term gets its own ContentCheckItem."""
    file = _drive_file(name="Resume.pdf", modified_at=NOW)
    # GPA found, skills not found
    mock_db.scalar = AsyncMock(
        side_effect=[
            "GPA: 3.8/4.0",  # chunk match for gpa
            None,             # chunk search for skill → not found
            None,             # extracted_text for skill → not found
        ]
    )

    retriever = FileInventoryRetriever(db=mock_db)
    results = await retriever._run_content_checks(
        file, [("gpa", "GPA"), ("skill", "skills")]
    )

    assert len(results) == 2
    gpa_check = next(r for r in results if r.term == "GPA")
    skill_check = next(r for r in results if r.term == "skills")
    assert gpa_check.found is True
    assert skill_check.found is False


def test_build_inventory_context_shows_content_checks_found() -> None:
    files = [
        InventoryFile(
            drive_file_id="id1",
            name="Resume_2024.pdf",
            mime_type="application/pdf",
            modified_at=NOW,
            folder_path=None,
        ),
    ]
    result = InventoryResult(
        search_terms=["resume"],
        total_count=1,
        files=files,
        latest_file=files[0],
        content_checks=[
            ContentCheckItem(term="GPA", found=True, excerpt="GPA: 3.8/4.0"),
        ],
    )
    context = build_inventory_context(result)
    assert "Content checks on 'Resume_2024.pdf'" in context
    assert "GPA mentioned: YES" in context
    assert "3.8/4.0" in context


def test_build_inventory_context_shows_content_checks_not_found() -> None:
    files = [
        InventoryFile(
            drive_file_id="id1",
            name="Resume_2024.pdf",
            mime_type="application/pdf",
            modified_at=NOW,
            folder_path=None,
        ),
    ]
    result = InventoryResult(
        search_terms=["resume"],
        total_count=1,
        files=files,
        latest_file=files[0],
        content_checks=[
            ContentCheckItem(term="GPA", found=False),
        ],
    )
    context = build_inventory_context(result)
    assert "GPA mentioned: NO" in context
    assert "not found in indexed content" in context


def test_build_inventory_context_no_content_checks_no_section() -> None:
    """When content_checks is empty, no content-check section should appear."""
    files = [
        InventoryFile(
            drive_file_id="id1",
            name="Resume_2024.pdf",
            mime_type="application/pdf",
            modified_at=NOW,
            folder_path=None,
        ),
    ]
    result = InventoryResult(
        search_terms=["resume"],
        total_count=1,
        files=files,
        latest_file=files[0],
    )
    context = build_inventory_context(result)
    assert "Content checks" not in context
