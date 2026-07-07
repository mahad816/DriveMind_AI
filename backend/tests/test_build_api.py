"""Tests for vector index build API route."""

from __future__ import annotations

from collections.abc import Generator
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.api.index import get_indexing_service
from app.embeddings.base import EmbeddingConfigurationError
from app.main import app
from app.services.indexing_service import IndexBuildResult


@pytest.fixture(autouse=True)
def clear_dependency_overrides() -> Generator[None, None, None]:
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_build_vector_index_batch_success(async_client: AsyncClient) -> None:
    user_id = uuid.uuid4()
    job_id = uuid.uuid4()
    fake_service = MagicMock()
    fake_service.build_index = AsyncMock(
        return_value=IndexBuildResult(
            job_id=job_id,
            user_id=user_id,
            embedded=5,
            unchanged=3,
            skipped=1,
            removed=2,
            total=9,
        )
    )
    app.dependency_overrides[get_indexing_service] = lambda: fake_service

    response = await async_client.post("/api/v1/index/build")

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "Vector index build (batch) completed"
    assert body["embedded"] == 5
    assert body["unchanged"] == 3
    assert body["removed"] == 2
    assert body["job_id"] == str(job_id)


@pytest.mark.asyncio
async def test_build_single_file_index_success(async_client: AsyncClient) -> None:
    user_id = uuid.uuid4()
    job_id = uuid.uuid4()
    file_id = uuid.uuid4()
    fake_service = MagicMock()
    fake_service.build_index = AsyncMock(
        return_value=IndexBuildResult(
            job_id=job_id,
            user_id=user_id,
            embedded=1,
            unchanged=0,
            skipped=0,
            removed=0,
            total=1,
        )
    )
    app.dependency_overrides[get_indexing_service] = lambda: fake_service

    response = await async_client.post(f"/api/v1/index/build?file_id={file_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "Vector index build (file) completed"
    fake_service.build_index.assert_awaited_once_with(file_id=file_id)


@pytest.mark.asyncio
async def test_build_vector_index_no_connection_returns_503(async_client: AsyncClient) -> None:
    fake_service = MagicMock()
    fake_service.build_index = AsyncMock(
        side_effect=ValueError("No Google Drive connection found. Complete OAuth first.")
    )
    app.dependency_overrides[get_indexing_service] = lambda: fake_service

    response = await async_client.post("/api/v1/index/build")

    assert response.status_code == 503
    assert "No Google Drive connection" in response.json()["detail"]


@pytest.mark.asyncio
async def test_build_vector_index_missing_openai_key_returns_503(
    async_client: AsyncClient,
) -> None:
    fake_service = MagicMock()
    fake_service.build_index = AsyncMock(
        side_effect=EmbeddingConfigurationError("OPENAI_API_KEY is not configured"),
    )
    app.dependency_overrides[get_indexing_service] = lambda: fake_service

    response = await async_client.post("/api/v1/index/build")

    assert response.status_code == 503
    assert "OPENAI_API_KEY" in response.json()["detail"]
