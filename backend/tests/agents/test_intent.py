"""Tests for M3 intent classification and retrieval planning nodes."""

from __future__ import annotations

import uuid

from app.agents.drive_graph.nodes import (
    build_retrieval_plan,
    classify_intent,
    classify_intent_heuristic,
    plan_retrieval,
    receive_question,
)
from app.agents.drive_graph.state import create_initial_state
from app.agents.drive_graph.types import QueryIntent


def test_classify_intent_heuristic_examples_from_project_context() -> None:
    """Intent heuristics should cover core product question patterns."""
    assert classify_intent_heuristic("Find my latest resume.") is QueryIntent.FIND_LATEST
    assert classify_intent_heuristic("Files mentioning CoreChain") is QueryIntent.KEYWORD_SEARCH
    assert (
        classify_intent_heuristic("What is federated learning in my notes?")
        is QueryIntent.SEMANTIC_QUESTION
    )
    assert (
        classify_intent_heuristic("Summarize everything related to PTCL internship")
        is QueryIntent.SUMMARIZE_TOPIC
    )
    assert (
        classify_intent_heuristic("Show only PDFs in my Projects folder")
        is QueryIntent.LIST_OR_FILTER
    )


def test_receive_question_normalizes_and_resets_state() -> None:
    """receive_question should trim question and reset mutable workflow fields."""
    user_id = uuid.uuid4()
    state = create_initial_state(question="  Explain CoreChain docs  ", user_id=user_id)
    state["working_query"] = "stale query"
    state["rewrite_count"] = 5
    state["retrieval_count"] = 9
    state["citations"] = []

    update = receive_question(state)

    assert update["question"] == "Explain CoreChain docs"
    assert update["working_query"] == "Explain CoreChain docs"
    assert update["rewrite_count"] == 0
    assert update["retrieval_count"] == 0


def test_classify_intent_node_sets_intent() -> None:
    """classify_intent node should populate state intent."""
    state = create_initial_state(question="Find my latest resume", user_id=uuid.uuid4())
    normalized_update = receive_question(state)
    state["question"] = normalized_update["question"]
    state["working_query"] = normalized_update["working_query"]
    state["rewrite_count"] = normalized_update["rewrite_count"]
    state["raw_chunks"] = normalized_update["raw_chunks"]
    state["ranked_chunks"] = normalized_update["ranked_chunks"]
    state["citations"] = normalized_update["citations"]
    state["retrieval_count"] = normalized_update["retrieval_count"]

    update = classify_intent(state)

    assert update["intent"] is QueryIntent.FIND_LATEST


def test_plan_retrieval_node_maps_intent_to_retriever_subset() -> None:
    """plan_retrieval should select expected retriever sets."""
    state = create_initial_state(question="Show only PDFs in folder", user_id=uuid.uuid4())
    state["intent"] = QueryIntent.LIST_OR_FILTER

    update = plan_retrieval(state)
    plan = update["retrieval_plan"]

    assert plan.intent is QueryIntent.LIST_OR_FILTER
    assert plan.retrievers == ("metadata",)
    assert plan.uses_metadata is True
    assert plan.uses_vector is False


def test_build_retrieval_plan_unknown_defaults_to_full_hybrid() -> None:
    """Unknown intent should preserve recall by using all retrievers."""
    plan = build_retrieval_plan(QueryIntent.UNKNOWN)
    assert plan.retrievers == ("vector", "keyword", "metadata")
