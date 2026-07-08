"""Tests for hybrid retrieval merge logic."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.core.config import Settings
from app.retrieval.merge import reciprocal_rank_fusion_merge
from app.retrieval.types import RetrievedChunk


def _chunk(
    *,
    chunk_id: uuid.UUID,
    score: float,
    modified_at: datetime,
    filename: str = "doc.txt",
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=uuid.uuid4(),
        drive_file_id=uuid.uuid4(),
        filename=filename,
        mime_type="text/plain",
        modified_at=modified_at,
        chunk_index=0,
        text="chunk text",
        score=score,
    )


def test_rrf_merge_deduplicates_and_accumulates_source_scores() -> None:
    shared_id = uuid.uuid4()
    unique_vector = uuid.uuid4()
    unique_keyword = uuid.uuid4()
    now = datetime.now(UTC)

    vector_chunks = [
        _chunk(chunk_id=shared_id, score=0.9, modified_at=now),
        _chunk(chunk_id=unique_vector, score=0.7, modified_at=now - timedelta(minutes=1)),
    ]
    keyword_chunks = [
        _chunk(chunk_id=shared_id, score=0.8, modified_at=now),
        _chunk(chunk_id=unique_keyword, score=0.6, modified_at=now - timedelta(minutes=2)),
    ]

    merged = reciprocal_rank_fusion_merge(
        {"vector": vector_chunks, "keyword": keyword_chunks},
        settings=Settings(
            retrieval_candidate_k=8,
            hybrid_rrf_k=10,
            hybrid_weight_vector=0.5,
            hybrid_weight_keyword=0.3,
            hybrid_weight_metadata=0.2,
        ),
    )

    assert len(merged) == 3
    assert merged[0].chunk_id == shared_id
    assert merged[0].fusion_score is not None
    assert merged[0].source_scores["vector"] == 0.9
    assert merged[0].source_scores["keyword"] == 0.8
    assert merged[0].primary_source == "vector"


def test_rrf_merge_orders_by_fusion_score() -> None:
    now = datetime.now(UTC)
    top = _chunk(chunk_id=uuid.uuid4(), score=0.95, modified_at=now)
    middle = _chunk(chunk_id=uuid.uuid4(), score=0.8, modified_at=now - timedelta(minutes=1))
    low = _chunk(chunk_id=uuid.uuid4(), score=0.7, modified_at=now - timedelta(minutes=2))

    merged = reciprocal_rank_fusion_merge(
        {"vector": [top, middle, low]},
        settings=Settings(
            retrieval_candidate_k=8,
            hybrid_rrf_k=20,
            hybrid_weight_vector=0.5,
            hybrid_weight_keyword=0.3,
            hybrid_weight_metadata=0.2,
        ),
    )

    assert [item.chunk_id for item in merged] == [top.chunk_id, middle.chunk_id, low.chunk_id]
    assert merged[0].score > merged[1].score > merged[2].score


def test_rrf_merge_respects_candidate_result_cap() -> None:
    now = datetime.now(UTC)
    chunks = [
        _chunk(chunk_id=uuid.uuid4(), score=0.5, modified_at=now - timedelta(minutes=i))
        for i in range(10)
    ]
    merged = reciprocal_rank_fusion_merge(
        {"vector": chunks},
        settings=Settings(
            retrieval_candidate_k=3,
            hybrid_rrf_k=10,
            hybrid_weight_vector=0.5,
            hybrid_weight_keyword=0.3,
            hybrid_weight_metadata=0.2,
        ),
    )

    assert len(merged) == 6
