"""Explicit opt-in invocation; creates a fresh runtime registry for each run."""

from uuid import UUID
from typing import cast
from sqlalchemy.ext.asyncio import AsyncSession
from app.retrieval.hybrid import HybridRetriever
from .agent_models import AgentChatService, AgentMessage
from .agent_state import AgentState
from .graph import build_tool_graph, MAX_AGENT_CYCLES
from .prompts import AGENT_SYSTEM_PROMPT
from .handles import RuntimeHandleRegistry
from .execution.context import ExecutionContext
from .execution.executor import ToolExecutor


class ToolRagAgentService:
    def __init__(
        self,
        chat: AgentChatService,
        *,
        executor: ToolExecutor | None = None,
        max_cycles: int = MAX_AGENT_CYCLES,
    ):
        if (
            isinstance(max_cycles, bool)
            or not isinstance(max_cycles, int)
            or not 1 <= max_cycles <= MAX_AGENT_CYCLES
        ):
            raise ValueError("max_cycles must be application-owned and within 1..6")
        self.max_cycles = max_cycles
        self.graph = build_tool_graph(chat, executor)

    async def run(
        self,
        question: str,
        *,
        user_id: UUID,
        db: AsyncSession,
        retriever: HybridRetriever | None = None,
    ) -> AgentState:
        if not question.strip() or len(question) > 8000:
            raise ValueError("question must be nonblank and at most 8000 characters")
        context = ExecutionContext(
            user_id=user_id, db=db, handles=RuntimeHandleRegistry(), retriever=retriever
        )
        state: AgentState = {
            "original_question": question,
            "user_id": user_id,
            "messages": (
                AgentMessage(role="SYSTEM", text=AGENT_SYSTEM_PROMPT),
                AgentMessage(role="USER", text=question),
            ),
            "pending": None,
            "tool_history": (),
            "observations": (),
            "cycle_count": 0,
            "max_cycles": self.max_cycles,
            "final_answer": None,
            "evidence": (),
            "citation_handles": (),
            "retrieval_count": 0,
            "failure": None,
        }
        result = await self.graph.ainvoke(
            state, context=context, config={"recursion_limit": 2 * MAX_AGENT_CYCLES + 4}
        )
        return cast(AgentState, result)
