"""Round-robin combination of two ranked chunk lists (hybrid retrieval C2)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.retrieval.round_robin import round_robin_merge
from app.retrieval.types import RetrievedChunk

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def chunk(n: int, *, score: float = 1.0) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.UUID(int=n),
        document_id=uuid.UUID(int=1000 + n),
        drive_file_id=uuid.UUID(int=2000 + n),
        filename=f"f{n}.txt",
        mime_type="text/plain",
        modified_at=NOW,
        chunk_index=0,
        text=f"text {n}",
        score=score,
        source_scores={"vector": score},
        fusion_score=score,
    )


def ids(chunks: list[RetrievedChunk]) -> list[int]:
    return [c.chunk_id.int for c in chunks]


def test_alternates_original_first_then_model() -> None:
    merged = round_robin_merge(
        [chunk(1), chunk(2), chunk(3)], [chunk(11), chunk(12), chunk(13)], limit=8
    )
    assert ids(merged) == [1, 11, 2, 12, 3, 13]


def test_duplicate_chunk_is_taken_once_and_the_turn_moves_to_the_next_unseen() -> None:
    # model rank 1 repeats original rank 1: it is skipped, the model list gives its next unseen chunk.
    merged = round_robin_merge([chunk(1), chunk(2)], [chunk(1), chunk(11), chunk(12)], limit=8)
    assert ids(merged) == [1, 11, 2, 12]
    assert len(set(ids(merged))) == len(merged)


def test_duplicates_never_reduce_the_result_below_the_unique_candidates_available() -> None:
    original = [chunk(n) for n in (1, 2, 3, 4, 5, 6, 7, 8)]
    model = [chunk(n) for n in (8, 7, 6, 5, 4, 3, 2, 1, 9, 10)]
    merged = round_robin_merge(original, model, limit=8)
    assert len(merged) == 8
    assert len(set(ids(merged))) == 8


def test_stops_at_limit() -> None:
    merged = round_robin_merge(
        [chunk(n) for n in range(1, 9)], [chunk(n) for n in range(11, 19)], limit=8
    )
    assert ids(merged) == [1, 11, 2, 12, 3, 13, 4, 14]


def test_original_list_empty_returns_model_list_in_order() -> None:
    assert ids(round_robin_merge([], [chunk(11), chunk(12)], limit=8)) == [11, 12]


def test_model_list_empty_returns_original_list_in_order() -> None:
    assert ids(round_robin_merge([chunk(1), chunk(2)], [], limit=8)) == [1, 2]


def test_both_empty_is_empty() -> None:
    assert round_robin_merge([], [], limit=8) == []


def test_one_list_exhausted_early_the_other_continues() -> None:
    merged = round_robin_merge([chunk(1)], [chunk(11), chunk(12), chunk(13)], limit=8)
    assert ids(merged) == [1, 11, 12, 13]


def test_fewer_than_limit_available() -> None:
    merged = round_robin_merge([chunk(1), chunk(2)], [chunk(11)], limit=8)
    assert ids(merged) == [1, 11, 2]


def test_deterministic_and_does_not_mutate_inputs() -> None:
    original = [chunk(1), chunk(2)]
    model = [chunk(2), chunk(3)]
    first = round_robin_merge(original, model, limit=8)
    second = round_robin_merge(original, model, limit=8)
    assert ids(first) == ids(second) == [1, 2, 3]
    assert ids(original) == [1, 2] and ids(model) == [2, 3]


def test_keeps_the_chunk_object_and_its_scores_unchanged() -> None:
    first = chunk(1, score=0.9)
    merged = round_robin_merge([first], [chunk(11, score=0.4)], limit=8)
    assert merged[0] is first
    assert merged[0].source_scores == {"vector": 0.9}
    assert merged[0].fusion_score == 0.9


def test_a_duplicate_keeps_the_copy_from_the_list_that_reached_it_first() -> None:
    from_original = chunk(1, score=0.9)
    from_model = chunk(1, score=0.2)
    merged = round_robin_merge([from_original], [from_model], limit=8)
    assert merged == [from_original]
    assert merged[0].score == 0.9


def test_non_positive_limit_returns_nothing() -> None:
    assert round_robin_merge([chunk(1)], [chunk(2)], limit=0) == []
