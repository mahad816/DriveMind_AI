"""Health endpoint tests."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_returns_ok(async_client: AsyncClient) -> None:
    """Liveness endpoint should always return 200."""
    response = await async_client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_ready_returns_ok_when_db_connected(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Readiness should return 200 when DB connectivity check passes."""

    async def fake_connected() -> bool:
        return True

    monkeypatch.setattr("app.api.health.check_db_connection", fake_connected)

    response = await async_client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}


@pytest.mark.asyncio
async def test_ready_returns_503_when_db_unavailable(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Readiness should return 503 when DB connectivity check fails."""

    async def fake_disconnected() -> bool:
        return False

    monkeypatch.setattr("app.api.health.check_db_connection", fake_disconnected)

    response = await async_client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "Database not reachable"}
