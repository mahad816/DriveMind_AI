"""LangGraph state definition for the DriveMind agent workflow."""

from __future__ import annotations

import uuid
from typing import NotRequired, TypedDict

from app.agents.drive_graph.types import QueryIntent, RetrievalPlan
from app.retrieval.types import RetrievedChunk
from app.schemas.query import CitationItem
from app.routing.intent_frame.scope import RetrievalScope, EligibleCollectionScope


class DriveGraphState(TypedDict):
    """Mutable workflow state passed between LangGraph nodes."""

    question: str
    working_query: str
    user_id: uuid.UUID
    retrieval_scope: RetrievalScope
    rewrite_count: int
    raw_chunks: list[RetrievedChunk]
    ranked_chunks: list[RetrievedChunk]
    citations: list[CitationItem]
    retrieval_count: int
    # Set by the runner so conditional routing can cap rewrite loops safely.
    max_rewrite_attempts: NotRequired[int]
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
    scope: RetrievalScope | None = None,
) -> DriveGraphState:
    """Build the initial graph state for a single-turn question."""
    if not isinstance(user_id, uuid.UUID):
        raise ValueError("A valid corpus owner UUID is required")
    normalized = question.strip()
    if not normalized:
        raise ValueError("Question must not be empty")

    return DriveGraphState(
        question=normalized,
        working_query=normalized,
        user_id=user_id,
        retrieval_scope=scope if scope is not None else EligibleCollectionScope(),
        rewrite_count=0,
        raw_chunks=[],
        ranked_chunks=[],
        citations=[],
        retrieval_count=0,
    )
