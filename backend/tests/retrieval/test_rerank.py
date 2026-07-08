"""Tests for weighted fusion reranking."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.core.config import Settings
from app.retrieval.rerank import weighted_fusion_rerank
from app.retrieval.types import RetrievalSource, RetrievedChunk


def _chunk(
    *,
    source_scores: dict[RetrievalSource, float],
    modified_at: datetime,
    fusion_score: float | None = None,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        drive_file_id=uuid.uuid4(),
        filename="doc.txt",
        mime_type="text/plain",
        modified_at=modified_at,
        chunk_index=0,
        text="chunk",
        score=fusion_score or 0.0,
        source_scores=source_scores,
        fusion_score=fusion_score,
    )


def test_weighted_fusion_rerank_orders_by_weighted_normalized_score() -> None:
    now = datetime.now(UTC)
    c1 = _chunk(source_scores={"vector": 0.9, "keyword": 0.1}, modified_at=now)
    c2 = _chunk(
        source_scores={"vector": 0.5, "keyword": 0.9}, modified_at=now - timedelta(minutes=1)
    )
    c3 = _chunk(source_scores={"metadata": 0.8}, modified_at=now - timedelta(minutes=2))

    reranked = weighted_fusion_rerank(
        [c1, c2, c3],
        settings=Settings(
            retrieval_top_k=3,
            hybrid_weight_vector=0.5,
            hybrid_weight_keyword=0.3,
            hybrid_weight_metadata=0.2,
        ),
    )

    assert len(reranked) == 3
    assert reranked[0].score >= reranked[1].score >= reranked[2].score
    # c2 should lead because strong vector+keyword balance beats single-source metadata.
    assert reranked[0].source_scores.get("keyword") == 0.9


def test_weighted_fusion_rerank_respects_top_k() -> None:
    now = datetime.now(UTC)
    chunks = [
        _chunk(source_scores={"vector": 0.2 + i * 0.1}, modified_at=now - timedelta(minutes=i))
        for i in range(6)
    ]

    reranked = weighted_fusion_rerank(
        chunks,
        settings=Settings(
            retrieval_top_k=4,
            hybrid_weight_vector=0.5,
            hybrid_weight_keyword=0.3,
            hybrid_weight_metadata=0.2,
        ),
    )
    assert len(reranked) == 4


def test_weighted_fusion_rerank_falls_back_to_fusion_score() -> None:
    now = datetime.now(UTC)
    c1 = _chunk(source_scores={}, modified_at=now, fusion_score=0.12)
    c2 = _chunk(source_scores={}, modified_at=now - timedelta(minutes=1), fusion_score=0.05)

    reranked = weighted_fusion_rerank(
        [c1, c2],
        settings=Settings(retrieval_top_k=2),
    )

    assert reranked[0].score == 0.12
    assert reranked[1].score == 0.05
