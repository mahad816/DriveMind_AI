"""Round-robin combination of two ranked chunk lists (original question and model query, C2)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from app.retrieval.types import RetrievedChunk


def round_robin_merge(
    original: Sequence[RetrievedChunk],
    model: Sequence[RetrievedChunk],
    *,
    limit: int,
) -> list[RetrievedChunk]:
    """Alternate between two ranked lists, original first, until ``limit`` unique chunks are taken.

    Each turn takes the best chunk of that list not taken yet, so a chunk both lists contain is taken once and
    never costs the turn. A list that runs out hands every remaining turn to the other. The chunk objects, with
    their own scores, are returned unchanged; the copy from the list that reached a chunk first is kept.
    """
    taken: list[RetrievedChunk] = []
    seen: set[uuid.UUID] = set()
    lists = (original, model)
    cursors = [0, 0]
    turn = 0
    while len(taken) < limit and (cursors[0] < len(original) or cursors[1] < len(model)):
        source = lists[turn]
        while cursors[turn] < len(source):
            candidate = source[cursors[turn]]
            cursors[turn] += 1
            if candidate.chunk_id not in seen:
                seen.add(candidate.chunk_id)
                taken.append(candidate)
                break
        turn = 1 - turn
    return taken
