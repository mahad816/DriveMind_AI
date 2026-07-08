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
    ],
)
def test_pure_social_phrases_are_chitchat(question: str) -> None:
    assert classify_query(question) is QueryRoute.CHITCHAT


@pytest.mark.parametrize(
    "question",
    [
        # Knowledge signals override social words
        "hi, find my resume",
        "hello, what files do I have?",
        "hey, summarize my documents",
        "thanks, now find my CV",
        "ok, list my certificates",
        # Short but has knowledge signal
        "find resume",
        "show files",
    ],
)
def test_social_plus_knowledge_signal_is_not_chitchat(question: str) -> None:
    assert classify_query(question) is not QueryRoute.CHITCHAT


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
        "Tell me about my AWS experience",
        "Summarize everything about CoreChain",
        "Find everything related to machine learning",
        "Which files mention LangGraph or RAG?",
    ],
)
def test_knowledge_questions_route_to_grounded_rag(question: str) -> None:
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
