"""Round-robin combination of two ranked chunk lists (original question and model query, C2)."""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Sequence

from app.retrieval.types import RetrievedChunk


def round_robin_merge(
    original: Sequence[RetrievedChunk],
    model: Sequence[RetrievedChunk],
    *,
    limit: int,
    max_per_file: int = 0,
) -> list[RetrievedChunk]:
    """Alternate between two ranked lists, original first, until ``limit`` unique chunks are taken.

    Each turn takes the best chunk of that list not taken yet, so a chunk both lists contain is taken once and
    never costs the turn. A list that runs out hands every remaining turn to the other. The chunk objects, with
    their own scores, are returned unchanged; the copy from the list that reached a chunk first is kept.

    ``max_per_file`` > 0 adds a SOFT per-file cap (strategy C2-cap3, selected on development evidence on
    2026-11-24; see docs/tickets/hybrid-retrieval-comparison/01-fusion-and-query-source-comparison.md). A chunk
    whose file already holds ``max_per_file`` taken chunks is deferred (kept, in the order it was met) and the turn
    continues with that list's next chunk, so another file is preferred whenever one has a candidate. When both
    lists are exhausted and fewer than ``limit`` chunks were taken, the deferred chunks refill the remaining slots in
    the order they were met and come after the taken ones. A chunk seen once, taken or deferred, is never
    considered again. The cap is soft: a file exceeds it only when the candidates that respect it cannot fill the
    budget. With ``max_per_file`` of 0 (or a limit at or below the cap) nothing is deferred and the result is the
    plain round-robin.
    """
    taken: list[RetrievedChunk] = []
    seen: set[uuid.UUID] = set()
    per_file: Counter[uuid.UUID] = Counter()
    deferred: list[RetrievedChunk] = []
    lists = (original, model)
    cursors = [0, 0]
    turn = 0
    while len(taken) < limit and (cursors[0] < len(original) or cursors[1] < len(model)):
        source = lists[turn]
        while cursors[turn] < len(source):
            candidate = source[cursors[turn]]
            cursors[turn] += 1
            if candidate.chunk_id in seen:
                continue
            seen.add(candidate.chunk_id)
            if max_per_file > 0 and per_file[candidate.drive_file_id] >= max_per_file:
                deferred.append(candidate)
                continue
            per_file[candidate.drive_file_id] += 1
            taken.append(candidate)
            break
        turn = 1 - turn
    for candidate in deferred:
        if len(taken) >= limit:
            break
        taken.append(candidate)
    return taken
