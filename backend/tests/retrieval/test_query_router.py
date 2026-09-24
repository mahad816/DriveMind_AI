"""Tests for query routing classification."""

from __future__ import annotations

import pytest

from app.retrieval.query_router import QueryRoute, classify_query


# ── Chitchat ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "question",
    [
        "hi",
        "Hi",
        "HI",
        "hello",
        "Hello!",
        "hey",
        "Hey!",
        "hiya",
        "howdy",
        "thanks",
        "thank you",
        "thx",
        "ty",
        "ok",
        "okay",
        "cool",
        "great",
        "awesome",
        "bye",
        "goodbye",
        "good morning",
        "Good Morning",
        "good night",
        "how are you",
        "how are you?",
        "how are you doing",
        "whats up",
        "what's up",
        "what can you do?",
        "who are you?",
    ],
)
def test_pure_social_phrases_are_chitchat(question: str) -> None:
    assert classify_query(question) is QueryRoute.CHITCHAT


@pytest.mark.parametrize(
    "question",
    [
        # Social words inside substantive requests are not exact chitchat phrases.
        "hi, find my resume",
        "hello, what files do I have?",
        "hey, summarize my documents",
        "thanks, now find my CV",
        "ok, list my certificates",
        # Short retrieval requests remain non-chitchat.
        "find resume",
        "show files",
    ],
)
def test_substantive_requests_with_social_words_are_not_chitchat(question: str) -> None:
    assert classify_query(question) is not QueryRoute.CHITCHAT


@pytest.mark.parametrize(
    "question",
    [
        "CoreChain architecture",
        "DriveMind architecture",
        "cloud computing notes",
        "federated learning",
        "meeting notes",
        "machine learning",
        "architecture",
        "notes",
        "Python",
    ],
)
def test_short_substantive_topics_route_to_grounded_rag(question: str) -> None:
    assert classify_query(question) is QueryRoute.GROUNDED_RAG


# ── File inventory ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "question",
    [
        # Exact user question that triggered the bug
        "can you check all files which have resume name or CV and tell how many in total and tell which one of them was the latest resume like date etc and does it include any mention of GPA or no",
        # Simpler forms
        "find all resume files",
        "how many CV files do I have?",
        "Find my latest resume",
        "show me all my certificates",
        "list all resumes",
        "what is the latest CV",
        "find all certificate files",
        "how many resumes do I have",
        "show my recent certificates",
        "check all resume files",
        "find every CV",
        "list my certifications",
        "get all transcripts",
        "show latest thesis",
        "find all my reports",
        # "files named/with X" pattern
        'files named "resume"',
        "files with resume in the name",
        "files called CV",
    ],
)
def test_file_inventory_questions_route_correctly(question: str) -> None:
    assert classify_query(question) is QueryRoute.FILE_INVENTORY


# ── Grounded RAG ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "question",
    [
        "What does tensile strength mean?",
        "Summarize my internship documents",
        "What is LangGraph?",
        "Explain CoreChain architecture",
        "What projects did I work on at PTCL?",
        "What is federated learning in my notes?",
        "Summarize everything about CoreChain",
        "Find everything related to machine learning",
        "Which files mention LangGraph or RAG?",
        "PTCL internship",
        "project requirements",
        "expense report",
        "What is CoreChain?",
        "Explain CoreChain",
        "How does CoreChain work?",
        "What did I do at PTCL?",
    ],
)
def test_knowledge_questions_route_to_grounded_rag(question: str) -> None:
    assert classify_query(question) is QueryRoute.GROUNDED_RAG


@pytest.mark.parametrize(
    "question",
    [
        "Tell me about my AWS experience",
    ],
)
def test_broad_topic_questions_route_to_grounded_rag(question: str) -> None:
    assert classify_query(question) is QueryRoute.GROUNDED_RAG


# ── Edge cases ────────────────────────────────────────────────────────────────


def test_empty_string_routes_to_grounded_rag() -> None:
    assert classify_query("") is QueryRoute.GROUNDED_RAG


def test_whitespace_only_routes_to_grounded_rag() -> None:
    assert classify_query("   ") is QueryRoute.GROUNDED_RAG


def test_chitchat_priority_over_file_inventory() -> None:
    # Pure greeting — no action signal strong enough to flip to inventory
    assert classify_query("hi") is QueryRoute.CHITCHAT


def test_find_latest_resume_is_file_inventory() -> None:
    # This is the key regression for the plan — used to map to FIND_LATEST
    # which returned globally latest files, not resume-specific ones.
    assert classify_query("Find my latest resume") is QueryRoute.FILE_INVENTORY


def test_find_latest_cv_is_file_inventory() -> None:
    assert classify_query("What is my most recent CV?") is QueryRoute.FILE_INVENTORY


# ── General file-count queries (Phase B) ───────────────────────────────────────


@pytest.mark.parametrize(
    "question",
    [
        "list total number of files",
        "how many files do I have",
        "how many files do I have indexed",
        "count all files",
        "what is the total number of files",
        "how many files are there",
        "list all my files",
        "show all my files",
        "all my files",
    ],
)
def test_general_file_count_routes_to_file_inventory(question: str) -> None:
    """Global file count / listing should route to FILE_INVENTORY (no domain term needed)."""
    assert classify_query(question) is QueryRoute.FILE_INVENTORY


# EXP-03: only explicit references to chat messages get the new route.
@pytest.mark.parametrize(
    "question",
    [
        "What was the question I just asked?",
        "Can you repeat my last question?",
        "What did you just reply?",
        "Say your last answer again",
        "wht did i ask jus now?",
    ],
)
def test_routes_explicit_message_recall_to_conversation_history(question: str) -> None:
    assert classify_query(question) is QueryRoute.CONVERSATION_HISTORY


@pytest.mark.parametrize(
    "question",
    [
        "What did I ask before that?",
        "What was my second-last question?",
        "Repeat the answer before your last one",
    ],
)
def test_routes_unsupported_chat_ordinals_to_conversation_history(question: str) -> None:
    assert classify_query(question) is QueryRoute.CONVERSATION_HISTORY


def test_routes_ambiguous_explicit_message_reference_to_conversation_history() -> None:
    assert (
        classify_query("What did you say about my last question?")
        is QueryRoute.CONVERSATION_HISTORY
    )


@pytest.mark.parametrize(
    "question",
    [
        "Would you restate the question I posed most recently?",
        "Can you give me my penultimate question?",
    ],
)
def test_observed_v1_history_misses_reach_the_history_route(question: str) -> None:
    assert classify_query(question) is QueryRoute.CONVERSATION_HISTORY


@pytest.mark.parametrize(
    "question",
    [
        "Quote the latest PDF.",
        "Which report did I send most recently?",
        "What was in the penultimate revision?",
    ],
)
def test_document_targets_with_history_vocabulary_do_not_reach_history_route(
    question: str,
) -> None:
    assert classify_query(question) is not QueryRoute.CONVERSATION_HISTORY


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("show me the previous version of project-plan.pdf", QueryRoute.GROUNDED_RAG),
        ("what was the last modified report?", QueryRoute.FILE_INVENTORY),
        ("list the latest meeting files", QueryRoute.GROUNDED_RAG),
        (
            "compare the previous internship report with the current one",
            QueryRoute.GROUNDED_RAG,
        ),
        ("find the last PDF I uploaded", QueryRoute.GROUNDED_RAG),
        ("how are you?", QueryRoute.CHITCHAT),
        ("how many files are named agenda?", QueryRoute.FILE_INVENTORY),
        ('Tell me about "Field_Notes.docx"', QueryRoute.FILE_TARGET),
        ("What causes condensation?", QueryRoute.GROUNDED_RAG),
    ],
)
def test_document_and_existing_routes_do_not_become_chat_recall(
    question: str, expected: QueryRoute
) -> None:
    assert classify_query(question) is expected
