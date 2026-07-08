"""LangGraph node implementations for Phase 8 M3 foundations."""

from __future__ import annotations

import re
import uuid as uuid_module
import asyncio
from typing import Any, Awaitable, Callable

from app.agents.drive_graph.state import DriveGraphState
from app.agents.drive_graph.types import RetrieverName
from app.agents.drive_graph.types import QueryIntent, RetrievalPlan
from app.core.config import Settings
from app.retrieval.base import Retriever
from app.retrieval.types import RetrievedChunk, RetrievalSource
from typing import cast
from app.retrieval.merge import reciprocal_rank_fusion_merge
from app.llm.prompts import NO_EVIDENCE_ANSWER


def receive_question(state: DriveGraphState) -> dict[str, Any]:
    """Normalize question text and reset core state for a new run."""
    normalized = state["question"].strip()
    if not normalized:
        raise ValueError("Question must not be empty")

    return {
        "question": normalized,
        "working_query": normalized,
        "rewrite_count": 0,
        "raw_chunks": [],
        "ranked_chunks": [],
        "citations": [],
        "retrieval_count": 0,
    }


def classify_intent(state: DriveGraphState) -> dict[str, Any]:
    """Classify query intent using deterministic heuristic rules."""
    intent = classify_intent_heuristic(state["working_query"])
    return {"intent": intent}


def plan_retrieval(state: DriveGraphState) -> dict[str, Any]:
    """Build a retrieval plan from the selected intent."""
    intent = state.get("intent")
    if intent is None:
        raise ValueError("intent must be set before plan_retrieval")
    plan = build_retrieval_plan(intent)
    return {"retrieval_plan": plan}


def route_retriever(state: DriveGraphState) -> dict[str, Any]:
    """Expose active retrievers from the retrieval plan."""
    plan = state.get("retrieval_plan")
    if plan is None:
        raise ValueError("retrieval_plan must be set before route_retriever")
    return {"active_retrievers": plan.retrievers}


def retrieve(state: DriveGraphState) -> dict[str, Any]:
    """Retrieve raw evidence chunks (stubbed: no DB/Qdrant calls in M2)."""
    return {
        "raw_chunks": [],
        "ranked_chunks": [],
        "retrieval_count": 0,
    }


def make_retrieve_node(
    *,
    retrievers: dict[RetrieverName, Retriever],
    settings: Settings,
) -> Callable[[DriveGraphState], Awaitable[dict[str, Any]]]:
    """Create a routed retrieval node using only active retrievers.

    The closure keeps node functions testable without relying on global state.
    """

    async def _retrieve(state: DriveGraphState) -> dict[str, Any]:
        active = state.get("active_retrievers")
        if not active:
            return {"raw_chunks": [], "ranked_chunks": [], "retrieval_count": 0}

        working_query = state["working_query"]

        tasks: list[Awaitable[list[RetrievedChunk]]] = []
        source_order: list[RetrieverName] = []
        for raw_name in active:
            if raw_name not in {"vector", "keyword", "metadata"}:
                raise ValueError(f"Unsupported active retriever name: {raw_name}")
            name = cast(RetrieverName, raw_name)

            retriever = retrievers.get(name)
            if retriever is None:
                raise ValueError(f"Missing retriever for active name: {name}")
            tasks.append(retriever.retrieve(working_query))
            source_order.append(name)

        results = await asyncio.gather(*tasks)
        chunks_by_source: dict[RetrievalSource, list[RetrievedChunk]] = {
            cast(RetrievalSource, name): chunks for name, chunks in zip(source_order, results)
        }
        merged = reciprocal_rank_fusion_merge(chunks_by_source, settings=settings)

        return {
            "raw_chunks": merged,
            "ranked_chunks": [],
            "retrieval_count": len(merged),
        }

    return _retrieve


def rerank(state: DriveGraphState) -> dict[str, Any]:
    """Rerank retrieved chunks (stub for M3)."""
    return {}


def grade_evidence(state: DriveGraphState) -> dict[str, Any]:
    """Grade evidence sufficiency (stub: always insufficient in M3)."""
    return {
        "evidence_sufficient": False,
        "evidence_reason": "M2 stub: no retrieval executed, so evidence is insufficient.",
    }


def rewrite_query(state: DriveGraphState) -> dict[str, Any]:
    """Rewrite the query to improve retrieval (stub for M3)."""
    next_count = state["rewrite_count"] + 1
    refined = f"{state['working_query']} (refined {next_count})"
    return {
        "working_query": refined,
        "rewrite_count": next_count,
    }


def generate_answer(state: DriveGraphState) -> dict[str, Any]:
    """Generate the final answer (stub for M3)."""
    return {
        "answer": NO_EVIDENCE_ANSWER,
        "citations": [],
    }


def verify_citations(state: DriveGraphState) -> dict[str, Any]:
    """Verify bracket citations (stub: no-op for M3)."""
    return {}


def return_response(state: DriveGraphState) -> dict[str, Any]:
    """Finalize the state for a RagResult (stub)."""
    return {
        "query_id": uuid_module.uuid4(),
    }


def classify_intent_heuristic(question: str) -> QueryIntent:
    """Classify query intent using lightweight deterministic rules.

    This keeps M3 reliable and testable. LLM-assisted fallback can be layered in M4+.
    """
    normalized = question.strip().lower()
    if not normalized:
        return QueryIntent.UNKNOWN

    if re.search(r"\b(latest|recent|newest)\b", normalized):
        return QueryIntent.FIND_LATEST

    if re.search(r"\b(summarize|summary|overview)\b", normalized):
        return QueryIntent.SUMMARIZE_TOPIC

    if re.search(r"\b(list|show|filter|only)\b", normalized) and re.search(
        r"\b(files?|docs?|documents?|pdf|docx|txt|folder)\b",
        normalized,
    ):
        return QueryIntent.LIST_OR_FILTER

    if re.search(r"\b(mention|mentions|mentioning|contains|exact|keyword|phrase)\b", normalized):
        return QueryIntent.KEYWORD_SEARCH

    if re.search(r"\b(what|why|how|explain|tell me)\b", normalized):
        return QueryIntent.SEMANTIC_QUESTION

    return QueryIntent.UNKNOWN


def build_retrieval_plan(intent: QueryIntent) -> RetrievalPlan:
    """Map intent to retriever strategy for later nodes."""
    if intent is QueryIntent.FIND_LATEST:
        return RetrievalPlan(
            intent=intent,
            retrievers=("metadata", "keyword"),
            sort_by_modified_desc=True,
        )

    if intent is QueryIntent.KEYWORD_SEARCH:
        return RetrievalPlan(intent=intent, retrievers=("keyword", "vector"))

    if intent is QueryIntent.SEMANTIC_QUESTION:
        return RetrievalPlan(intent=intent, retrievers=("vector", "keyword"))

    if intent is QueryIntent.SUMMARIZE_TOPIC:
        return RetrievalPlan(intent=intent, retrievers=("vector", "keyword", "metadata"))

    if intent is QueryIntent.LIST_OR_FILTER:
        return RetrievalPlan(intent=intent, retrievers=("metadata",))

    return RetrievalPlan(intent=QueryIntent.UNKNOWN, retrievers=("vector", "keyword", "metadata"))
