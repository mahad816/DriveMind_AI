"""Tests for Drive file content API route (Phase 3 Milestone 5)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.api.files import get_drive_content_service
from app.connectors.google_drive.client import DriveClientError
from app.main import app
from app.services.drive_content_service import DriveFileContent


@pytest.fixture(autouse=True)
def clear_dependency_overrides() -> None:
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_file_content_success(async_client: AsyncClient) -> None:
    file_id = uuid.uuid4()
    fake_service = MagicMock()
    fake_service.fetch_file_content = AsyncMock(
        return_value=DriveFileContent(
            data=b"hello world",
            mime_type="text/plain",
            filename="notes.txt",
            drive_file_id="gdrive-123",
        )
    )
    app.dependency_overrides[get_drive_content_service] = lambda: fake_service

    response = await async_client.get(f"/api/v1/files/{file_id}/content")

    assert response.status_code == 200
    assert response.content == b"hello world"
    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["x-drive-file-id"] == "gdrive-123"


@pytest.mark.asyncio
async def test_get_file_content_not_found(async_client: AsyncClient) -> None:
    file_id = uuid.uuid4()
    fake_service = MagicMock()
    fake_service.fetch_file_content = AsyncMock(side_effect=ValueError("Synced file not found"))
    app.dependency_overrides[get_drive_content_service] = lambda: fake_service

    response = await async_client.get(f"/api/v1/files/{file_id}/content")

    assert response.status_code == 404
    assert response.json()["detail"] == "Synced file not found"


@pytest.mark.asyncio
async def test_get_file_content_drive_error_returns_502(async_client: AsyncClient) -> None:
    file_id = uuid.uuid4()
    fake_service = MagicMock()
    fake_service.fetch_file_content = AsyncMock(
        side_effect=DriveClientError("Drive file download failed")
    )
    app.dependency_overrides[get_drive_content_service] = lambda: fake_service

    response = await async_client.get(f"/api/v1/files/{file_id}/content")

    assert response.status_code == 502
    assert "download failed" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_file_content_no_connection_returns_503(async_client: AsyncClient) -> None:
    file_id = uuid.uuid4()
    fake_service = MagicMock()
    fake_service.fetch_file_content = AsyncMock(
        side_effect=ValueError("No Google Drive connection found. Complete OAuth first.")
    )
    app.dependency_overrides[get_drive_content_service] = lambda: fake_service

    response = await async_client.get(f"/api/v1/files/{file_id}/content")

    assert response.status_code == 503
    assert "No Google Drive connection" in response.json()["detail"]
