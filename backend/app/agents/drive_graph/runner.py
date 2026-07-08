"""Runner for the Phase 8 DriveMind LangGraph agent."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.drive_graph.graph import build_drive_graph
from app.agents.drive_graph.state import create_initial_state
from app.agents.drive_graph.types import RetrieverName
from app.core.config import Settings
from app.llm.base import ChatService
from app.retrieval.base import Retriever
from app.retrieval.keyword import KeywordRetriever
from app.retrieval.metadata import MetadataRetriever
from app.retrieval.vector import VectorRetriever
from app.services.rag_service import RagResult


async def run_drive_graph(
    db: AsyncSession,
    settings: Settings,
    *,
    question: str,
    user_id: uuid.UUID,
    chat_service: ChatService | None = None,
    retrievers: dict[RetrieverName, Retriever] | None = None,
) -> RagResult:
    """Execute the DriveMind LangGraph workflow for a single question."""
    active_retrievers = retrievers or {
        "vector": VectorRetriever(db, settings),
        "keyword": KeywordRetriever(db, settings),
        "metadata": MetadataRetriever(db, settings),
    }

    state = create_initial_state(question=question, user_id=user_id)
    state["max_rewrite_attempts"] = settings.agent_max_rewrite_attempts

    compiled = build_drive_graph(
        retrievers=active_retrievers,
        settings=settings,
        chat_service=chat_service,
    )
    final_state = await compiled.ainvoke(state)

    query_id = final_state.get("query_id") or uuid.uuid4()
    return RagResult(
        query_id=query_id,
        user_id=user_id,
        question=final_state["question"],
        answer=final_state.get("answer", ""),  # stub always sets this
        citations=final_state.get("citations", []),
        retrieval_count=final_state.get("retrieval_count", 0),
    )
