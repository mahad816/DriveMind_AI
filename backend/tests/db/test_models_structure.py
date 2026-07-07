"""Structural tests for Phase 2 core DB models."""

from app.db.base import Base
from app.db.models import Chunk, Document, DriveFile, IndexingJob, QueryHistory, User


def test_all_core_tables_are_registered() -> None:
    """All expected core tables should be present in SQLAlchemy metadata."""
    expected_tables = {
        "users",
        "drive_files",
        "documents",
        "chunks",
        "indexing_jobs",
        "query_history",
        "google_oauth_tokens",
    }
    assert expected_tables.issubset(set(Base.metadata.tables.keys()))


def test_foreign_keys_exist_for_core_relationships() -> None:
    """Critical foreign-key links should be defined for relational integrity."""
    assert User.__table__.name == "users"

    drive_file_fks = {fk.target_fullname for fk in DriveFile.__table__.foreign_keys}
    assert "users.id" in drive_file_fks

    document_fks = {fk.target_fullname for fk in Document.__table__.foreign_keys}
    assert "drive_files.id" in document_fks

    chunk_fks = {fk.target_fullname for fk in Chunk.__table__.foreign_keys}
    assert "documents.id" in chunk_fks

    indexing_job_fks = {fk.target_fullname for fk in IndexingJob.__table__.foreign_keys}
    assert "users.id" in indexing_job_fks

    query_history_fks = {fk.target_fullname for fk in QueryHistory.__table__.foreign_keys}
    assert "users.id" in query_history_fks


def test_expected_unique_constraints_are_present() -> None:
    """Identity fields should be uniquely constrained where required."""
    user_unique_columns = {col.name for col in User.__table__.columns if col.unique}
    assert {"email", "google_id"}.issubset(user_unique_columns)

    drive_file_unique_columns = {col.name for col in DriveFile.__table__.columns if col.unique}
    assert "drive_file_id" in drive_file_unique_columns
