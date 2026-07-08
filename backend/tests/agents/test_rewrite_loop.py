"""Tests for Phase 8 M6 query rewrite behavior."""

from __future__ import annotations

import uuid
from typing import cast
from unittest.mock import AsyncMock

import pytest

from app.agents.drive_graph.graph import build_drive_graph
from app.agents.drive_graph.nodes import make_rewrite_query_node
from app.agents.drive_graph.state import create_initial_state
from app.agents.drive_graph.types import RetrieverName
from app.core.config import Settings
from app.retrieval.base import Retriever


@pytest.mark.asyncio
async def test_make_rewrite_query_node_uses_injected_rewriter() -> None:
    """Injected rewrite callable should control rewritten query."""
    settings = Settings(agent_max_rewrite_attempts=2)
    rewrite_fn = AsyncMock(return_value="tensile strength material property exact terms")
    node = make_rewrite_query_node(settings=settings, rewrite_fn=rewrite_fn)

    state = create_initial_state(question="What is tensile strength?", user_id=uuid.uuid4())
    state["evidence_reason"] = "Top fused evidence score below minimum threshold."

    update = await node(state)

    rewrite_fn.assert_awaited_once()
    assert update["rewrite_count"] == 1
    assert update["working_query"] == "tensile strength material property exact terms"


@pytest.mark.asyncio
async def test_make_rewrite_query_node_fallback_rewrites_when_empty() -> None:
    """Fallback should rewrite even when custom rewriter returns empty text."""
    settings = Settings(agent_max_rewrite_attempts=2)
    rewrite_fn = AsyncMock(return_value="")
    node = make_rewrite_query_node(settings=settings, rewrite_fn=rewrite_fn)

    state = create_initial_state(question="What is tensile strength?", user_id=uuid.uuid4())
    state["evidence_reason"] = "Vector evidence is weak and keyword evidence is absent."

    update = await node(state)

    assert update["rewrite_count"] == 1
    assert update["working_query"] != state["working_query"]
    assert "exact terms" in update["working_query"]


@pytest.mark.asyncio
async def test_graph_rewrite_loop_honors_attempt_cap() -> None:
    """Graph should rewrite up to max attempts, then move to answer path."""
    settings = Settings(
        agent_max_rewrite_attempts=2,
        evidence_min_fusion_score=0.9,  # force insufficient grading
        retrieval_score_threshold=0.9,
    )

    # Force empty retrieval so grading stays insufficient and loop behavior is deterministic.
    mock_vector = AsyncMock()
    mock_vector.retrieve = AsyncMock(return_value=[])
    mock_keyword = AsyncMock()
    mock_keyword.retrieve = AsyncMock(return_value=[])
    mock_metadata = AsyncMock()
    mock_metadata.retrieve = AsyncMock(return_value=[])

    retrievers = {
        "vector": mock_vector,
        "keyword": mock_keyword,
        "metadata": mock_metadata,
    }
    retrievers_typed = cast(dict[RetrieverName, Retriever], retrievers)

    rewrite_fn = AsyncMock(side_effect=["rewrite one", "rewrite two"])

    compiled = build_drive_graph(
        retrievers=retrievers_typed,
        settings=settings,
        rewrite_fn=rewrite_fn,
    )
    state = create_initial_state(question="What is tensile strength?", user_id=uuid.uuid4())
    state["max_rewrite_attempts"] = settings.agent_max_rewrite_attempts

    final_state = await compiled.ainvoke(state)

    assert final_state["rewrite_count"] == 2
    assert final_state["working_query"] == "rewrite two"
    assert final_state["evidence_sufficient"] is False
    assert rewrite_fn.await_count == 2
