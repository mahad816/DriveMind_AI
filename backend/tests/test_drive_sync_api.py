"""Tests for Drive sync and file listing API routes (Phase 3 Milestone 4)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.api.files import get_drive_sync_service
from app.api.index import get_drive_sync_service as get_index_sync_service
from app.connectors.google_drive.client import DriveClientError
from app.db.enums import DriveFileStatus, IndexingJobStatus
from app.db.models.drive_file import DriveFile
from app.db.models.indexing_job import IndexingJob
from app.main import app
from app.services.drive_sync_service import DriveSyncResult


@pytest.fixture(autouse=True)
def clear_dependency_overrides() -> None:
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_sync_drive_metadata_success(async_client: AsyncClient) -> None:
    user_id = uuid.uuid4()
    job_id = uuid.uuid4()
    fake_service = MagicMock()
    fake_service.sync_metadata = AsyncMock(
        return_value=DriveSyncResult(
            job_id=job_id,
            user_id=user_id,
            created=2,
            updated=1,
            unchanged=0,
            total_seen=3,
        )
    )
    app.dependency_overrides[get_index_sync_service] = lambda: fake_service

    response = await async_client.post("/api/v1/index/sync")

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "Drive metadata sync completed"
    assert body["created"] == 2
    assert body["updated"] == 1
    assert body["total_seen"] == 3
    assert body["job_id"] == str(job_id)


@pytest.mark.asyncio
async def test_sync_drive_metadata_no_connection_returns_503(async_client: AsyncClient) -> None:
    fake_service = MagicMock()
    fake_service.sync_metadata = AsyncMock(
        side_effect=ValueError("No Google Drive connection found. Complete OAuth first.")
    )
    app.dependency_overrides[get_index_sync_service] = lambda: fake_service

    response = await async_client.post("/api/v1/index/sync")

    assert response.status_code == 503
    assert "No Google Drive connection" in response.json()["detail"]


@pytest.mark.asyncio
async def test_sync_drive_metadata_drive_error_returns_502(async_client: AsyncClient) -> None:
    fake_service = MagicMock()
    fake_service.sync_metadata = AsyncMock(side_effect=DriveClientError("Drive list failed"))
    app.dependency_overrides[get_index_sync_service] = lambda: fake_service

    response = await async_client.post("/api/v1/index/sync")

    assert response.status_code == 502
    assert "Drive list failed" in response.json()["detail"]


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
