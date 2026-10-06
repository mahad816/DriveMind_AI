"""Service-level opt-in orchestration. No SQL, classifier, or semantic fallback."""

import asyncio
import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from time import perf_counter
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from app.agents.tool_rag.agent_models import AgentChatService, AgentMessage
from app.agents.tool_rag.agent_service import ToolRagAgentService
from app.agents.tool_rag.contracts import (
    FileEvidencePayload,
    FileEvidenceResult,
    SearchKnowledgeResult,
)
from app.agents.tool_rag.errors import ToolErrorCode
from app.core.config import Settings
from app.llm.base import ChatError
from app.llm.prompts import no_evidence_answer
from app.llm.openai_agent_service import OpenAIAgentChatService
from app.retrieval.hybrid import HybridRetriever
from app.schemas.chat import ChatHistoryTurn
from app.schemas.query import CitationItem
from app.services.conversation_history import bounded_rewrite_history

logger = logging.getLogger(__name__)
TOOL_AGENT_TIMEOUT_SECONDS = 120.0
_IDENTIFIER = re.compile(
    r"\b(?:file|source|evidence)_\d+\b|\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b", re.I
)
TRUNCATION_NOTICE = "Only a bounded portion of the indexed document was available; this answer is based on that portion, not guaranteed coverage of the entire file."


@dataclass(frozen=True)
class ToolAgentResult:
    answer: str
    citations: tuple[CitationItem, ...]
    retrieval_count: int


def bounded_agent_history(
    history: Sequence[ChatHistoryTurn | Mapping[str, str]],
) -> tuple[AgentMessage, ...]:
    """Reuse the existing six-message/6000-character bound; no tool-history replay."""
    safe = [
        {
            "role": turn["role"],
            "text": _IDENTIFIER.sub("[unavailable prior identifier]", turn["text"]),
        }
        for turn in bounded_rewrite_history(history)
    ]
    return tuple(
        AgentMessage(role="USER" if turn["role"] == "user" else "ASSISTANT", text=turn["text"])
        for turn in bounded_rewrite_history(safe)
    )


class ToolAgentAdapter:
    def __init__(
        self,
        db: AsyncSession,
        settings: Settings,
        *,
        chat: AgentChatService | None = None,
        agent: ToolRagAgentService | None = None,
        retriever: HybridRetriever | None = None,
    ):
        self.db = db
        self.settings = settings
        self.chat = chat
        self.agent = agent
        self.retriever = retriever

    async def answer(
        self,
        question: str,
        *,
        user_id: UUID,
        history: Sequence[ChatHistoryTurn | Mapping[str, str]],
        history_window_complete: bool,
    ) -> ToolAgentResult:
        started = perf_counter()
        owned_chat = (
            OpenAIAgentChatService(self.settings)
            if self.chat is None and self.agent is None
            else None
        )
        chat = self.chat or owned_chat
        if self.agent is not None:
            agent = self.agent
        else:
            assert chat is not None
            agent = ToolRagAgentService(chat)
        try:
            async with asyncio.timeout(TOOL_AGENT_TIMEOUT_SECONDS):
                state = await agent.run(
                    question,
                    user_id=user_id,
                    db=self.db,
                    retriever=self.retriever or HybridRetriever(self.db, self.settings),
                    history=bounded_agent_history(history),
                    history_window_complete=history_window_complete,
                )
            tool_errors = tuple(
                h.result.error.code for h in state["tool_history"] if h.result.error
            )
            stats = {
                "path": "tool_agent",
                "llm_steps": state["cycle_count"],
                "tool_names": [
                    h.call.tool_name
                    if h.call.tool_name
                    in {"files_query", "resolve_file", "search_knowledge", "file_evidence"}
                    else "UNKNOWN"
                    for h in state["tool_history"]
                ],
                "tool_count": len(state["tool_history"]),
                "retrieval_count": state["retrieval_count"],
                "outcome": state["failure"]
                or (
                    "INTERNAL_ERROR"
                    if ToolErrorCode.INTERNAL_ERROR in tool_errors
                    else "UNSUPPORTED_SCOPE"
                    if ToolErrorCode.UNSUPPORTED_SCOPE in tool_errors
                    else "TOOL_LIMITATION"
                    if tool_errors
                    else "COMPLETED"
                ),
                "cycle_limit": state["failure"] == "CYCLE_LIMIT",
                "unsupported_scope": ToolErrorCode.UNSUPPORTED_SCOPE in tool_errors,
                "duration_ms": (perf_counter() - started) * 1000,
            }
            logger.info("rag_execution %s", json.dumps(stats, sort_keys=True))
            if (
                state["failure"] not in (None, "CYCLE_LIMIT", "MESSAGE_LIMIT")
                or ToolErrorCode.INTERNAL_ERROR in tool_errors
            ):
                raise ChatError("The tool agent could not complete safely.")
            answer = state["final_answer"]
            if not answer:
                raise ChatError("The tool agent returned no answer.")
            # An empty successful read is not proof that a fact is absent from a file.
            # Use the established safe envelope instead of ungrounded model conclusions.
            if (
                state["failure"] is None
                and not state["evidence"]
                and any(
                    isinstance(
                        h.result.internal_result, (FileEvidenceResult, SearchKnowledgeResult)
                    )
                    for h in state["tool_history"]
                )
            ):
                answer = no_evidence_answer(demo_mode=self.settings.demo_mode)
            if any(
                isinstance(h.result.llm_result, FileEvidencePayload)
                and h.result.llm_result.truncated
                for h in state["tool_history"]
            ):
                answer = TRUNCATION_NOTICE + "\n\n" + answer
            return ToolAgentResult(
                answer=answer,
                citations=state["citations"],
                retrieval_count=state["retrieval_count"],
            )
        except TimeoutError:
            logger.info("rag_execution path=tool_agent outcome=TIMEOUT")
            raise ChatError("The tool agent timed out safely.") from None
        except ChatError:
            raise
        except Exception:
            logger.info("rag_execution path=tool_agent outcome=INTERNAL_ERROR")
            raise ChatError("The tool agent could not complete safely.") from None
        finally:
            if owned_chat is not None:
                try:
                    async with asyncio.timeout(5):
                        await owned_chat.aclose()
                except Exception:
                    logger.info("rag_execution path=tool_agent outcome=CLIENT_CLEANUP_ERROR")
                    raise ChatError("The tool agent could not complete safely.") from None
