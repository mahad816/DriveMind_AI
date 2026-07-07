"""Tests for document chunking API route."""

from __future__ import annotations

from collections.abc import Generator
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.api.index import get_chunking_service
from app.main import app
from app.services.chunking_service import ChunkingResult


@pytest.fixture(autouse=True)
def clear_dependency_overrides() -> Generator[None, None, None]:
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_chunk_extracted_documents_batch_success(async_client: AsyncClient) -> None:
    user_id = uuid.uuid4()
    job_id = uuid.uuid4()
    fake_service = MagicMock()
    fake_service.chunk_documents = AsyncMock(
        return_value=ChunkingResult(
            job_id=job_id,
            user_id=user_id,
            chunked=4,
            unchanged=2,
            skipped=1,
            total=7,
        )
    )
    app.dependency_overrides[get_chunking_service] = lambda: fake_service

    response = await async_client.post("/api/v1/index/chunk")

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "Document chunking (batch) completed"
    assert body["chunked"] == 4
    assert body["unchanged"] == 2
    assert body["skipped"] == 1
    assert body["total"] == 7
    assert body["job_id"] == str(job_id)


@pytest.mark.asyncio
async def test_chunk_single_document_success(async_client: AsyncClient) -> None:
    user_id = uuid.uuid4()
    job_id = uuid.uuid4()
    file_id = uuid.uuid4()
    fake_service = MagicMock()
    fake_service.chunk_documents = AsyncMock(
        return_value=ChunkingResult(
            job_id=job_id,
            user_id=user_id,
            chunked=1,
            unchanged=0,
            skipped=0,
            total=1,
        )
    )
    app.dependency_overrides[get_chunking_service] = lambda: fake_service

    response = await async_client.post(f"/api/v1/index/chunk?file_id={file_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "Document chunking (file) completed"
    assert body["chunked"] == 1
    fake_service.chunk_documents.assert_awaited_once_with(file_id=file_id)


@pytest.mark.asyncio
async def test_chunk_extracted_documents_no_connection_returns_503(
    async_client: AsyncClient,
) -> None:
    fake_service = MagicMock()
    fake_service.chunk_documents = AsyncMock(
        side_effect=ValueError("No Google Drive connection found. Complete OAuth first.")
    )
    app.dependency_overrides[get_chunking_service] = lambda: fake_service

    response = await async_client.post("/api/v1/index/chunk")

    assert response.status_code == 503
    assert "No Google Drive connection" in response.json()["detail"]
