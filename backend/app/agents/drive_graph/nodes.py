"""LangGraph node implementations (stubbed for Phase 8 M2)."""

from __future__ import annotations

import uuid as uuid_module
from typing import Any

from app.agents.drive_graph.state import DriveGraphState
from app.llm.prompts import NO_EVIDENCE_ANSWER


def receive_question(state: DriveGraphState) -> dict[str, Any]:
    """Initialize/validate the incoming question state (stub)."""
    return {}


def classify_intent(state: DriveGraphState) -> dict[str, Any]:
    """Classify user intent (stub)."""
    return {}


def plan_retrieval(state: DriveGraphState) -> dict[str, Any]:
    """Plan which retrievers to use for the question (stub)."""
    return {}


def route_retriever(state: DriveGraphState) -> dict[str, Any]:
    """Route to a subset of retrievers (stub)."""
    return {}


def retrieve(state: DriveGraphState) -> dict[str, Any]:
    """Retrieve raw evidence chunks (stubbed: no DB/Qdrant calls in M2)."""
    return {
        "raw_chunks": [],
        "ranked_chunks": [],
        "retrieval_count": 0,
    }


def rerank(state: DriveGraphState) -> dict[str, Any]:
    """Rerank retrieved chunks (stub)."""
    return {}


def grade_evidence(state: DriveGraphState) -> dict[str, Any]:
    """Grade evidence sufficiency (stub: always insufficient in M2)."""
    return {
        "evidence_sufficient": False,
        "evidence_reason": "M2 stub: no retrieval executed, so evidence is insufficient.",
    }


def rewrite_query(state: DriveGraphState) -> dict[str, Any]:
    """Rewrite the query to improve retrieval (stub)."""
    next_count = state["rewrite_count"] + 1
    refined = f"{state['working_query']} (refined {next_count})"
    return {
        "working_query": refined,
        "rewrite_count": next_count,
    }


def generate_answer(state: DriveGraphState) -> dict[str, Any]:
    """Generate the final answer (stub)."""
    return {
        "answer": NO_EVIDENCE_ANSWER,
        "citations": [],
    }


def verify_citations(state: DriveGraphState) -> dict[str, Any]:
    """Verify bracket citations (stub: no-op for M2)."""
    return {}


def return_response(state: DriveGraphState) -> dict[str, Any]:
    """Finalize the state for a RagResult (stub)."""
    return {
        "query_id": uuid_module.uuid4(),
    }
