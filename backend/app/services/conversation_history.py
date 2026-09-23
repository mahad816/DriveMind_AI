"""Pure selection and deterministic rendering of explicit prior-message recall."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from app.retrieval.conversation_intent import HistoryRole, ReferenceKind
from app.schemas.chat import ChatHistoryTurn


class HistoryOutcome(StrEnum):
    """Mutually distinct results of a bounded history lookup."""

    SELECTED = "selected"
    NO_HISTORY = "no_history"
    ROLE_NOT_PRESENT = "role_not_present"
    UNAVAILABLE_IN_BOUNDED_HISTORY = "unavailable_in_bounded_history"
    UNSUPPORTED_ORDINAL_REFERENCE = "unsupported_ordinal_reference"
    AMBIGUOUS_REFERENCE = "ambiguous_reference"


@dataclass(frozen=True)
class HistorySelection:
    """Selected exact text and position, or a truthful non-selection outcome."""

    outcome: HistoryOutcome
    text: str | None = None
    index: int | None = None


def select_history_turn(
    history: Sequence[ChatHistoryTurn | Mapping[str, str]],
    *,
    target_role: HistoryRole | str | None,
    history_window_complete: bool,
    reference_kind: ReferenceKind = ReferenceKind.LATEST_SUPPORTED,
) -> HistorySelection:
    """Select the latest matching role without interpreting historical text."""
    if reference_kind is ReferenceKind.UNSUPPORTED_ORDINAL_REFERENCE:
        return HistorySelection(HistoryOutcome.UNSUPPORTED_ORDINAL_REFERENCE)
    if reference_kind is ReferenceKind.AMBIGUOUS_REFERENCE:
        return HistorySelection(HistoryOutcome.AMBIGUOUS_REFERENCE)

    for index in range(len(history) - 1, -1, -1):
        turn = history[index]
        role = turn["role"] if isinstance(turn, Mapping) else turn.role
        if role == target_role:
            text = turn["text"] if isinstance(turn, Mapping) else turn.text
            return HistorySelection(HistoryOutcome.SELECTED, text=text, index=index)

    if not history and history_window_complete:
        return HistorySelection(HistoryOutcome.NO_HISTORY)
    if history_window_complete:
        return HistorySelection(HistoryOutcome.ROLE_NOT_PRESENT)
    return HistorySelection(HistoryOutcome.UNAVAILABLE_IN_BOUNDED_HISTORY)


def render_history_answer(selection: HistorySelection, role: HistoryRole | None) -> str:
    """Render a fixed response; selected text is copied as data, never generated."""
    if selection.outcome is HistoryOutcome.SELECTED:
        prefix = "Your last question was:" if role is HistoryRole.USER else "My last answer was:"
        return f"{prefix}\n{selection.text}"
    if selection.outcome is HistoryOutcome.NO_HISTORY:
        return "There are no earlier messages in this conversation to recall."
    if selection.outcome is HistoryOutcome.ROLE_NOT_PRESENT:
        if role is HistoryRole.USER:
            return "There is no earlier question from you in this conversation."
        return "There is no earlier answer from me in this conversation."
    if selection.outcome is HistoryOutcome.UNAVAILABLE_IN_BOUNDED_HISTORY:
        return "That message is not in the available recent history; it may be outside this bounded window."
    if selection.outcome is HistoryOutcome.UNSUPPORTED_ORDINAL_REFERENCE:
        return "I can recall only the latest prior question or answer, not an earlier ordinal turn."
    return "Please specify whether you mean your prior question or my prior answer."
