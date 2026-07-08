"""LangGraph state definition for the DriveMind agent workflow."""

from __future__ import annotations

import uuid
from typing import NotRequired, TypedDict

from app.agents.drive_graph.types import QueryIntent, RetrievalPlan
from app.retrieval.types import RetrievedChunk
from app.schemas.query import CitationItem


class DriveGraphState(TypedDict):
    """Mutable workflow state passed between LangGraph nodes."""

    question: str
    working_query: str
    user_id: uuid.UUID
    rewrite_count: int
    raw_chunks: list[RetrievedChunk]
    ranked_chunks: list[RetrievedChunk]
    citations: list[CitationItem]
    retrieval_count: int
    intent: NotRequired[QueryIntent]
    retrieval_plan: NotRequired[RetrievalPlan]
    active_retrievers: NotRequired[tuple[str, ...]]
    evidence_sufficient: NotRequired[bool]
    evidence_reason: NotRequired[str]
    answer: NotRequired[str]
    query_id: NotRequired[uuid.UUID]


def create_initial_state(
    *,
    question: str,
    user_id: uuid.UUID,
) -> DriveGraphState:
    """Build the initial graph state for a single-turn question."""
    normalized = question.strip()
    if not normalized:
        raise ValueError("Question must not be empty")

    return DriveGraphState(
        question=normalized,
        working_query=normalized,
        user_id=user_id,
        rewrite_count=0,
        raw_chunks=[],
        ranked_chunks=[],
        citations=[],
        retrieval_count=0,
    )
