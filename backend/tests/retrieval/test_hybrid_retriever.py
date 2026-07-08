"""Tests for hybrid retrieval orchestration."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.types import RetrievalSource, RetrievedChunk


def _chunk(*, score: float, source: RetrievalSource) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        drive_file_id=uuid.uuid4(),
        filename="doc.txt",
        mime_type="text/plain",
        modified_at=datetime.now(UTC),
        chunk_index=0,
        text="chunk text",
        score=score,
        primary_source=source,
        source_scores={source: score},
    )


@pytest.mark.asyncio
async def test_hybrid_retriever_runs_sources_and_returns_graded_chunks() -> None:
    vector = AsyncMock()
    keyword = AsyncMock()
    metadata = AsyncMock()
    vector.retrieve = AsyncMock(return_value=[_chunk(score=0.9, source="vector")])
    keyword.retrieve = AsyncMock(return_value=[_chunk(score=0.7, source="keyword")])
    metadata.retrieve = AsyncMock(return_value=[])

    retriever = HybridRetriever(
        db=AsyncMock(),
        settings=Settings(
            retrieval_candidate_k=8,
            retrieval_top_k=4,
            hybrid_rrf_k=20,
            hybrid_weight_vector=0.5,
            hybrid_weight_keyword=0.3,
            hybrid_weight_metadata=0.2,
            evidence_min_fusion_score=0.01,
            retrieval_score_threshold=0.35,
        ),
        vector_retriever=vector,
        keyword_retriever=keyword,
        metadata_retriever=metadata,
    )

    chunks = await retriever.retrieve("latest pdf")

    assert len(chunks) >= 1
    vector.retrieve.assert_awaited_once()
    keyword.retrieve.assert_awaited_once()
    metadata.retrieve.assert_awaited_once()


@pytest.mark.asyncio
async def test_hybrid_retriever_returns_insufficient_for_empty_question() -> None:
    retriever = HybridRetriever(
        db=AsyncMock(),
        settings=Settings(),
        vector_retriever=AsyncMock(),
        keyword_retriever=AsyncMock(),
        metadata_retriever=AsyncMock(),
    )
    evidence = await retriever.retrieve_with_grade("   ")
    assert evidence.sufficient is False
    assert evidence.chunks == []
