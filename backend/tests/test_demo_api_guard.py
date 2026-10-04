"""API checks for demo setup/mutation guards and preserved read/query routes."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.api.dependencies import require_demo_index
from app.api.auth import get_oauth_service
from app.api.chat import get_rag_service
from app.api.files import get_drive_sync_service as get_file_service
from app.api.index import get_drive_sync_service as get_index_service
from app.api.sources import get_source_service
from app.core.config import Settings, get_settings
from app.main import app
from app.services.rag_service import RagResult

REJECTION = {"detail": "This operation is unavailable in public demo mode."}


@pytest.fixture(autouse=True)
def runtime_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    settings = Settings(demo_mode=True)
    monkeypatch.setitem(app.dependency_overrides, get_settings, lambda: settings)
    return settings


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/auth/google", "/auth/google/callback?code=test&state=test"])
async def test_demo_oauth_rejected_before_service_creation(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    factory = MagicMock()

    def forbidden_service() -> None:
        factory()
        raise AssertionError("Blocked OAuth must not create a service or exchange tokens")

    monkeypatch.setitem(app.dependency_overrides, get_oauth_service, forbidden_service)
    response = await async_client.get(
        f"/api/v1{path}", headers={"Accept": "text/html"}, follow_redirects=False
    )

    assert response.status_code == 403
    assert response.json() == REJECTION
    assert "location" not in response.headers
    factory.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["sync", "ingest", "chunk", "build"])
async def test_demo_index_mutations_never_reach_services_or_background_jobs(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    factory = MagicMock()
    background = AsyncMock()

    def forbidden_service() -> None:
        factory()
        raise AssertionError("Blocked sync must not inspect the owner's connection")

    monkeypatch.setitem(app.dependency_overrides, get_index_service, forbidden_service)
    monkeypatch.setattr(f"app.api.index._bg_{stage}", background)
    response = await async_client.post(f"/api/v1/index/{stage}")

    assert response.status_code == 403
    assert response.json() == REJECTION
    factory.assert_not_called()
    background.assert_not_called()


@pytest.mark.asyncio
async def test_normal_oauth_still_reaches_existing_logic(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch, runtime_settings: Settings
) -> None:
    runtime_settings.demo_mode = False
    service = MagicMock()
    service.create_authorization_url = AsyncMock(return_value="https://accounts.google.com/test")
    monkeypatch.setitem(app.dependency_overrides, get_oauth_service, lambda: service)

    response = await async_client.get("/api/v1/auth/google", follow_redirects=False)

    assert response.status_code == 307
    service.create_authorization_url.assert_awaited_once()


@pytest.mark.asyncio
async def test_normal_build_still_runs_existing_background_job(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch, runtime_settings: Settings
) -> None:
    runtime_settings.demo_mode = False
    background = AsyncMock()
    monkeypatch.setattr("app.api.index._bg_build", background)

    response = await async_client.post("/api/v1/index/build")

    assert response.status_code == 202
    assert response.json()["status"] == "started"
    background.assert_awaited_once_with(None)


@pytest.mark.asyncio
async def test_demo_chat_still_reaches_rag_service(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = MagicMock()
    service.ask = AsyncMock(
        return_value=RagResult(
            query_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            question="What is in the sample corpus?",
            answer="Sample answer.",
            citations=[],
            retrieval_count=0,
        )
    )
    monkeypatch.setitem(app.dependency_overrides, require_demo_index, lambda: None)
    monkeypatch.setitem(app.dependency_overrides, get_rag_service, lambda: service)

    response = await async_client.post(
        "/api/v1/chat", json={"question": "What is in the sample corpus?"}
    )

    assert response.status_code == 200
    service.ask.assert_awaited_once_with("What is in the sample corpus?")


@pytest.mark.asyncio
async def test_demo_source_lookup_remains_available(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    chunk_id = uuid.uuid4()
    service = MagicMock()
    service.get_source_chunk = AsyncMock(return_value=None)
    monkeypatch.setitem(app.dependency_overrides, require_demo_index, lambda: None)
    monkeypatch.setitem(app.dependency_overrides, get_source_service, lambda: service)

    response = await async_client.get(f"/api/v1/sources/{chunk_id}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Source chunk not found"}
    service.get_source_chunk.assert_awaited_once_with(chunk_id)


@pytest.mark.asyncio
async def test_demo_file_listing_remains_available(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = MagicMock()
    service.list_synced_files = AsyncMock(return_value=[])
    monkeypatch.setitem(app.dependency_overrides, get_file_service, lambda: service)

    response = await async_client.get("/api/v1/files")

    assert response.status_code == 200
    assert response.json() == {"files": [], "total": 0}
    service.list_synced_files.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/health", "/health/ready", "/index/status", "/index/pending"])
async def test_demo_health_and_index_reads_remain_available(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    service = MagicMock()
    service.is_connected = AsyncMock(return_value=False)
    service.get_pending_counts = AsyncMock(side_effect=ValueError("No connection"))
    monkeypatch.setitem(app.dependency_overrides, get_index_service, lambda: service)
    monkeypatch.setattr("app.api.health.check_db_connection", AsyncMock(return_value=True))

    response = await async_client.get(f"/api/v1{path}")

    assert response.status_code == 200
