"""Tests for weighted fusion reranking."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.core.config import Settings
from dataclasses import replace

from app.retrieval.rerank import limit_chunks_per_file, weighted_fusion_rerank
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


# ---- per-file limit --------------------------------------------------------------------------------


def _ranked(*files: str, per_file: int = 1) -> list[RetrievedChunk]:
    """Chunks already in rank order; the file name stands for the file id."""
    ids = {name: uuid.uuid4() for name in dict.fromkeys(files)}
    now = datetime.now(UTC)
    out = []
    for position, name in enumerate(files):
        chunk = _chunk(source_scores={"vector": 1.0 - position / 100}, modified_at=now)
        out.append(replace(chunk, drive_file_id=ids[name], filename=name, chunk_index=position))
    return out


def names(chunks: list[RetrievedChunk]) -> list[str]:
    return [c.filename for c in chunks]


def test_limit_off_returns_the_plain_top_k() -> None:
    ranked = _ranked("a", "a", "a", "a", "b")
    assert names(limit_chunks_per_file(ranked, 4, 0)) == ["a", "a", "a", "a"]


def test_limit_lets_other_files_in_and_keeps_rank_order() -> None:
    ranked = _ranked("a", "a", "a", "a", "a", "b", "c", "a")
    result = limit_chunks_per_file(ranked, 4, 2)
    assert names(result) == ["a", "a", "b", "c"]  # a's later chunks gave way to b and c
    assert [c.chunk_index for c in result] == [0, 1, 5, 6]


def test_limit_fills_a_remaining_slot_with_the_best_surplus_chunk() -> None:
    ranked = _ranked("a", "a", "a", "a", "a", "b", "c", "a")
    result = limit_chunks_per_file(ranked, 5, 2)  # only 4 chunks fit under the limit
    assert [c.chunk_index for c in result] == [0, 1, 2, 5, 6]  # rank 3 (an "a") takes slot 5


def test_limit_is_soft_and_refills_when_no_other_file_has_candidates() -> None:
    ranked = _ranked("a", "a", "a", "a", "a", "a")
    assert names(limit_chunks_per_file(ranked, 4, 2)) == ["a", "a", "a", "a"]


def test_limit_refills_with_the_best_surplus_chunks_first() -> None:
    ranked = _ranked("a", "a", "a", "a", "b")
    result = limit_chunks_per_file(ranked, 4, 2)
    assert names(result) == ["a", "a", "a", "b"]  # a's third chunk (rank 3) beats nothing else
    assert [c.chunk_index for c in result] == [0, 1, 2, 4]


def test_limit_handles_short_and_empty_input() -> None:
    assert limit_chunks_per_file([], 8, 3) == []
    ranked = _ranked("a", "b")
    assert names(limit_chunks_per_file(ranked, 8, 3)) == ["a", "b"]


def test_rerank_applies_the_limit_after_scoring() -> None:
    now = datetime.now(UTC)
    shared = uuid.uuid4()
    strong = [
        replace(
            _chunk(source_scores={"vector": 0.9 - i / 100}, modified_at=now), drive_file_id=shared
        )
        for i in range(4)
    ]
    other = _chunk(source_scores={"vector": 0.5}, modified_at=now)
    settings = Settings(retrieval_top_k=3)

    unlimited = weighted_fusion_rerank([*strong, other], settings, max_per_file=0)
    assert all(c.drive_file_id == shared for c in unlimited)  # the long file fills every slot

    limited = weighted_fusion_rerank([*strong, other], settings, max_per_file=2)
    assert len(limited) == 3
    assert sum(c.drive_file_id == shared for c in limited) == 2
    assert other.chunk_id in {c.chunk_id for c in limited}
