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


# ---- soft per-file cap during the merge (C2-cap3, the strategy selected on 2026-11-24) ----------------------


import random  # noqa: E402
from collections import Counter  # noqa: E402


def filed(n: int, file_no: int) -> RetrievedChunk:
    base = chunk(n)
    return RetrievedChunk(
        chunk_id=base.chunk_id,
        document_id=base.document_id,
        drive_file_id=uuid.UUID(int=5000 + file_no),
        filename=f"file{file_no}.txt",
        mime_type=base.mime_type,
        modified_at=NOW,
        chunk_index=n,
        text=base.text,
        score=base.score,
        source_scores=base.source_scores,
        fusion_score=base.fusion_score,
    )


def reference_cap(original, model, limit, cap):  # type: ignore[no-untyped-def]
    """Independent re-statement of the reviewed experiment strategy (evidence folder, strategies.py)."""
    taken, seen, deferred = [], set(), []
    per_file: Counter[uuid.UUID] = Counter()
    lists, cursors, turn = (original, model), [0, 0], 0
    while len(taken) < limit and (cursors[0] < len(original) or cursors[1] < len(model)):
        src = lists[turn]
        while cursors[turn] < len(src):
            cand = src[cursors[turn]]
            cursors[turn] += 1
            if cand.chunk_id in seen:
                continue
            seen.add(cand.chunk_id)
            if per_file[cand.drive_file_id] >= cap:
                deferred.append(cand)
                continue
            per_file[cand.drive_file_id] += 1
            taken.append(cand)
            break
        turn = 1 - turn
    for cand in deferred:
        if len(taken) >= limit:
            break
        taken.append(cand)
    return taken


def test_default_cap_is_off_and_matches_the_uncapped_merge() -> None:
    original = [filed(n, 1) for n in range(1, 6)]
    model = [filed(n, 1) for n in range(11, 16)]
    assert ids(round_robin_merge(original, model, limit=8)) == ids(
        round_robin_merge(original, model, limit=8, max_per_file=0)
    )
    assert (
        Counter(c.drive_file_id for c in round_robin_merge(original, model, limit=8)).most_common(
            1
        )[0][1]
        == 8
    )


def test_mx07_style_displacement_is_prevented() -> None:
    # Model list: 3 chunks of file 144, 4 of file 146, then the expected file's chunk last. The original question
    # adds a 4th chunk of file 144. Uncapped, that chunk pushes the expected file out; capped, it does not.
    a = [
        filed(1, 144),
        filed(2, 146),
        filed(3, 146),
        filed(4, 144),
        filed(5, 146),
        filed(6, 144),
        filed(7, 146),
        filed(8, 999),
    ]
    extra = filed(20, 144)
    original = [a[0], a[1], a[2], a[3], a[4], extra]
    assert 8 not in ids(round_robin_merge(original, a, limit=8))
    assert ids(round_robin_merge(original, a, limit=8, max_per_file=3)) == [1, 2, 3, 4, 5, 6, 8, 20]
    assert 8 not in ids(
        round_robin_merge(original, a, limit=8, max_per_file=4)
    )  # a cap of 4 does not bind here


def test_cap_defers_in_the_current_turn_and_prefers_other_files() -> None:
    original = [filed(1, 1), filed(2, 1), filed(3, 1), filed(4, 1), filed(5, 2)]
    model = [filed(11, 3)]
    merged = round_robin_merge(original, model, limit=4, max_per_file=3)
    assert ids(merged) == [
        1,
        11,
        2,
        3,
    ]  # file 1 reaches 3; chunk 4 is deferred; the budget is met without it
    merged = round_robin_merge(original, model, limit=5, max_per_file=3)
    assert ids(merged) == [1, 11, 2, 3, 5]  # chunk 5 (file 2) is preferred to the deferred chunk 4


def test_refill_uses_deferred_chunks_in_encounter_order_and_puts_them_last() -> None:
    original = [filed(1, 1), filed(2, 1), filed(3, 1), filed(4, 1), filed(5, 1)]
    model = [filed(11, 1), filed(12, 1)]
    merged = round_robin_merge(original, model, limit=8, max_per_file=3)
    # Taken in turn order until file 1 holds three: 1 (original), 11 (model), 2 (original). Then 12 (model turn),
    # 3, 4 and 5 (original turns) are deferred in the order they were met, and refill the budget after the taken ones.
    assert ids(merged) == [1, 11, 2, 12, 3, 4, 5]


def test_a_chunk_in_both_lists_is_counted_once_even_when_it_is_deferred() -> None:
    shared = filed(3, 1)
    original = [filed(1, 1), filed(2, 1), shared, filed(4, 1)]
    model = [filed(11, 1), filed(12, 1), shared, filed(4, 1)]
    merged = round_robin_merge(original, model, limit=8, max_per_file=3)
    assert len(ids(merged)) == len(set(ids(merged)))


def test_empty_and_exhausted_lists_with_a_cap() -> None:
    assert round_robin_merge([], [], limit=8, max_per_file=3) == []
    assert ids(round_robin_merge([], [filed(11, 1), filed(12, 2)], limit=8, max_per_file=3)) == [
        11,
        12,
    ]
    assert ids(round_robin_merge([filed(1, 1)], [], limit=8, max_per_file=3)) == [1]
    assert round_robin_merge([filed(1, 1)], [filed(2, 2)], limit=0, max_per_file=3) == []


def test_a_single_file_keeps_filling_the_budget_because_the_cap_is_soft() -> None:
    original = [filed(n, 1) for n in range(1, 9)]
    model = [filed(n, 1) for n in range(11, 19)]
    merged = round_robin_merge(original, model, limit=8, max_per_file=3)
    assert len(merged) == 8 and {c.drive_file_id for c in merged} == {uuid.UUID(int=5001)}
    assert ids(merged)[:3] == [1, 11, 2]


def test_cap_never_returns_a_chunk_twice_and_never_exceeds_the_limit() -> None:
    rng = random.Random(5)
    pool = [filed(n, rng.randrange(1, 6)) for n in range(1, 41)]
    for _ in range(300):
        original = rng.sample(pool, rng.randrange(0, 9))
        model = rng.sample(pool, rng.randrange(0, 9))
        merged = round_robin_merge(original, model, limit=8, max_per_file=3)
        assert len(set(ids(merged))) == len(merged) <= 8
        assert set(ids(merged)) <= {c.chunk_id.int for c in (*original, *model)}


def test_matches_the_reviewed_experiment_strategy_on_random_lists() -> None:
    rng = random.Random(2026)
    pool = [filed(n, rng.randrange(1, 6)) for n in range(1, 41)]
    for cap in (3, 4):
        for _ in range(1000):
            original = rng.sample(pool, rng.randrange(0, 9))
            model = rng.sample(pool, rng.randrange(0, 9))
            assert ids(round_robin_merge(original, model, limit=8, max_per_file=cap)) == ids(
                reference_cap(original, model, 8, cap)
            )


def test_a_cap_of_at_least_the_limit_equals_the_uncapped_merge() -> None:
    rng = random.Random(9)
    pool = [filed(n, rng.randrange(1, 6)) for n in range(1, 41)]
    for _ in range(500):
        original = rng.sample(pool, rng.randrange(0, 9))
        model = rng.sample(pool, rng.randrange(0, 9))
        assert ids(round_robin_merge(original, model, limit=8, max_per_file=8)) == ids(
            round_robin_merge(original, model, limit=8)
        )


def test_the_cap_is_deterministic_and_does_not_mutate_its_inputs() -> None:
    original = [filed(1, 1), filed(2, 1), filed(3, 1), filed(4, 1)]
    model = [filed(11, 1), filed(12, 2)]
    first = round_robin_merge(original, model, limit=8, max_per_file=3)
    second = round_robin_merge(original, model, limit=8, max_per_file=3)
    assert ids(first) == ids(second)
    assert ids(original) == [1, 2, 3, 4] and ids(model) == [11, 12]
