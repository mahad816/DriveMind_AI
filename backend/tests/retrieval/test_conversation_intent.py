"""EXP-03 RED contract for explicit chat-message intent, separate from turn selection."""

from __future__ import annotations

import pytest

from app.retrieval.conversation_intent import (
    ConversationReference,
    classify_conversation_reference,
)


def _classify(question: str) -> ConversationReference | None:
    return classify_conversation_reference(question)


def _label(value: object) -> object:
    return getattr(value, "value", value)


@pytest.mark.parametrize(
    ("question", "role"),
    [
        ("What was the question I just asked?", "user"),
        ("Please repeat my last question", "user"),
        ("Could you say your previous answer again?", "assistant"),
        ("What did you last answer?", "assistant"),
        ("wat was ur last reply?", "assistant"),
        ("Repeat the previous answer", "assistant"),
    ],
)
def test_classifies_latest_chat_recall_by_requested_role(question: str, role: str) -> None:
    decision = _classify(question)

    assert decision is not None
    assert _label(decision.target_role) == role
    assert _label(decision.reference_kind) == "latest_supported"


@pytest.mark.parametrize(
    "question",
    [
        "Tell me what you answered",
        "Tell me what you replied",
        "Tell me what you responded",
    ],
)
def test_direct_assistant_response_recall_without_recency_word(question: str) -> None:
    decision = _classify(question)

    assert decision is not None
    assert _label(decision.target_role) == "assistant"
    assert _label(decision.reference_kind) == "latest_supported"


@pytest.mark.parametrize(
    "question",
    [
        "What did I ask before that?",
        "Which was my second-last question?",
        "Repeat the answer before your last one",
        "What did I ask before your last answer?",
    ],
)
def test_identifies_unsupported_chat_ordinal_without_selecting_latest(question: str) -> None:
    decision = _classify(question)

    assert decision is not None
    assert _label(decision.reference_kind) == "unsupported_ordinal_reference"


@pytest.mark.parametrize(
    ("question", "role"),
    [
        ("What was my third-last question?", "user"),
        ("What was my fourth last question?", "user"),
        ("What was my eleventh-last question?", "user"),
        ("What did I ask two questions ago?", "user"),
        ("What did you answer 3 replies ago?", "assistant"),
        ("Tell me your answer three replies ago", "assistant"),
    ],
)
def test_general_chat_ordinals_are_unsupported(question: str, role: str) -> None:
    decision = _classify(question)

    assert decision is not None
    assert _label(decision.target_role) == role
    assert _label(decision.reference_kind) == "unsupported_ordinal_reference"


def test_direct_user_question_recall_without_recency_word() -> None:
    decision = _classify("What question did I ask?")

    assert decision is not None
    assert _label(decision.target_role) == "user"
    assert _label(decision.reference_kind) == "latest_supported"


# Observed EXP-03 v1 failures are regression cases, not held-out evidence.
@pytest.mark.parametrize(
    ("question", "role", "reference_kind"),
    [
        ("Would you restate the question I posed most recently?", "user", "latest_supported"),
        ("Could you quote your latest response to me?", "assistant", "latest_supported"),
        ("In this chat, which question did I most recently send?", "user", "latest_supported"),
        (
            "Can you give me my penultimate question?",
            "user",
            "unsupported_ordinal_reference",
        ),
    ],
)
def test_observed_v1_history_misses_become_regression_cases(
    question: str, role: str, reference_kind: str
) -> None:
    decision = _classify(question)

    assert decision is not None
    assert _label(decision.target_role) == role
    assert _label(decision.reference_kind) == reference_kind


@pytest.mark.parametrize(
    ("question", "role", "reference_kind"),
    [
        ("Please restate the message I submitted most recently.", "user", "latest_supported"),
        ("Can you recall the message I sent to this chat?", "user", "latest_supported"),
        ("Please quote the response you gave most recently.", "assistant", "latest_supported"),
        ("What was your penultimate reply?", "assistant", "unsupported_ordinal_reference"),
        (
            "Repeat my question prior to the latest one.",
            "user",
            "unsupported_ordinal_reference",
        ),
    ],
)
def test_composes_message_target_role_and_recall_or_ordinal_intent(
    question: str, role: str, reference_kind: str
) -> None:
    decision = _classify(question)

    assert decision is not None
    assert _label(decision.target_role) == role
    assert _label(decision.reference_kind) == reference_kind


def test_ambiguous_explicit_message_reference_does_not_guess_a_role() -> None:
    decision = _classify("What did you say about my last question?")

    assert decision is not None
    assert decision.target_role is None
    assert _label(decision.reference_kind) == "ambiguous_reference"


@pytest.mark.parametrize(
    "question",
    [
        "Show the previous version of project-plan.pdf",
        "What was the last modified report?",
        "Find the last PDF I uploaded",
        "Tell me what the previous report answered",
        "Show me the third-last version of this file",
        "Find the report from two days ago",
        "What did the previous PDF say?",
    ],
)
def test_document_recency_is_not_chat_message_intent(question: str) -> None:
    assert _classify(question) is None


@pytest.mark.parametrize(
    "question",
    [
        "Restate what the report says.",
        "Quote the latest PDF.",
        "Which file did I most recently upload?",
        "What was in the penultimate revision?",
        "Show the response stored in this document.",
        "Can you quote the answer in this report?",
        "Could you restate the response stored in the document?",
        "Which report did I send most recently?",
    ],
)
def test_recall_and_recency_words_do_not_turn_document_targets_into_chat_messages(
    question: str,
) -> None:
    assert _classify(question) is None


def test_requested_target_distinguishes_chat_question_about_report_from_report_content() -> None:
    chat_decision = _classify("Recall my last question about the budget report")

    assert chat_decision is not None
    assert _label(chat_decision.target_role) == "user"
    assert _label(chat_decision.reference_kind) == "latest_supported"
    assert _classify("What did the previous budget report say?") is None
    assert _classify("What did the previous budget report say about my last question?") is None
