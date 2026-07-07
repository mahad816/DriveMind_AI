"""Tests for document ingestion API route."""

from __future__ import annotations

from collections.abc import Generator
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.api.index import get_ingestion_service
from app.main import app
from app.services.ingestion_service import IngestionResult


@pytest.fixture(autouse=True)
def clear_dependency_overrides() -> Generator[None, None, None]:
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_ingest_drive_files_batch_success(async_client: AsyncClient) -> None:
    user_id = uuid.uuid4()
    job_id = uuid.uuid4()
    fake_service = MagicMock()
    fake_service.ingest_files = AsyncMock(
        return_value=IngestionResult(
            job_id=job_id,
            user_id=user_id,
            ingested=3,
            unchanged=1,
            failed=0,
            skipped=2,
            total=6,
        )
    )
    app.dependency_overrides[get_ingestion_service] = lambda: fake_service

    response = await async_client.post("/api/v1/index/ingest")

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "Drive text ingestion (batch) completed"
    assert body["ingested"] == 3
    assert body["unchanged"] == 1
    assert body["skipped"] == 2
    assert body["total"] == 6
    assert body["job_id"] == str(job_id)


@pytest.mark.asyncio
async def test_ingest_single_drive_file_success(async_client: AsyncClient) -> None:
    user_id = uuid.uuid4()
    job_id = uuid.uuid4()
    file_id = uuid.uuid4()
    fake_service = MagicMock()
    fake_service.ingest_files = AsyncMock(
        return_value=IngestionResult(
            job_id=job_id,
            user_id=user_id,
            ingested=1,
            unchanged=0,
            failed=0,
            skipped=0,
            total=1,
        )
    )
    app.dependency_overrides[get_ingestion_service] = lambda: fake_service

    response = await async_client.post(f"/api/v1/index/ingest?file_id={file_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "Drive text ingestion (file) completed"
    assert body["ingested"] == 1
    fake_service.ingest_files.assert_awaited_once_with(file_id=file_id)


@pytest.mark.asyncio
async def test_ingest_drive_files_no_connection_returns_503(async_client: AsyncClient) -> None:
    fake_service = MagicMock()
    fake_service.ingest_files = AsyncMock(
        side_effect=ValueError("No Google Drive connection found. Complete OAuth first.")
    )
    app.dependency_overrides[get_ingestion_service] = lambda: fake_service

    response = await async_client.post("/api/v1/index/ingest")

    assert response.status_code == 503
    assert "No Google Drive connection" in response.json()["detail"]
