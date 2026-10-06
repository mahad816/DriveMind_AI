"""Internal graph state; only messages and tool definitions reach the model."""

from dataclasses import dataclass
from typing import Literal, TypedDict
from uuid import UUID
from .agent_models import AgentMessage, AgentStepResult, ToolCallRequest
from .execution.executor import ToolExecutionResult
from .handles import SourceHandle
from app.routing.intent_frame.evidence import EvidenceSection

Failure = Literal[
    "PROVIDER_ERROR", "MALFORMED_RESPONSE", "CYCLE_LIMIT", "STATE_ERROR", "MESSAGE_LIMIT"
]


@dataclass(frozen=True)
class ToolExecutionRecord:
    call: ToolCallRequest
    result: ToolExecutionResult


class AgentState(TypedDict):
    original_question: str
    user_id: UUID
    messages: tuple[AgentMessage, ...]
    pending: AgentStepResult | None
    tool_history: tuple[ToolExecutionRecord, ...]
    observations: tuple[AgentStepResult, ...]
    cycle_count: int
    max_cycles: int
    final_answer: str | None
    evidence: tuple[EvidenceSection, ...]
    citation_handles: tuple[SourceHandle, ...]
    retrieval_count: int
    failure: Failure | None
