"""Focused tests for immutable evaluation trace snapshots."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
import uuid

import pytest

from app.evaluation.trace import EvalTraceCollector, snapshot_candidates
from app.retrieval.types import RetrievedChunk


def _chunk(*, score: float, text: str = "evidence") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        drive_file_id=uuid.uuid4(),
        filename="notes.txt",
        mime_type="text/plain",
        modified_at=datetime.now(UTC),
        chunk_index=0,
        text=text,
        score=score,
        source_scores={"vector": score},
        fusion_score=score,
    )


def test_candidate_snapshots_are_immutable_stage_values() -> None:
    chunk = _chunk(score=0.02)
    merged = snapshot_candidates([chunk])
    reranked_chunk = replace(chunk, score=0.5, fusion_score=0.5)
    reranked = snapshot_candidates([reranked_chunk])

    assert merged[0].score == 0.02
    assert reranked[0].score == 0.5
    with pytest.raises(FrozenInstanceError):
        merged[0].score = 1.0  # type: ignore[misc]


def test_collector_is_single_use() -> None:
    collector = EvalTraceCollector()
    collector.start("question")

    with pytest.raises(RuntimeError, match="single-use"):
        collector.start("another question")
