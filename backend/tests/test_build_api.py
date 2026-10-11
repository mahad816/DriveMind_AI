"""The new indexing consumer is not ready: no legacy dispatch fallback."""

from uuid import UUID
from unittest.mock import AsyncMock
import pytest
from app.api.dependencies import require_index_user
from app.db.session import get_db
from app.main import app


@pytest.mark.parametrize("target", ["", "?file_id=00000000-0000-0000-0000-000000000123"])
async def test_build_closed_until_worker_ready(async_client, monkeypatch, target):
    monkeypatch.setitem(app.dependency_overrides, require_index_user, lambda: UUID(int=101))
    monkeypatch.setitem(app.dependency_overrides, get_db, lambda: AsyncMock())
    app.state.indexing_admission_ready = False
    response = await async_client.post("/api/v1/index/build" + target)
    assert response.status_code == 503
    assert "worker and recovery" in response.json()["detail"]
