"""Runner for the Phase 8 DriveMind LangGraph agent (M2: skeleton only)."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.drive_graph.graph import build_drive_graph
from app.agents.drive_graph.state import create_initial_state
from app.core.config import Settings
from app.services.rag_service import RagResult


async def run_drive_graph(
    db: AsyncSession,
    settings: Settings,
    *,
    question: str,
    user_id: uuid.UUID,
) -> RagResult:
    """Execute the DriveMind LangGraph skeleton for a single question.

    Note: Phase 8 M2 uses stubbed nodes, so `db` is currently unused.
    """
    _ = db

    state = create_initial_state(question=question, user_id=user_id)
    state["max_rewrite_attempts"] = settings.agent_max_rewrite_attempts

    compiled = build_drive_graph()
    final_state = compiled.invoke(state)

    query_id = final_state.get("query_id") or uuid.uuid4()
    return RagResult(
        query_id=query_id,
        user_id=user_id,
        question=final_state["question"],
        answer=final_state.get("answer", ""),  # stub always sets this
        citations=final_state.get("citations", []),
        retrieval_count=final_state.get("retrieval_count", 0),
    )
