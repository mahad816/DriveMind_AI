"""Tests for document ingestion API route (background task pattern)."""

from __future__ import annotations

from collections.abc import Generator
import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient

from app.main import app


@pytest.fixture(autouse=True)
def clear_dependency_overrides() -> Generator[None, None, None]:
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_ingest_returns_202(async_client: AsyncClient) -> None:
    with patch("app.api.index._bg_ingest"):
        response = await async_client.post("/api/v1/index/ingest")
    assert response.status_code == 202
    assert response.json()["status"] == "started"


@pytest.mark.asyncio
async def test_ingest_with_file_id_returns_202(async_client: AsyncClient) -> None:
    file_id = uuid.uuid4()
    with patch("app.api.index._bg_ingest"):
        response = await async_client.post(f"/api/v1/index/ingest?file_id={file_id}")
    assert response.status_code == 202
