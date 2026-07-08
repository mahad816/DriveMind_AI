"""Tests for Phase 8 M5: rerank, evidence grading, and rewrite routing."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock

import pytest

from app.agents.drive_graph.graph import build_drive_graph, should_rewrite
from app.agents.drive_graph.nodes import make_grade_evidence_node, make_rerank_node
from app.agents.drive_graph.state import create_initial_state
from app.agents.drive_graph.types import RetrieverName
from app.core.config import Settings
from app.retrieval.base import Retriever
from app.retrieval.types import RetrievedChunk, RetrievalSource


def _chunk(
    *,
    score: float,
    fusion_score: float | None = None,
    source_scores: dict[RetrievalSource, float] | None = None,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        drive_file_id=uuid.uuid4(),
        filename="notes.txt",
        mime_type="text/plain",
        modified_at=datetime.now(UTC),
        chunk_index=0,
        text="Evidence text for testing.",
        score=score,
        primary_source="vector",
        source_scores=source_scores or {"vector": score},
        fusion_score=fusion_score,
    )


def test_rerank_node_populates_ranked_chunks() -> None:
    """Rerank node should transform raw merged chunks into ranked chunks."""
    settings = Settings(retrieval_top_k=2)
    raw_chunks = [
        _chunk(score=0.9, fusion_score=0.9, source_scores={"vector": 0.9, "keyword": 0.2}),
        _chunk(score=0.5, fusion_score=0.5, source_scores={"vector": 0.5, "keyword": 0.8}),
    ]
    state = create_initial_state(question="What is tensile strength?", user_id=uuid.uuid4())
    state["raw_chunks"] = raw_chunks

    update = make_rerank_node(settings=settings)(state)

    assert len(update["ranked_chunks"]) == 2
    assert update["ranked_chunks"][0].fusion_score is not None


def test_grade_evidence_node_marks_sufficient_evidence() -> None:
    """Grade node should accept strong vector evidence."""
    settings = Settings(
        evidence_min_fusion_score=0.15,
        retrieval_score_threshold=0.35,
    )
    ranked = [
        _chunk(score=0.42, fusion_score=0.42, source_scores={"vector": 0.42}),
    ]
    state = create_initial_state(question="What is tensile strength?", user_id=uuid.uuid4())
    state["ranked_chunks"] = ranked

    update = make_grade_evidence_node(settings=settings)(state)

    assert update["evidence_sufficient"] is True
    assert update["retrieval_count"] == 1
    assert "sufficient" in update["evidence_reason"].lower()


def test_grade_evidence_node_marks_insufficient_evidence() -> None:
    """Grade node should reject weak evidence with no keyword signal."""
    settings = Settings(
        evidence_min_fusion_score=0.15,
        retrieval_score_threshold=0.35,
    )
    ranked = [
        _chunk(score=0.2, fusion_score=0.2, source_scores={"vector": 0.2}),
    ]
    state = create_initial_state(question="What is tensile strength?", user_id=uuid.uuid4())
    state["ranked_chunks"] = ranked

    update = make_grade_evidence_node(settings=settings)(state)

    assert update["evidence_sufficient"] is False
    assert update["ranked_chunks"] == []
    assert update["retrieval_count"] == 0


def test_should_rewrite_skips_when_evidence_is_sufficient() -> None:
    """Sufficient evidence should route directly to answer generation."""
    state = create_initial_state(question="hello?", user_id=uuid.uuid4())
    state["evidence_sufficient"] = True
    state["rewrite_count"] = 0
    state["max_rewrite_attempts"] = 2

    assert should_rewrite(state) == "generate_answer"


def test_should_rewrite_triggers_when_attempts_remain() -> None:
    """Insufficient evidence with remaining attempts should route to rewrite."""
    state = create_initial_state(question="hello?", user_id=uuid.uuid4())
    state["evidence_sufficient"] = False
    state["rewrite_count"] = 0
    state["max_rewrite_attempts"] = 2

    assert should_rewrite(state) == "rewrite_query"


def test_should_rewrite_stops_when_attempt_cap_reached() -> None:
    """Insufficient evidence after max attempts should proceed to answer generation."""
    state = create_initial_state(question="hello?", user_id=uuid.uuid4())
    state["evidence_sufficient"] = False
    state["rewrite_count"] = 2
    state["max_rewrite_attempts"] = 2

    assert should_rewrite(state) == "generate_answer"


@pytest.mark.asyncio
async def test_graph_skips_rewrite_when_evidence_is_sufficient() -> None:
    """End-to-end graph should not rewrite when graded evidence is sufficient."""
    settings = Settings(
        agent_max_rewrite_attempts=2,
        evidence_min_fusion_score=0.15,
        retrieval_score_threshold=0.35,
        retrieval_top_k=4,
    )
    strong_chunk = _chunk(score=0.42, fusion_score=0.42, source_scores={"vector": 0.42})

    mock_vector = AsyncMock()
    mock_vector.retrieve = AsyncMock(return_value=[strong_chunk])
    mock_keyword = AsyncMock()
    mock_keyword.retrieve = AsyncMock(return_value=[])
    mock_metadata = AsyncMock()
    mock_metadata.retrieve = AsyncMock(return_value=[])

    retrievers = {
        "vector": mock_vector,
        "keyword": mock_keyword,
        "metadata": mock_metadata,
    }
    retrievers_typed: dict[RetrieverName, Retriever] = cast(
        dict[RetrieverName, Retriever],
        retrievers,
    )

    compiled = build_drive_graph(retrievers=retrievers_typed, settings=settings)
    state = create_initial_state(question="What is tensile strength?", user_id=uuid.uuid4())
    state["max_rewrite_attempts"] = settings.agent_max_rewrite_attempts

    final_state = await compiled.ainvoke(state)

    assert final_state["rewrite_count"] == 0
    assert final_state["evidence_sufficient"] is True
    assert final_state["retrieval_count"] == 1


@pytest.mark.asyncio
async def test_graph_rewrites_once_when_evidence_is_insufficient() -> None:
    """End-to-end graph should rewrite once when evidence remains insufficient."""
    settings = Settings(
        agent_max_rewrite_attempts=1,
        evidence_min_fusion_score=0.15,
        retrieval_score_threshold=0.35,
    )
    weak_chunk = _chunk(score=0.1, fusion_score=0.1, source_scores={"vector": 0.1})

    mock_vector = AsyncMock()
    mock_vector.retrieve = AsyncMock(return_value=[weak_chunk])
    mock_keyword = AsyncMock()
    mock_keyword.retrieve = AsyncMock(return_value=[])
    mock_metadata = AsyncMock()
    mock_metadata.retrieve = AsyncMock(return_value=[])

    retrievers = {
        "vector": mock_vector,
        "keyword": mock_keyword,
        "metadata": mock_metadata,
    }
    retrievers_typed: dict[RetrieverName, Retriever] = cast(
        dict[RetrieverName, Retriever],
        retrievers,
    )

    compiled = build_drive_graph(retrievers=retrievers_typed, settings=settings)
    state = create_initial_state(question="What is tensile strength?", user_id=uuid.uuid4())
    state["max_rewrite_attempts"] = settings.agent_max_rewrite_attempts

    final_state = await compiled.ainvoke(state)

    assert final_state["rewrite_count"] == 1
    assert final_state["evidence_sufficient"] is False
    assert mock_vector.retrieve.await_count == 2
