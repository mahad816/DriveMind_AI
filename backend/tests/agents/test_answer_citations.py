"""Tests for Phase 8 M7 answer generation and citation verification."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.agents.drive_graph.graph import build_drive_graph
from app.agents.drive_graph.nodes import build_citation, make_generate_answer_node, verify_citations
from app.agents.drive_graph.state import create_initial_state
from app.agents.drive_graph.types import RetrieverName
from app.core.config import Settings
from app.llm.prompts import NO_EVIDENCE_ANSWER
from app.retrieval.base import Retriever
from app.retrieval.types import RetrievedChunk


def _chunk(*, text: str, score: float = 0.9, idx: int = 0) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        drive_file_id=uuid.uuid4(),
        filename="notes.txt",
        mime_type="text/plain",
        modified_at=datetime.now(UTC),
        chunk_index=idx,
        text=text,
        score=score,
        source_scores={"vector": score},
        fusion_score=score,
    )


@pytest.mark.asyncio
async def test_generate_answer_node_returns_no_evidence_without_ranked_chunks() -> None:
    """No ranked chunks should produce standard no-evidence answer."""
    settings = Settings(rag_max_context_chars=12000)
    chat = AsyncMock()
    chat.generate_grounded_answer = AsyncMock(return_value="unused")
    node = make_generate_answer_node(settings=settings, chat_service=chat)

    state = create_initial_state(question="What is tensile strength?", user_id=uuid.uuid4())
    update = await node(state)

    assert update["answer"] == NO_EVIDENCE_ANSWER
    assert update["citations"] == []
    chat.generate_grounded_answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_answer_node_builds_citations_from_prompt_chunks() -> None:
    """Answer node should generate answer and citations from ranked chunks."""
    settings = Settings(rag_max_context_chars=12000)
    chat = AsyncMock()
    chat.generate_grounded_answer = AsyncMock(return_value="Tensile strength appears in [1].")
    node = make_generate_answer_node(settings=settings, chat_service=chat)

    state = create_initial_state(question="What is tensile strength?", user_id=uuid.uuid4())
    state["ranked_chunks"] = [_chunk(text="Tensile strength is a materials property.")]

    update = await node(state)

    assert update["answer"] == "Tensile strength appears in [1]."
    assert len(update["citations"]) == 1
    assert update["citations"][0].filename == "notes.txt"
    assert "Tensile strength" in update["citations"][0].snippet


def test_verify_citations_strips_invalid_references_and_reindexes() -> None:
    """Verification should drop invalid references and align citation list."""
    c1 = build_citation(_chunk(text="chunk one", idx=0))
    c2 = build_citation(_chunk(text="chunk two", idx=1))
    c3 = build_citation(_chunk(text="chunk three", idx=2))
    state = create_initial_state(question="Q?", user_id=uuid.uuid4())
    state["answer"] = "Answer from [1] and [3], but not [9]."
    state["citations"] = [c1, c2, c3]

    update = verify_citations(state)

    assert "[9]" not in update["answer"]
    assert update["answer"].count("[1]") >= 1
    assert update["answer"].count("[2]") >= 1  # [3] reindexed to [2]
    assert len(update["citations"]) == 2


@pytest.mark.asyncio
async def test_graph_m7_flow_generates_answer_and_citations() -> None:
    """End-to-end graph should produce answer+citations when evidence is sufficient."""
    settings = Settings(
        agent_max_rewrite_attempts=0,
        evidence_min_fusion_score=0.1,
        retrieval_score_threshold=0.05,
        rag_max_context_chars=12000,
    )

    strong_chunk = _chunk(text="Tensile strength is in this chunk.", score=0.8)
    mock_vector = AsyncMock()
    mock_vector.retrieve = AsyncMock(return_value=[strong_chunk])
    mock_keyword = AsyncMock()
    mock_keyword.retrieve = AsyncMock(return_value=[])
    mock_metadata = AsyncMock()
    mock_metadata.retrieve = AsyncMock(return_value=[])

    chat = AsyncMock()
    chat.generate_grounded_answer = AsyncMock(return_value="Tensile strength is discussed in [1].")

    retrievers: dict[RetrieverName, Retriever] = {
        "vector": mock_vector,
        "keyword": mock_keyword,
        "metadata": mock_metadata,
    }

    compiled = build_drive_graph(
        retrievers=retrievers,
        settings=settings,
        chat_service=chat,
    )
    state = create_initial_state(question="What is tensile strength?", user_id=uuid.uuid4())
    state["max_rewrite_attempts"] = settings.agent_max_rewrite_attempts

    final_state = await compiled.ainvoke(state)

    assert final_state["answer"] == "Tensile strength is discussed in [1]."
    assert len(final_state["citations"]) == 1
    assert final_state["evidence_sufficient"] is True
    assert final_state["retrieval_count"] == 1
