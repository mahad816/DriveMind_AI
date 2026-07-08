"""Phase 8 LangGraph skeleton tests (M2)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from app.agents.drive_graph.graph import build_drive_graph
from app.agents.drive_graph.runner import run_drive_graph
from app.agents.drive_graph.state import create_initial_state
from app.core.config import Settings
from app.llm.prompts import NO_EVIDENCE_ANSWER


@pytest.mark.asyncio
async def test_graph_compiles_and_runs_stub_pipeline() -> None:
    """Graph should compile and execute the rewrite loop cap."""
    settings = Settings(agent_max_rewrite_attempts=1)
    user_id = uuid.uuid4()

    state = create_initial_state(question="What is tensile strength?", user_id=user_id)
    state["max_rewrite_attempts"] = settings.agent_max_rewrite_attempts

    compiled = build_drive_graph()
    final_state = await compiled.ainvoke(state)

    assert final_state["rewrite_count"] == 1
    assert final_state["answer"] == NO_EVIDENCE_ANSWER
    assert final_state["citations"] == []
    assert final_state["retrieval_count"] == 0
    assert final_state.get("query_id") is not None


@pytest.mark.asyncio
async def test_runner_returns_ragresult_for_stub_graph() -> None:
    """Runner should wrap graph execution into RagResult."""
    settings = Settings(agent_max_rewrite_attempts=1)
    user_id = uuid.uuid4()
    db = AsyncMock()
    mock_vector = AsyncMock()
    mock_vector.retrieve = AsyncMock(return_value=[])
    mock_keyword = AsyncMock()
    mock_keyword.retrieve = AsyncMock(return_value=[])
    mock_metadata = AsyncMock()
    mock_metadata.retrieve = AsyncMock(return_value=[])

    result = await run_drive_graph(
        db,
        settings,
        question="hello?",
        user_id=user_id,
        retrievers={
            "vector": mock_vector,
            "keyword": mock_keyword,
            "metadata": mock_metadata,
        },
    )

    assert result.user_id == user_id
    assert result.answer == NO_EVIDENCE_ANSWER
    assert result.citations == []
    assert result.retrieval_count == 0
    assert result.query_id is not None
