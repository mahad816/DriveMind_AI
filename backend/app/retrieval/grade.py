"""Evidence grading for hybrid retrieval results."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings, get_settings
from app.retrieval.types import RetrievedChunk


@dataclass(frozen=True)
class EvidenceGrade:
    """Result of grading retrieval evidence quality."""

    sufficient: bool
    reason: str
    chunks: list[RetrievedChunk]


def grade_evidence(
    chunks: list[RetrievedChunk],
    settings: Settings | None = None,
) -> EvidenceGrade:
    """Grade whether retrieved chunks provide sufficient evidence for answering."""
    resolved = settings or get_settings()
    if not chunks:
        return EvidenceGrade(
            sufficient=False,
            reason="No retrieval evidence available.",
            chunks=[],
        )

    top_score = chunks[0].fusion_score if chunks[0].fusion_score is not None else chunks[0].score
    if top_score < resolved.evidence_min_fusion_score:
        return EvidenceGrade(
            sufficient=False,
            reason="Top fused evidence score below minimum threshold.",
            chunks=[],
        )

    has_keyword_signal = any(chunk.source_scores.get("keyword", 0.0) > 0.0 for chunk in chunks)
    vector_scores = [chunk.source_scores.get("vector", 0.0) for chunk in chunks]
    if (
        vector_scores
        and max(vector_scores) < resolved.retrieval_score_threshold
        and not has_keyword_signal
    ):
        return EvidenceGrade(
            sufficient=False,
            reason="Vector evidence is weak and keyword evidence is absent.",
            chunks=[],
        )

    filtered = [chunk for chunk in chunks if (chunk.fusion_score or chunk.score) >= 0.0]
    return EvidenceGrade(
        sufficient=True,
        reason="Evidence is sufficient for grounded generation.",
        chunks=filtered,
    )
