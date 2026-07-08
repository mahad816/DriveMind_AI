"""Migration integrity tests for Phase 2 schema."""

from __future__ import annotations

import subprocess
import importlib.util
from pathlib import Path


def _backend_dir() -> Path:
    """Return backend project root from test file location."""
    return Path(__file__).resolve().parents[2]


def test_initial_migration_metadata_is_consistent() -> None:
    """Revision metadata should remain stable for initial schema migration."""
    migration_path = (
        _backend_dir() / "alembic" / "versions" / "20260707_1409_initial_phase2_schema.py"
    )
    spec = importlib.util.spec_from_file_location("phase2_migration", migration_path)
    assert spec is not None and spec.loader is not None
    migration_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration_module)

    assert migration_module.revision == "20260707_1409"
    assert migration_module.down_revision is None
    assert callable(migration_module.upgrade)
    assert callable(migration_module.downgrade)


def test_upgrade_sql_contains_all_core_tables() -> None:
    """Offline upgrade SQL should create every core Phase 2 table."""
    result = subprocess.run(
        ["alembic", "upgrade", "head", "--sql"],
        cwd=_backend_dir(),
        check=True,
        capture_output=True,
        text=True,
    )
    sql = result.stdout
    for table in (
        "users",
        "drive_files",
        "documents",
        "chunks",
        "indexing_jobs",
        "query_history",
        "google_oauth_tokens",
        "oauth_pending_states",
        "drive_sync_states",
    ):
        assert f"CREATE TABLE {table}" in sql


def test_downgrade_sql_drops_all_core_tables() -> None:
    """Offline downgrade SQL should drop every core Phase 2 table."""
    result = subprocess.run(
        ["alembic", "downgrade", "20260707_1409:base", "--sql"],
        cwd=_backend_dir(),
        check=True,
        capture_output=True,
        text=True,
    )
    sql = result.stdout
    for table in (
        "query_history",
        "indexing_jobs",
        "chunks",
        "documents",
        "drive_files",
        "users",
    ):
        assert f"DROP TABLE {table}" in sql


def test_upgrade_sql_contains_documents_extracted_text_column() -> None:
    """Offline upgrade SQL should add extracted_text storage on documents."""
    result = subprocess.run(
        ["alembic", "upgrade", "head", "--sql"],
        cwd=_backend_dir(),
        check=True,
        capture_output=True,
        text=True,
    )
    sql = result.stdout
    assert "extracted_text" in sql
    assert "documents" in sql


def test_upgrade_sql_contains_chunks_search_vector_and_gin_index() -> None:
    """Offline upgrade SQL should add chunks FTS vector column and index."""
    result = subprocess.run(
        ["alembic", "upgrade", "head", "--sql"],
        cwd=_backend_dir(),
        check=True,
        capture_output=True,
        text=True,
    )
    sql = result.stdout
    assert "search_vector" in sql
    assert "chunks" in sql
    assert "ix_chunks_search_vector" in sql


def test_documents_extracted_text_migration_metadata_is_consistent() -> None:
    """Revision metadata should remain stable for extracted_text migration."""
    migration_path = (
        _backend_dir() / "alembic" / "versions" / "20260707_1800_add_documents_extracted_text.py"
    )
    spec = importlib.util.spec_from_file_location("phase4_migration", migration_path)
    assert spec is not None and spec.loader is not None
    migration_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration_module)

    assert migration_module.revision == "20260707_1800"
    assert migration_module.down_revision == "20260707_1700"
    assert callable(migration_module.upgrade)
    assert callable(migration_module.downgrade)


def test_chunks_search_vector_migration_metadata_is_consistent() -> None:
    """Revision metadata should remain stable for chunks FTS migration."""
    migration_path = (
        _backend_dir() / "alembic" / "versions" / "20260708_1400_add_chunks_search_vector.py"
    )
    spec = importlib.util.spec_from_file_location("phase7_m2_migration", migration_path)
    assert spec is not None and spec.loader is not None
    migration_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration_module)

    assert migration_module.revision == "20260708_1400"
    assert migration_module.down_revision == "20260707_1800"
    assert callable(migration_module.upgrade)
    assert callable(migration_module.downgrade)


def test_oauth_migration_downgrade_sql_drops_token_table() -> None:
    """Downgrading from head to phase-2 revision should drop oauth token table only."""
    result = subprocess.run(
        ["alembic", "downgrade", "20260707_1500:20260707_1409", "--sql"],
        cwd=_backend_dir(),
        check=True,
        capture_output=True,
        text=True,
    )
    sql = result.stdout
    assert "DROP TABLE google_oauth_tokens" in sql
