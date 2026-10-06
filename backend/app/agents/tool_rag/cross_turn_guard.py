"""Bounded provenance guard for previous-turn file references, not intent routing."""

import re

_VAGUE_FILE_REFERENCE = re.compile(
    r"\b(?:(?:first|second|third)\s+(?:one|file|document)|that\s+(?:file|document))\b",
    re.IGNORECASE,
)


def unresolved_cross_turn_reference(
    *, question: str, has_prior_history: bool, proposed_reference: str, returned_in_run: bool
) -> bool:
    if not has_prior_history or returned_in_run or not _VAGUE_FILE_REFERENCE.search(question):
        return False
    # Literal occurrence only. No fuzzy matching, filename extraction or semantic inference.
    reference = proposed_reference.strip().casefold()
    explicit = re.search(
        r"(?<![\w./\\-])" + re.escape(reference) + r"(?![\w/\\-]|\.\w)", question.casefold()
    )
    return explicit is None
