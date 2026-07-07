"""Tests for citation source viewer API route."""

from __future__ import annotations

from collections.abc import Generator
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.api.sources import get_source_service
from app.main import app
from app.schemas.source import SourceChunkRead

CHUNK_ID = uuid.uuid4()
DRIVE_FILE_ID = uuid.uuid4()


@pytest.fixture(autouse=True)
def clear_dependency_overrides() -> Generator[None, None, None]:
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_source_chunk_success(async_client: AsyncClient) -> None:
    fake_service = MagicMock()
    fake_service.get_source_chunk = AsyncMock(
        return_value=SourceChunkRead(
            chunk_id=CHUNK_ID,
            drive_file_id=DRIVE_FILE_ID,
            filename="notes.txt",
            mime_type="text/plain",
            chunk_index=0,
            text="Tensile strength is a material property.",
            modified_at=datetime.now(UTC),
        ),
    )
    app.dependency_overrides[get_source_service] = lambda: fake_service

    response = await async_client.get(f"/api/v1/sources/{CHUNK_ID}")

    assert response.status_code == 200
    body = response.json()
    assert body["chunk_id"] == str(CHUNK_ID)
    assert body["drive_file_id"] == str(DRIVE_FILE_ID)
    assert body["filename"] == "notes.txt"
    assert body["text"] == "Tensile strength is a material property."
    fake_service.get_source_chunk.assert_awaited_once_with(CHUNK_ID)


@pytest.mark.asyncio
async def test_get_source_chunk_not_found_returns_404(async_client: AsyncClient) -> None:
    fake_service = MagicMock()
    fake_service.get_source_chunk = AsyncMock(return_value=None)
    app.dependency_overrides[get_source_service] = lambda: fake_service

    response = await async_client.get(f"/api/v1/sources/{CHUNK_ID}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Source chunk not found"


@pytest.mark.asyncio
async def test_get_source_chunk_invalid_uuid_returns_422(async_client: AsyncClient) -> None:
    response = await async_client.get("/api/v1/sources/not-a-uuid")

    assert response.status_code == 422
