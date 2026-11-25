"""`/index/status` tells the UI whether the sync executor is accepting jobs."""

from __future__ import annotations

import uuid
from collections.abc import Generator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.api.index import get_drive_sync_service, get_indexing_job_service, require_index_read_user
from app.core.config import get_settings
from app.main import app


@pytest.fixture(autouse=True)
def overrides() -> Generator[None, None, None]:
    owner = uuid.UUID(int=101)
    service = MagicMock()
    service.is_connected = AsyncMock(return_value=True)
    jobs = MagicMock()
    jobs.get_job = AsyncMock(return_value=None)
    app.dependency_overrides[require_index_read_user] = lambda: owner
    app.dependency_overrides[get_drive_sync_service] = lambda: service
    app.dependency_overrides[get_indexing_job_service] = lambda: jobs
    app.dependency_overrides[get_settings] = lambda: SimpleNamespace(demo_mode=False)  # type: ignore[assignment]
    yield
    app.dependency_overrides.clear()


def _state(monkeypatch: pytest.MonkeyPatch, *, supervisor: object | None, ready: bool) -> None:
    monkeypatch.setattr(app.state, "indexing_supervisor", supervisor, raising=False)
    monkeypatch.setattr(app.state, "indexing_admission_ready", ready, raising=False)


@pytest.mark.asyncio
async def test_status_reports_sync_unavailable_when_no_executor(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _state(monkeypatch, supervisor=None, ready=False)
    body = (await async_client.get("/api/v1/index/status")).json()
    assert body["connected"] is True
    assert body["sync_available"] is False


@pytest.mark.asyncio
async def test_status_reports_sync_unavailable_when_supervisor_unhealthy(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _state(monkeypatch, supervisor=SimpleNamespace(healthy=False), ready=True)
    assert (await async_client.get("/api/v1/index/status")).json()["sync_available"] is False


@pytest.mark.asyncio
async def test_status_reports_sync_available_only_when_open_and_healthy(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _state(monkeypatch, supervisor=SimpleNamespace(healthy=True), ready=True)
    assert (await async_client.get("/api/v1/index/status")).json()["sync_available"] is True
    _state(monkeypatch, supervisor=SimpleNamespace(healthy=True), ready=False)
    assert (await async_client.get("/api/v1/index/status")).json()["sync_available"] is False
