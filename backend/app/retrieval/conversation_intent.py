"""High-confidence intent detection for explicit prior-message recall."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class HistoryRole(StrEnum):
    """Role of the historical message being requested."""

    USER = "user"
    ASSISTANT = "assistant"


class ReferenceKind(StrEnum):
    """Whether the requested historical position is supported."""

    LATEST_SUPPORTED = "latest_supported"
    UNSUPPORTED_ORDINAL_REFERENCE = "unsupported_ordinal_reference"
    AMBIGUOUS_REFERENCE = "ambiguous_reference"


@dataclass(frozen=True)
class ConversationReference:
    """Message-recall intent, independent of any history contents."""

    target_role: HistoryRole | None
    reference_kind: ReferenceKind


# Narrowly normalize common short-form cue typos; never transform file/topic nouns.
_CUE_ALIASES: dict[str, str] = {
    "wht": "what",
    "wat": "what",
    "ur": "your",
    "jus": "just",
    "askd": "asked",
    "answr": "answer",
}
_FIRST_PERSON = frozenset({"i", "me", "my"})
_SECOND_PERSON = frozenset({"you", "your"})
_QUESTION_CUES = frozenset({"ask", "asked", "asking", "question", "questions", "prompt"})
_ANSWER_CUES = frozenset(
    {
        "answer",
        "answered",
        "reply",
        "replied",
        "response",
        "responded",
        "say",
        "said",
        "tell",
        "told",
    }
)
_RECALL_CUES = frozenset(
    {"previous", "last", "just", "now", "before", "repeat", "again", "remind", "preceding"}
)
_ORDINAL_LAST_RE = re.compile(
    r"\b(?:\d+(?:st|nd|rd|th)?|first|second|third|[a-z]+th) (?:to )?last\b"
)
_COUNT_BACK_RE = re.compile(
    r"\b(?:\d+|[a-z]+) (?:questions?|answers?|replies|responses?|messages?|prompts?) ago\b"
)
_BEFORE_RE = re.compile(r"\bbefore (?:that|(?:your|my|the) last)\b")


def classify_conversation_reference(question: str) -> ConversationReference | None:
    """Return a decision only for an explicit, role-resolvable chat-message reference."""
    words = [
        _CUE_ALIASES.get(word) or word
        for word in re.findall(r"[a-z0-9]+", question.lower().replace("’", "'"))
    ]
    tokens = set(words)
    normalized = " ".join(words)
    direct_assistant_recall = (
        words[:4] == ["tell", "me", "what", "you"]
        and len(words) in {5, 6}
        and words[4] in _ANSWER_CUES
        and (len(words) == 5 or words[5] in {"me", "with"})
    )
    direct_recall = normalized.startswith(("what did", "what was", "which was")) or (
        len(words) >= 3 and words[0] == "what" and words[1] in _QUESTION_CUES and words[2] == "did"
    )
    ordinal = any(
        pattern.search(normalized) for pattern in (_ORDINAL_LAST_RE, _COUNT_BACK_RE, _BEFORE_RE)
    )
    if not (tokens & _RECALL_CUES or direct_recall or direct_assistant_recall or ordinal):
        return None

    question_referent = bool(tokens & _QUESTION_CUES)
    answer_referent = bool(tokens & _ANSWER_CUES)
    user_reference = bool(tokens & _FIRST_PERSON and question_referent)
    assistant_reference = bool(tokens & _SECOND_PERSON and answer_referent)
    if user_reference and assistant_reference:
        return ConversationReference(
            None,
            ReferenceKind.UNSUPPORTED_ORDINAL_REFERENCE
            if ordinal
            else ReferenceKind.AMBIGUOUS_REFERENCE,
        )
    if user_reference:
        role = HistoryRole.USER
    elif assistant_reference:
        role = HistoryRole.ASSISTANT
    elif "repeat" in tokens and question_referent != answer_referent:
        role = HistoryRole.USER if question_referent else HistoryRole.ASSISTANT
    else:
        return None

    return ConversationReference(
        target_role=role,
        reference_kind=(
            ReferenceKind.UNSUPPORTED_ORDINAL_REFERENCE
            if ordinal
            else ReferenceKind.LATEST_SUPPORTED
        ),
    )
