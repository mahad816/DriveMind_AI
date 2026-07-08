"""Hybrid retrieval merge utilities (RRF + dedupe)."""

from __future__ import annotations

from dataclasses import replace
import uuid

from app.core.config import Settings, get_settings
from app.retrieval.types import RetrievalSource, RetrievedChunk


def reciprocal_rank_fusion_merge(
    chunks_by_source: dict[RetrievalSource, list[RetrievedChunk]],
    settings: Settings | None = None,
) -> list[RetrievedChunk]:
    """Merge ranked source lists with reciprocal rank fusion and deduplication."""
    resolved = settings or get_settings()
    weighted_scores: dict[RetrievalSource, float] = {
        "vector": resolved.hybrid_weight_vector,
        "keyword": resolved.hybrid_weight_keyword,
        "metadata": resolved.hybrid_weight_metadata,
        "hybrid": 0.0,
    }
    rrf_k = max(resolved.hybrid_rrf_k, 1)
    merged: dict[uuid.UUID, RetrievedChunk] = {}
    fusion_scores: dict[uuid.UUID, float] = {}
    source_scores: dict[uuid.UUID, dict[RetrievalSource, float]] = {}

    for source, chunks in chunks_by_source.items():
        source_weight = weighted_scores.get(source, 0.0)
        if source_weight <= 0.0:
            continue
        for rank, chunk in enumerate(chunks, start=1):
            chunk_id = chunk.chunk_id
            rrf_score = source_weight / (rrf_k + rank)
            fusion_scores[chunk_id] = fusion_scores.get(chunk_id, 0.0) + rrf_score
            per_source = source_scores.setdefault(chunk_id, {})
            per_source[source] = max(per_source.get(source, 0.0), float(chunk.score))
            if chunk_id not in merged:
                merged[chunk_id] = chunk

    result: list[RetrievedChunk] = []
    for chunk_id, chunk in merged.items():
        per_source = source_scores.get(chunk_id, {})
        primary_source = _primary_source(per_source, default=chunk.primary_source)
        fusion_score = fusion_scores.get(chunk_id, 0.0)
        result.append(
            replace(
                chunk,
                primary_source=primary_source,
                source_scores=per_source,
                fusion_score=fusion_score,
                score=fusion_score,
            )
        )

    result.sort(
        key=lambda item: (
            item.fusion_score if item.fusion_score is not None else 0.0,
            item.modified_at,
        ),
        reverse=True,
    )
    max_results = max(resolved.retrieval_candidate_k * 2, resolved.retrieval_candidate_k)
    return result[:max_results]


def _primary_source(
    source_scores: dict[RetrievalSource, float],
    *,
    default: RetrievalSource,
) -> RetrievalSource:
    if not source_scores:
        return default
    return max(source_scores.items(), key=lambda item: item[1])[0]
