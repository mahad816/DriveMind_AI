"""DriveMind LangGraph skeleton for Phase 8 (intent -> retrieval -> grade -> optional rewrite)."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from langgraph.graph import END, StateGraph

from app.agents.drive_graph.nodes import (
    classify_intent,
    grade_evidence,
    generate_answer,
    plan_retrieval,
    receive_question,
    return_response,
    rewrite_query,
    route_retriever,
    retrieve,
    rerank,
    verify_citations,
)
from app.agents.drive_graph.state import DriveGraphState


def _should_rewrite(state: DriveGraphState) -> str:
    """Conditional edge logic for the evidence grade stage."""
    if state.get("evidence_sufficient", False):
        return "generate_answer"

    max_attempts = state.get("max_rewrite_attempts", 0) or 0
    return "rewrite_query" if state["rewrite_count"] < max_attempts else "generate_answer"


@lru_cache(maxsize=1)
def build_drive_graph() -> Any:
    """Compile and cache the Phase 8 DriveGraph skeleton."""
    graph = StateGraph(DriveGraphState)

    # Core pipeline nodes (stubbed in M2).
    graph.add_node("receive_question", receive_question)
    graph.add_node("classify_intent", classify_intent)
    graph.add_node("plan_retrieval", plan_retrieval)
    graph.add_node("route_retriever", route_retriever)
    graph.add_node("retrieve", retrieve)
    graph.add_node("rerank", rerank)
    graph.add_node("grade_evidence", grade_evidence)
    graph.add_node("rewrite_query", rewrite_query)
    graph.add_node("generate_answer", generate_answer)
    graph.add_node("verify_citations", verify_citations)
    graph.add_node("return_response", return_response)

    graph.set_entry_point("receive_question")
    graph.set_finish_point("return_response")

    graph.add_edge("receive_question", "classify_intent")
    graph.add_edge("classify_intent", "plan_retrieval")
    graph.add_edge("plan_retrieval", "route_retriever")
    graph.add_edge("route_retriever", "retrieve")
    graph.add_edge("retrieve", "rerank")
    graph.add_edge("rerank", "grade_evidence")

    graph.add_conditional_edges(
        "grade_evidence",
        _should_rewrite,
        {
            "rewrite_query": "rewrite_query",
            "generate_answer": "generate_answer",
        },
    )

    graph.add_edge("rewrite_query", "retrieve")
    graph.add_edge("generate_answer", "verify_citations")
    graph.add_edge("verify_citations", "return_response")
    graph.add_edge("return_response", END)

    return graph.compile()
