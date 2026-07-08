"""Tests for Phase 8 M4: selective routed retrieval."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.agents.drive_graph.graph import build_drive_graph
from app.agents.drive_graph.state import create_initial_state
from app.agents.drive_graph.types import RetrieverName
from app.core.config import Settings
from app.retrieval.base import Retriever
from app.retrieval.types import RetrievedChunk
from typing import cast


def _chunk(*, chunk_id: uuid.UUID, source: RetrieverName) -> RetrievedChunk:
    now = datetime.now(UTC)
    filename = f"file_{source}.txt"
    # Note: merge utilities rely on `chunk.score` + which source list the chunk came from.
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=uuid.uuid4(),
        drive_file_id=uuid.uuid4(),
        filename=filename,
        mime_type="text/plain",
        modified_at=now,
        chunk_index=0,
        text=f"{source} chunk content",
        score=0.9 if source != "vector" else 0.8,
        primary_source=source,  # type: ignore[arg-type]
        source_scores={source: 0.9},
    )


@pytest.mark.asyncio
async def test_retrieve_metadata_only_path_runs_metadata_retriever_only() -> None:
    """LIST/FILTER intent should route to metadata retriever only."""
    settings = Settings(agent_max_rewrite_attempts=0)

    metadata_chunk = _chunk(chunk_id=uuid.uuid4(), source="metadata")
    vector_chunk = _chunk(chunk_id=uuid.uuid4(), source="vector")
    keyword_chunk = _chunk(chunk_id=uuid.uuid4(), source="keyword")

    mock_vector = AsyncMock()
    mock_vector.retrieve = AsyncMock(return_value=[vector_chunk])

    mock_keyword = AsyncMock()
    mock_keyword.retrieve = AsyncMock(return_value=[keyword_chunk])

    mock_metadata = AsyncMock()
    mock_metadata.retrieve = AsyncMock(return_value=[metadata_chunk])

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
    state = create_initial_state(
        question="Show only PDFs in my Projects folder", user_id=uuid.uuid4()
    )
    state["max_rewrite_attempts"] = 0

    final_state = await compiled.ainvoke(state)

    mock_metadata.retrieve.assert_awaited_once()
    mock_keyword.retrieve.assert_not_awaited()
    mock_vector.retrieve.assert_not_awaited()

    assert len(final_state["raw_chunks"]) == 1
    assert final_state["retrieval_count"] == 0
    assert final_state["evidence_sufficient"] is False
    raw_chunks = final_state["raw_chunks"]
    assert len(raw_chunks) == 1
    assert set(raw_chunks[0].source_scores.keys()) == {"metadata"}


@pytest.mark.asyncio
async def test_retrieve_keyword_search_path_runs_keyword_and_vector_only() -> None:
    """Keyword-search intent should route to keyword+vector retrievers only."""
    settings = Settings(agent_max_rewrite_attempts=0)

    keyword_chunk = _chunk(chunk_id=uuid.uuid4(), source="keyword")
    vector_chunk = _chunk(chunk_id=uuid.uuid4(), source="vector")

    mock_vector = AsyncMock()
    mock_vector.retrieve = AsyncMock(return_value=[vector_chunk])

    mock_keyword = AsyncMock()
    mock_keyword.retrieve = AsyncMock(return_value=[keyword_chunk])

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
    state = create_initial_state(question="Files mentioning CoreChain", user_id=uuid.uuid4())
    state["max_rewrite_attempts"] = 0

    final_state = await compiled.ainvoke(state)

    mock_keyword.retrieve.assert_awaited_once()
    mock_vector.retrieve.assert_awaited_once()
    mock_metadata.retrieve.assert_not_awaited()

    assert final_state["retrieval_count"] == 2 or final_state["retrieval_count"] == 1

    raw_chunks = final_state["raw_chunks"]
    assert raw_chunks
    source_key_sets = {tuple(sorted(chunk.source_scores.keys())) for chunk in raw_chunks}
    assert source_key_sets.issubset({("keyword",), ("vector",)})
    assert ("keyword",) in source_key_sets or ("vector",) in source_key_sets
