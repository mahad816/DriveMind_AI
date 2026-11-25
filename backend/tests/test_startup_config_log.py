"""The running backend reports which answer path is active, without any secret (stabilization 5.3)."""

import logging
from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.main import app, lifespan


@pytest.mark.asyncio
@pytest.mark.parametrize("dual,agent", [(True, True), (False, False), (True, False), (False, True)])
async def test_startup_logs_the_effective_answer_path_flags_only(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, dual: bool, agent: bool
) -> None:
    settings = Settings(
        **{
            "_env_file": None,  # ignore any local .env
            "retrieval_dual_query_enabled": dual,
            "tool_rag_agent_enabled": agent,
            "openai_api_key": "sk-test-secret-value",
        }
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    monkeypatch.setattr("app.main._cleanup_stuck_jobs", AsyncMock())
    monkeypatch.setattr("app.main.engine", AsyncMock())
    with caplog.at_level(logging.INFO, logger="app.main"):
        async with lifespan(app):
            pass
    lines = [r.getMessage() for r in caplog.records if "effective_config" in r.getMessage()]
    assert len(lines) == 1
    assert f"tool_agent={agent}" in lines[0] and f"dual_query={dual}" in lines[0]
    assert "hybrid=True" in lines[0] and "claim_check=True" in lines[0]
    assert (
        f"max_chunks_per_file={settings.retrieval_max_chunks_per_file}" in lines[0]
    )  # the "cap" of C2-cap3
    assert "sk-test" not in caplog.text
