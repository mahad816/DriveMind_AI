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
    FileInventoryRetriever,
    InventoryFile,
    InventoryResult,
    build_inventory_context,
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

    retriever = FileInventoryRetriever(db=mock_db)
    result = await retriever.search("find my latest resume and check if it mentions GPA")

    assert result.total_count == 1
    assert len(result.latest_file_chunks) == 2
    assert "GPA" in result.latest_file_chunks[0]


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
