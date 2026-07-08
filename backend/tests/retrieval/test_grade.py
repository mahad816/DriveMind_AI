"""Tests for evidence grading rules."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.core.config import Settings
from app.retrieval.grade import grade_evidence
from app.retrieval.types import RetrievedChunk


def _chunk(
    *,
    score: float,
    fusion_score: float | None = None,
    source_scores: dict[str, float] | None = None,
    modified_at: datetime | None = None,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        drive_file_id=uuid.uuid4(),
        filename="doc.txt",
        mime_type="text/plain",
        modified_at=modified_at or datetime.now(UTC),
        chunk_index=0,
        text="chunk",
        score=score,
        source_scores=(source_scores or {}),  # type: ignore[arg-type]
        fusion_score=fusion_score,
    )


def test_grade_evidence_rejects_empty_results() -> None:
    grade = grade_evidence([], settings=Settings(evidence_min_fusion_score=0.15))
    assert grade.sufficient is False
    assert grade.chunks == []


def test_grade_evidence_rejects_below_fusion_threshold() -> None:
    chunks = [_chunk(score=0.1, fusion_score=0.1, source_scores={"vector": 0.2})]
    grade = grade_evidence(
        chunks,
        settings=Settings(
            evidence_min_fusion_score=0.15,
            retrieval_score_threshold=0.35,
        ),
    )
    assert grade.sufficient is False
    assert "below minimum threshold" in grade.reason


def test_grade_evidence_rejects_weak_vector_without_keyword() -> None:
    now = datetime.now(UTC)
    chunks = [
        _chunk(
            score=0.2,
            fusion_score=0.2,
            source_scores={"vector": 0.2},
            modified_at=now,
        ),
        _chunk(
            score=0.18,
            fusion_score=0.18,
            source_scores={"vector": 0.25},
            modified_at=now - timedelta(minutes=1),
        ),
    ]
    grade = grade_evidence(
        chunks,
        settings=Settings(
            evidence_min_fusion_score=0.15,
            retrieval_score_threshold=0.35,
        ),
    )
    assert grade.sufficient is False
    assert "Vector evidence is weak" in grade.reason


def test_grade_evidence_accepts_with_keyword_signal() -> None:
    chunks = [
        _chunk(
            score=0.2,
            fusion_score=0.2,
            source_scores={"vector": 0.2, "keyword": 0.05},
        )
    ]
    grade = grade_evidence(
        chunks,
        settings=Settings(
            evidence_min_fusion_score=0.15,
            retrieval_score_threshold=0.35,
        ),
    )
    assert grade.sufficient is True
    assert len(grade.chunks) == 1
