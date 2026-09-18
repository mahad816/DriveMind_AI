"""Integration tests for end-to-end DriveGraph orchestration."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock

import pytest

from app.agents.drive_graph.graph import build_drive_graph
from app.agents.drive_graph.state import create_initial_state
from app.agents.drive_graph.types import RetrieverName
from app.core.config import Settings
from app.evaluation.trace import EvalTraceCollector, TraceOutcome
from app.llm.prompts import NO_EVIDENCE_ANSWER
from app.retrieval.base import Retriever
from app.retrieval.types import RetrievedChunk


def _chunk(
    *,
    text: str,
    score: float,
    source: RetrieverName,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        drive_file_id=uuid.uuid4(),
        filename=f"{source}_notes.txt",
        mime_type="text/plain",
        modified_at=datetime.now(UTC),
        chunk_index=0,
        text=text,
        score=score,
        primary_source=source,  # type: ignore[arg-type]
        source_scores={source: score},
        fusion_score=score,
    )


@pytest.mark.asyncio
async def test_graph_full_path_generates_answer_after_single_rewrite() -> None:
    """Graph should rewrite once, retrieve again, then produce answer with citations."""
    settings = Settings(
        agent_max_rewrite_attempts=1,
        evidence_min_fusion_score=0.15,
        retrieval_score_threshold=0.35,
        rag_max_context_chars=12000,
    )

    weak = _chunk(text="weak chunk", score=0.1, source="vector")
    strong = _chunk(text="strong chunk with tensile evidence", score=0.8, source="vector")

    # First retrieve call -> weak evidence; second call -> strong evidence.
    mock_vector = AsyncMock()
    mock_vector.retrieve = AsyncMock(side_effect=[[weak], [strong]])
    mock_keyword = AsyncMock()
    mock_keyword.retrieve = AsyncMock(return_value=[])
    mock_metadata = AsyncMock()
    mock_metadata.retrieve = AsyncMock(return_value=[])

    chat = AsyncMock()
    chat.generate_grounded_answer = AsyncMock(return_value="Answer based on [1].")
    rewrite_fn = AsyncMock(return_value="refined tensile query")

    retrievers = {
        "vector": mock_vector,
        "keyword": mock_keyword,
        "metadata": mock_metadata,
    }
    retrievers_typed: dict[RetrieverName, Retriever] = cast(
        dict[RetrieverName, Retriever],
        retrievers,
    )

    compiled = build_drive_graph(
        retrievers=retrievers_typed,
        settings=settings,
        rewrite_fn=rewrite_fn,
        chat_service=chat,
    )
    state = create_initial_state(question="What is tensile strength?", user_id=uuid.uuid4())
    state["max_rewrite_attempts"] = settings.agent_max_rewrite_attempts

    final_state = await compiled.ainvoke(state)

    assert final_state["rewrite_count"] == 1
    assert final_state["evidence_sufficient"] is True
    assert final_state["answer"] == "Answer based on [1]."
    assert len(final_state["citations"]) == 1
    assert mock_vector.retrieve.await_count == 2
    rewrite_fn.assert_awaited_once()


@pytest.mark.asyncio
async def test_graph_verifies_and_reindexes_citations_integration() -> None:
    """Verification step should strip bad refs and normalize citation numbering."""
    settings = Settings(
        agent_max_rewrite_attempts=0,
        evidence_min_fusion_score=0.1,
        retrieval_score_threshold=0.05,
    )
    c1 = _chunk(text="first chunk", score=0.8, source="vector")
    c2 = _chunk(text="second chunk", score=0.7, source="keyword")
    c3 = _chunk(text="third chunk", score=0.6, source="vector")

    mock_vector = AsyncMock()
    mock_vector.retrieve = AsyncMock(return_value=[c1, c3])
    mock_keyword = AsyncMock()
    mock_keyword.retrieve = AsyncMock(return_value=[c2])
    mock_metadata = AsyncMock()
    mock_metadata.retrieve = AsyncMock(return_value=[])

    chat = AsyncMock()
    chat.generate_grounded_answer = AsyncMock(
        return_value="Compare [3] with [1], and ignore bad [9]."
    )

    retrievers = {
        "vector": mock_vector,
        "keyword": mock_keyword,
        "metadata": mock_metadata,
    }
    retrievers_typed: dict[RetrieverName, Retriever] = cast(
        dict[RetrieverName, Retriever],
        retrievers,
    )

    compiled = build_drive_graph(
        retrievers=retrievers_typed,
        settings=settings,
        chat_service=chat,
    )
    state = create_initial_state(question="Files mentioning CoreChain", user_id=uuid.uuid4())
    state["max_rewrite_attempts"] = 0

    final_state = await compiled.ainvoke(state)

    assert final_state["answer"] == "Compare [1] with [2], and ignore bad."
    assert len(final_state["citations"]) == 2
    assert len(final_state["ranked_chunks"]) == 3
    assert final_state["citations"][0].chunk_id == final_state["ranked_chunks"][2].chunk_id
    assert final_state["citations"][1].chunk_id == final_state["ranked_chunks"][0].chunk_id


@pytest.mark.asyncio
async def test_graph_returns_no_citations_when_answer_has_no_markers() -> None:
    settings = Settings(
        agent_max_rewrite_attempts=0,
        evidence_min_fusion_score=0.1,
        retrieval_score_threshold=0.05,
    )
    chunk = _chunk(text="grounded evidence", score=0.8, source="vector")
    mock_vector = AsyncMock()
    mock_vector.retrieve = AsyncMock(return_value=[chunk])
    mock_keyword = AsyncMock()
    mock_keyword.retrieve = AsyncMock(return_value=[])
    mock_metadata = AsyncMock()
    mock_metadata.retrieve = AsyncMock(return_value=[])
    chat = AsyncMock()
    chat.generate_grounded_answer = AsyncMock(return_value="Grounded answer without markers.")
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
    state = create_initial_state(question="What is the evidence?", user_id=uuid.uuid4())
    state["max_rewrite_attempts"] = 0

    final_state = await compiled.ainvoke(state)

    assert final_state["answer"] == "Grounded answer without markers."
    assert final_state["citations"] == []


@pytest.mark.asyncio
async def test_graph_does_not_infer_retrieval_abstention_from_answer_text() -> None:
    settings = Settings(
        agent_max_rewrite_attempts=0,
        evidence_min_fusion_score=0.1,
        retrieval_score_threshold=0.05,
    )
    chunk = _chunk(text="sufficient grounded evidence", score=0.8, source="vector")
    vector = AsyncMock()
    vector.retrieve = AsyncMock(return_value=[chunk])
    keyword = AsyncMock()
    keyword.retrieve = AsyncMock(return_value=[])
    metadata = AsyncMock()
    metadata.retrieve = AsyncMock(return_value=[])
    chat = AsyncMock()
    chat.generate_grounded_answer = AsyncMock(return_value=NO_EVIDENCE_ANSWER)
    retrievers: dict[RetrieverName, Retriever] = {
        "vector": vector,
        "keyword": keyword,
        "metadata": metadata,
    }
    collector = EvalTraceCollector()
    collector.start("What is the evidence?")
    compiled = build_drive_graph(
        retrievers=retrievers,
        settings=settings,
        chat_service=chat,
        trace=collector,
    )
    state = create_initial_state(question="What is the evidence?", user_id=uuid.uuid4())
    state["max_rewrite_attempts"] = 0

    final_state = await compiled.ainvoke(state)

    assert final_state["answer"] == NO_EVIDENCE_ANSWER
    assert final_state["evidence_sufficient"] is True
    assert final_state["ranked_chunks"]
    assert collector.trace.outcome is TraceOutcome.ANSWERED
    assert collector.trace.abstention_reason is None


@pytest.mark.asyncio
async def test_graph_trace_preserves_plan_rewrite_and_separate_attempts() -> None:
    settings = Settings(
        agent_max_rewrite_attempts=1,
        evidence_min_fusion_score=0.15,
        retrieval_score_threshold=0.35,
        rag_max_context_chars=12000,
    )
    weak = _chunk(text="weak chunk", score=0.1, source="vector")
    strong = _chunk(text="strong tensile evidence", score=0.8, source="vector")
    vector = AsyncMock()
    vector.retrieve = AsyncMock(side_effect=[[weak], [strong]])
    keyword = AsyncMock()
    keyword.retrieve = AsyncMock(return_value=[])
    metadata = AsyncMock()
    metadata.retrieve = AsyncMock(return_value=[])
    chat = AsyncMock()
    chat.generate_grounded_answer = AsyncMock(return_value="Answer [1].")
    rewrite_fn = AsyncMock(return_value="refined tensile query")
    retrievers: dict[RetrieverName, Retriever] = {
        "vector": vector,
        "keyword": keyword,
        "metadata": metadata,
    }
    collector = EvalTraceCollector()
    collector.start("What is tensile strength?")
    compiled = build_drive_graph(
        retrievers=retrievers,
        settings=settings,
        rewrite_fn=rewrite_fn,
        chat_service=chat,
        trace=collector,
    )
    state = create_initial_state(question="What is tensile strength?", user_id=uuid.uuid4())
    state["max_rewrite_attempts"] = 1

    final_state = await compiled.ainvoke(state)

    assert final_state["answer"] == "Answer [1]."
    assert collector.trace.graph_intent == "semantic_question"
    assert collector.trace.retrieval_plan == ("vector", "keyword")
    assert len(collector.trace.attempts) == 2
    assert collector.trace.attempts[0].working_query == "What is tensile strength?"
    assert collector.trace.attempts[1].working_query == "refined tensile query"
    assert collector.trace.attempts[0].reranked_candidates[0].chunk_id == weak.chunk_id
    assert collector.trace.attempts[1].reranked_candidates[0].chunk_id == strong.chunk_id
    assert collector.trace.rewrites[0].source == "custom"
    assert collector.trace.rewrites[0].output_query == "refined tensile query"
    assert collector.trace.raw_answer == "Answer [1]."
    assert collector.trace.final_answer == "Answer [1]."
    assert collector.trace.prompt_chunks[0].chunk_id == strong.chunk_id
