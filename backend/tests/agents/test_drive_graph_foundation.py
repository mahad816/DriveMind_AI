"""Tests for drive graph state and retrieval-plan types."""

from __future__ import annotations

import uuid

import pytest

from app.agents.drive_graph.state import create_initial_state
from app.agents.drive_graph.types import QueryIntent, RetrievalPlan


def test_query_intent_values() -> None:
    """QueryIntent should expose stable string values for graph routing."""
    assert QueryIntent.FIND_LATEST == "find_latest"
    assert QueryIntent.UNKNOWN == "unknown"


def test_retrieval_plan_requires_at_least_one_retriever() -> None:
    """RetrievalPlan should reject empty retriever lists."""
    with pytest.raises(ValueError, match="at least one retriever"):
        RetrievalPlan(intent=QueryIntent.UNKNOWN, retrievers=())


def test_retrieval_plan_rejects_unknown_retriever() -> None:
    """RetrievalPlan should reject unsupported retriever names."""
    with pytest.raises(ValueError, match="Unsupported retriever"):
        RetrievalPlan(intent=QueryIntent.UNKNOWN, retrievers=("vector", "invalid"))  # type: ignore[arg-type]


def test_retrieval_plan_retriever_flags() -> None:
    """RetrievalPlan helper properties should reflect selected retrievers."""
    plan = RetrievalPlan(
        intent=QueryIntent.SUMMARIZE_TOPIC,
        retrievers=("vector", "keyword", "metadata"),
        sort_by_modified_desc=True,
    )
    assert plan.uses_vector is True
    assert plan.uses_keyword is True
    assert plan.uses_metadata is True
    assert plan.sort_by_modified_desc is True


def test_create_initial_state_normalizes_question() -> None:
    """Initial state should trim whitespace and initialize rewrite counter."""
    user_id = uuid.uuid4()
    state = create_initial_state(question="  What is tensile strength?  ", user_id=user_id)

    assert state["question"] == "What is tensile strength?"
    assert state["working_query"] == "What is tensile strength?"
    assert state["user_id"] == user_id
    assert state["rewrite_count"] == 0
    assert state["raw_chunks"] == []
    assert state["ranked_chunks"] == []
    assert state["citations"] == []
    assert state["retrieval_count"] == 0


def test_create_initial_state_rejects_empty_question() -> None:
    """Initial state should reject blank questions."""
    with pytest.raises(ValueError, match="must not be empty"):
        create_initial_state(question="   ", user_id=uuid.uuid4())
