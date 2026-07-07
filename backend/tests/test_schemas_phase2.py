"""Validation tests for Phase 2 schema contracts."""

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import ValidationError

from app.db.enums import DriveFileStatus, IndexingJobStatus
from app.schemas.file import ChunkRead, DocumentRead, DriveFileRead
from app.schemas.indexing import IndexingJobCreate, IndexingStatusSummary
from app.schemas.query import CitationItem, QueryHistoryCreate


def test_drive_file_read_schema_accepts_valid_payload() -> None:
    """DriveFileRead should parse complete valid metadata payload."""
    payload = DriveFileRead(
        id=uuid4(),
        user_id=uuid4(),
        drive_file_id="gdrive_123",
        name="resume.pdf",
        mime_type="application/pdf",
        folder_path="/Career",
        modified_at=datetime.now(timezone.utc),
        indexed_at=None,
        status=DriveFileStatus.INDEXED,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    assert payload.status == DriveFileStatus.INDEXED


def test_chunk_read_rejects_negative_chunk_index() -> None:
    """Chunk schema should enforce non-negative chunk indices."""
    try:
        ChunkRead(
            id=uuid4(),
            document_id=uuid4(),
            chunk_index=-1,
            text="chunk text",
            metadata_json={"page": 1},
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    except ValidationError:
        return
    raise AssertionError("Expected ValidationError for negative chunk_index")


def test_indexing_status_summary_defaults_to_zero() -> None:
    """Status summary counters should safely default to zero."""
    summary = IndexingStatusSummary()
    assert summary.queued == 0
    assert summary.running == 0
    assert summary.completed == 0
    assert summary.failed == 0
    assert summary.canceled == 0


def test_query_history_create_allows_citation_items() -> None:
    """Query history create payload should include citation list."""
    citation = CitationItem(
        chunk_id=uuid4(),
        drive_file_id=uuid4(),
        filename="notes.txt",
        snippet="This mentions CoreChain details.",
        score=0.92,
    )
    payload = QueryHistoryCreate(
        user_id=uuid4(),
        question="What mentions CoreChain?",
        answer="Your notes mention CoreChain.",
        citations=[citation],
    )
    assert len(payload.citations) == 1


def test_indexing_job_create_uses_default_status() -> None:
    """IndexingJobCreate should default to queued when status omitted."""
    payload = IndexingJobCreate(user_id=uuid4())
    assert payload.status == IndexingJobStatus.QUEUED


def test_document_read_rejects_negative_page_count() -> None:
    """Document schema should reject invalid negative page counts."""
    try:
        DocumentRead(
            id=uuid4(),
            drive_file_id=uuid4(),
            extracted_text_hash="abc123",
            page_count=-3,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    except ValidationError:
        return
    raise AssertionError("Expected ValidationError for negative page_count")
