"""Tests for Drive sync and file listing API routes."""

from __future__ import annotations

from collections.abc import Generator
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.api.files import get_drive_sync_service
from app.api.index import get_drive_sync_service as get_index_sync_service
from app.db.enums import DriveFileStatus, IndexingJobStatus
from app.db.models.drive_file import DriveFile
from app.db.models.indexing_job import IndexingJob
from app.main import app


@pytest.fixture(autouse=True)
def clear_dependency_overrides() -> Generator[None, None, None]:
    yield
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /index/sync  (now returns 202 immediately; actual sync runs in background)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_drive_metadata_accepted(async_client: AsyncClient) -> None:
    """Connected account → 202 with started status."""
    fake_service = MagicMock()
    fake_service.is_connected = AsyncMock(return_value=True)
    app.dependency_overrides[get_index_sync_service] = lambda: fake_service

    with patch("app.api.index._bg_sync"):
        response = await async_client.post("/api/v1/index/sync")

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "started"


@pytest.mark.asyncio
async def test_sync_drive_metadata_full_scan_accepted(async_client: AsyncClient) -> None:
    """full=true → still 202 with started status."""
    fake_service = MagicMock()
    fake_service.is_connected = AsyncMock(return_value=True)
    app.dependency_overrides[get_index_sync_service] = lambda: fake_service

    with patch("app.api.index._bg_sync"):
        response = await async_client.post("/api/v1/index/sync?full=true")

    assert response.status_code == 202


@pytest.mark.asyncio
async def test_sync_drive_metadata_no_connection_returns_503(async_client: AsyncClient) -> None:
    """Not connected → 503 before any background work starts."""
    fake_service = MagicMock()
    fake_service.is_connected = AsyncMock(return_value=False)
    app.dependency_overrides[get_index_sync_service] = lambda: fake_service

    response = await async_client.post("/api/v1/index/sync")

    assert response.status_code == 503
    assert "No Google Drive connection" in response.json()["detail"]


@pytest.mark.asyncio
async def test_sync_connection_check_error_returns_503(async_client: AsyncClient) -> None:
    """Exception during is_connected check → 503."""
    fake_service = MagicMock()
    fake_service.is_connected = AsyncMock(side_effect=RuntimeError("DB gone"))
    app.dependency_overrides[get_index_sync_service] = lambda: fake_service

    response = await async_client.post("/api/v1/index/sync")

    assert response.status_code == 503


# ---------------------------------------------------------------------------
# GET /index/status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_sync_status_not_connected(async_client: AsyncClient) -> None:
    fake_service = MagicMock()
    fake_service.is_connected = AsyncMock(return_value=False)
    app.dependency_overrides[get_index_sync_service] = lambda: fake_service

    response = await async_client.get("/api/v1/index/status")

    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is False
    assert body["job"] is None


@pytest.mark.asyncio
async def test_get_sync_status_with_latest_job(async_client: AsyncClient) -> None:
    user_id = uuid.uuid4()
    job = IndexingJob(
        id=uuid.uuid4(),
        user_id=user_id,
        status=IndexingJobStatus.COMPLETED,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    fake_service = MagicMock()
    fake_service.is_connected = AsyncMock(return_value=True)
    fake_service.get_latest_sync_job = AsyncMock(return_value=job)
    app.dependency_overrides[get_index_sync_service] = lambda: fake_service

    response = await async_client.get("/api/v1/index/status")

    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is True
    assert body["job"]["status"] == "completed"


# ---------------------------------------------------------------------------
# POST /index/ingest, /chunk, /build  (also 202 background tasks)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_returns_202(async_client: AsyncClient) -> None:
    with patch("app.api.index._bg_ingest"):
        response = await async_client.post("/api/v1/index/ingest")
    assert response.status_code == 202
    assert response.json()["status"] == "started"


@pytest.mark.asyncio
async def test_chunk_returns_202(async_client: AsyncClient) -> None:
    with patch("app.api.index._bg_chunk"):
        response = await async_client.post("/api/v1/index/chunk")
    assert response.status_code == 202
    assert response.json()["status"] == "started"


@pytest.mark.asyncio
async def test_build_returns_202(async_client: AsyncClient) -> None:
    with patch("app.api.index._bg_build"):
        response = await async_client.post("/api/v1/index/build")
    assert response.status_code == 202
    assert response.json()["status"] == "started"


# ---------------------------------------------------------------------------
# GET /files
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_synced_files_success(async_client: AsyncClient) -> None:
    user_id = uuid.uuid4()
    drive_file = DriveFile(
        id=uuid.uuid4(),
        user_id=user_id,
        drive_file_id="gdrive-abc",
        name="resume.pdf",
        mime_type="application/pdf",
        modified_at=datetime.now(UTC),
        status=DriveFileStatus.DISCOVERED,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    fake_service = MagicMock()
    fake_service.list_synced_files = AsyncMock(return_value=[drive_file])
    app.dependency_overrides[get_drive_sync_service] = lambda: fake_service

    response = await async_client.get("/api/v1/files")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["files"][0]["name"] == "resume.pdf"
    assert body["files"][0]["drive_file_id"] == "gdrive-abc"


@pytest.mark.asyncio
async def test_list_synced_files_no_connection_returns_503(async_client: AsyncClient) -> None:
    fake_service = MagicMock()
    fake_service.list_synced_files = AsyncMock(
        side_effect=ValueError("No Google Drive connection found. Complete OAuth first.")
    )
    app.dependency_overrides[get_drive_sync_service] = lambda: fake_service

    response = await async_client.get("/api/v1/files")

    assert response.status_code == 503
    assert "No Google Drive connection" in response.json()["detail"]
