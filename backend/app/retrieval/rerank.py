"""Weighted fusion reranking for merged retrieval candidates."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace

from app.core.config import Settings, get_settings
from app.retrieval.filename_targets import chunk_matches_filename_target, extract_filename_targets
from app.retrieval.types import RetrievedChunk


def weighted_fusion_rerank(
    candidates: list[RetrievedChunk],
    settings: Settings | None = None,
    *,
    question: str | None = None,
    max_per_file: int = 0,
) -> list[RetrievedChunk]:
    """Rerank merged candidates using normalized per-source weighted scores.

    ``max_per_file`` > 0 limits how many of the returned chunks may come from one file, so a long
    document cannot fill every slot; 0 returns the plain top ``retrieval_top_k``.
    """
    if not candidates:
        return []

    resolved = settings or get_settings()
    source_weights = {
        "vector": resolved.hybrid_weight_vector,
        "keyword": resolved.hybrid_weight_keyword,
        "metadata": resolved.hybrid_weight_metadata,
    }
    maxima = _max_source_scores(candidates)
    filename_targets = extract_filename_targets(question) if question else []

    reranked: list[RetrievedChunk] = []
    for chunk in candidates:
        weighted_score = 0.0
        for source, source_score in chunk.source_scores.items():
            max_score = maxima.get(source, 0.0)
            if max_score <= 0.0:
                continue
            normalized_score = source_score / max_score
            weighted_score += source_weights.get(source, 0.0) * normalized_score

        if weighted_score <= 0.0 and chunk.fusion_score is not None:
            weighted_score = chunk.fusion_score

        reranked.append(
            replace(
                chunk,
                score=weighted_score,
                fusion_score=weighted_score,
            )
        )

    reranked.sort(
        key=lambda item: (
            _filename_priority(item, filename_targets),
            item.fusion_score if item.fusion_score is not None else 0.0,
            item.modified_at,
        ),
        reverse=True,
    )
    return limit_chunks_per_file(reranked, resolved.retrieval_top_k, max_per_file)


def limit_chunks_per_file(
    ranked: list[RetrievedChunk], top_k: int, max_per_file: int
) -> list[RetrievedChunk]:
    """The best ``top_k`` chunks with at most ``max_per_file`` per file, in their original order.

    A soft limit: if too few other files have candidates, the best chunks over the limit refill
    the remaining slots, so a question that really lives in one long file still gets its chunks.
    """
    if max_per_file <= 0:
        return ranked[:top_k]
    kept: list[RetrievedChunk] = []
    overflow: list[RetrievedChunk] = []
    taken: Counter[object] = Counter()
    for chunk in ranked:
        if len(kept) >= top_k:
            break
        if taken[chunk.drive_file_id] < max_per_file:
            kept.append(chunk)
            taken[chunk.drive_file_id] += 1
        else:
            overflow.append(chunk)
    chosen = kept + overflow[: top_k - len(kept)]
    position = {id(chunk): index for index, chunk in enumerate(ranked)}
    return sorted(chosen, key=lambda chunk: position[id(chunk)])


def _filename_priority(chunk: RetrievedChunk, targets: list[str]) -> int:
    """Return 1 when the chunk belongs to a file named in the question, else 0."""
    if not targets:
        return 0
    return 1 if chunk_matches_filename_target(chunk, targets) else 0


def _max_source_scores(candidates: list[RetrievedChunk]) -> dict[str, float]:
    maxima: dict[str, float] = {"vector": 0.0, "keyword": 0.0, "metadata": 0.0}
    for chunk in candidates:
        for source, score in chunk.source_scores.items():
            maxima[source] = max(maxima.get(source, 0.0), score)
    return maxima
