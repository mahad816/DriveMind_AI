"""Tests for Drive sync and file listing API routes."""

from __future__ import annotations

from collections.abc import Generator
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.api.files import get_drive_sync_service
from app.db.enums import DriveFileStatus
from app.db.models.drive_file import DriveFile
from app.main import app
from app.api.dependencies import require_resource_user


@pytest.fixture(autouse=True)
def clear_dependency_overrides() -> Generator[None, None, None]:
    app.dependency_overrides[require_resource_user] = lambda: uuid.UUID(int=101)
    yield
    app.dependency_overrides.clear()


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
    assert (
        response.json()["detail"]
        == "The service is temporarily unavailable. Please try again later."
    )


async def test_sync_closed_until_worker_ready(async_client, monkeypatch):
    from app.api.dependencies import require_index_user
    from app.db.session import get_db

    monkeypatch.setitem(app.dependency_overrides, require_index_user, lambda: uuid.UUID(int=101))
    monkeypatch.setitem(app.dependency_overrides, get_db, lambda: AsyncMock())
    response = await async_client.post("/api/v1/index/sync?full=true")
    assert response.status_code == 503
