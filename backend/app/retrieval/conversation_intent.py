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
_QUESTION_NOUNS = frozenset({"question", "questions", "prompt", "prompts"})
_ASK_VERBS = frozenset({"ask", "asked", "asking"})
_ANSWER_NOUNS = frozenset({"answer", "answers", "reply", "replies", "response", "responses"})
_ANSWER_VERBS = frozenset({"answered", "replied", "responded", "say", "said", "told"})
_BASE_ANSWER_VERBS = frozenset({"answer", "reply", "respond", "say", "tell"})
_MESSAGE_NOUNS = frozenset({"message", "messages"})
_DOCUMENT_NOUNS = frozenset(
    {"file", "files", "pdf", "report", "reports", "document", "documents", "version", "revision"}
)
_RECALL_ACTIONS = frozenset(
    {"repeat", "restate", "recall", "remind", "quote", "identify", "give", "show"}
)
_RECENCY_CUES = frozenset(
    {
        "previous",
        "last",
        "latest",
        "just",
        "now",
        "before",
        "again",
        "preceding",
        "recent",
        "recently",
    }
)
_OWNED_MESSAGE_RE = re.compile(r"\b(my|your)(?: \w+){0,2} messages?\b")
_ACTED_MESSAGE_RE = re.compile(r"\bmessages? (?:that )?(i|you) (?:sent|submitted|wrote|said)\b")
_ORDINAL_LAST_RE = re.compile(
    r"\b(?:\d+(?:st|nd|rd|th)?|first|second|third|[a-z]+th) (?:to )?last\b"
)
_COUNT_BACK_RE = re.compile(
    r"\b(?:\d+|[a-z]+) (?:questions?|answers?|replies|responses?|messages?|prompts?) ago\b"
)
_BEFORE_RE = re.compile(r"\bbefore (?:that|(?:your|my|the) last)\b")
_PRIOR_TO_LATEST_RE = re.compile(r"\bprior to (?:my |your |the )?(?:latest|last)\b")


def _document_is_requested_target(words: list[str]) -> bool:
    """Prefer a leading document referent over later chat words used as its topic."""
    message_words = _QUESTION_NOUNS | _ASK_VERBS | _ANSWER_NOUNS | _ANSWER_VERBS | _MESSAGE_NOUNS
    first_document = next((i for i, word in enumerate(words) if word in _DOCUMENT_NOUNS), None)
    first_message = next((i for i, word in enumerate(words) if word in message_words), None)
    return first_document is not None and (first_message is None or first_document < first_message)


def _assistant_is_message_owner(words: list[str]) -> bool:
    """Distinguish who spoke from a polite 'you' asked to quote a document."""
    for index, word in enumerate(words):
        following = words[index + 1 : index + 4]
        if word == "your" and any(part in _ANSWER_NOUNS for part in following):
            return True
        if word in _ANSWER_NOUNS and len(following) >= 2:
            if following[0] == "you" and following[1] in {"gave", "sent"}:
                return True
        if word == "you":
            if following and following[0] in _ANSWER_VERBS:
                return True
            if len(following) >= 2 and following[0] in _RECENCY_CUES:
                if following[1] in _BASE_ANSWER_VERBS:
                    return True
            if index >= 2 and words[index - 2 : index] == ["what", "did"]:
                if following and following[0] in _BASE_ANSWER_VERBS:
                    return True
    return False


def _message_roles(words: list[str], normalized: str) -> tuple[bool, bool, bool]:
    """Find the requested chat-message role; document words alone are not a veto."""
    tokens = set(words)
    question_target = bool(tokens & (_QUESTION_NOUNS | _ASK_VERBS))
    answer_target = bool(tokens & (_ANSWER_NOUNS | _ANSWER_VERBS))
    user = question_target and bool(tokens & _FIRST_PERSON)
    assistant = _assistant_is_message_owner(words)

    for match in _OWNED_MESSAGE_RE.finditer(normalized):
        user |= match[1] == "my"
        assistant |= match[1] == "your"
    for match in _ACTED_MESSAGE_RE.finditer(normalized):
        user |= match[1] == "i"
        assistant |= match[1] == "you"

    # Subject-plus-communication-verb forms identify a message without a noun.
    user |= bool(tokens & _ASK_VERBS and "i" in tokens)
    return user, assistant, question_target or answer_target or bool(tokens & _MESSAGE_NOUNS)


def classify_conversation_reference(question: str) -> ConversationReference | None:
    """Compose message target, role, and recall position before claiming chat intent."""
    words = [
        _CUE_ALIASES.get(word) or word
        for word in re.findall(r"[a-z0-9]+", question.lower().replace("’", "'"))
    ]
    tokens = set(words)
    normalized = " ".join(words)
    if _document_is_requested_target(words):
        return None
    user_reference, assistant_reference, message_target = _message_roles(words, normalized)
    if not message_target:
        return None

    ordinal = (
        any(
            pattern.search(normalized)
            for pattern in (_ORDINAL_LAST_RE, _COUNT_BACK_RE, _BEFORE_RE, _PRIOR_TO_LATEST_RE)
        )
        or "penultimate" in tokens
    )
    direct_question = "what" in tokens or "which" in tokens
    recall = bool(tokens & (_RECALL_ACTIONS | _RECENCY_CUES)) or direct_question
    if not (recall or ordinal):
        return None

    # A bare "repeat the answer" is chat recall, but a document-qualified
    # answer is not. Explicit chat ownership still wins over a secondary topic.
    if not (user_reference or assistant_reference) and "repeat" in tokens:
        if not tokens & _DOCUMENT_NOUNS:
            question_noun = bool(tokens & _QUESTION_NOUNS)
            answer_noun = bool(tokens & _ANSWER_NOUNS)
            user_reference = question_noun and not answer_noun
            assistant_reference = answer_noun and not question_noun
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
