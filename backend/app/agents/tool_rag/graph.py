"""One agent, sequential tools, bounded cycles; no routing/planning/rewrites."""

import json
from typing import Literal
from langgraph.graph import START, END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from .agent_models import (
    AgentChatService,
    AgentMessage,
    AgentStepResult,
    AgentResponseError,
    ToolDefinition,
)
from .agent_state import AgentState, ToolExecutionRecord
from .execution.context import ExecutionContext
from .execution.executor import ToolExecutor, ToolExecutionResult
from .errors import ToolError, ToolErrorCode
from .contracts import (
    SearchKnowledgeResult,
    FileEvidenceResult,
    SearchKnowledgePayload,
    FileEvidencePayload,
)

from .finalization import finalize_answer

MAX_AGENT_CYCLES = 6
MAX_MODEL_HISTORY_CHARS = 128000
CYCLE_LIMIT_MESSAGE = "I wasn't able to complete that request within the available tool steps."
FAILURE_MESSAGE = "I wasn't able to complete that request safely. Please try again."


def route_after_agent(state: AgentState) -> Literal["FINAL", "TOOLS", "ERROR"]:
    if state["failure"] is not None:
        return "ERROR"
    pending = state["pending"]
    if pending is None:
        return "ERROR"
    return "TOOLS" if pending.tool_calls else "FINAL"


def build_tool_graph(
    chat: AgentChatService, executor: ToolExecutor | None = None
) -> CompiledStateGraph[AgentState, ExecutionContext, AgentState, AgentState]:
    execution = executor or ToolExecutor()
    definitions = tuple(ToolDefinition.model_validate(d) for d in execution.registry.definitions())

    async def agent(state: AgentState) -> dict[str, object]:
        count = state["cycle_count"]
        if not 1 <= state["max_cycles"] <= MAX_AGENT_CYCLES or count < 0:
            return {"failure": "STATE_ERROR"}
        if count >= state["max_cycles"]:
            return {"failure": "CYCLE_LIMIT"}
        if sum(len(m.model_dump_json()) for m in state["messages"]) > MAX_MODEL_HISTORY_CHARS:
            return {"failure": "MESSAGE_LIMIT"}
        try:
            step = await chat.step(messages=state["messages"], tools=definitions)
            step = AgentStepResult.model_validate_json(step.model_dump_json())
        except AgentResponseError:
            return {"cycle_count": count + 1, "failure": "MALFORMED_RESPONSE"}
        except Exception:
            return {"cycle_count": count + 1, "failure": "PROVIDER_ERROR"}
        previous = {record.call.call_id for record in state["tool_history"]}
        if previous.intersection(t.call_id for t in step.tool_calls):
            return {"cycle_count": count + 1, "failure": "STATE_ERROR"}
        return {
            "cycle_count": count + 1,
            "pending": step,
            "messages": state["messages"]
            + (AgentMessage(role="ASSISTANT", text=step.text, tool_calls=step.tool_calls),),
            "observations": state["observations"] + (step,),
            "failure": "CYCLE_LIMIT"
            if step.tool_calls and count + 1 >= state["max_cycles"]
            else None,
        }

    async def execute_tools(
        state: AgentState, runtime: Runtime[ExecutionContext]
    ) -> dict[str, object]:
        pending = state["pending"]
        context = runtime.context
        if pending is None or context is None or context.user_id != state["user_id"]:
            return {"failure": "STATE_ERROR"}
        messages = list(state["messages"])
        history = list(state["tool_history"])
        evidence = list(state["evidence"])
        citations = list(state["citation_handles"])
        for call in pending.tool_calls:
            try:
                if call.argument_error:
                    error = ToolError(code=ToolErrorCode.INVALID_ARGUMENT)
                    result = ToolExecutionResult(
                        internal_result=None, llm_result=error.to_llm_payload(), error=error
                    )
                else:
                    result = await execution.execute(
                        call.tool_name, json.dumps(call.arguments, allow_nan=False), context
                    )
            except Exception:
                error = ToolError(code=ToolErrorCode.INTERNAL_ERROR)
                result = ToolExecutionResult(
                    internal_result=None, llm_result=error.to_llm_payload(), error=error
                )
            messages.append(
                AgentMessage(
                    role="TOOL", call_id=call.call_id, text=result.llm_result.model_dump_json()
                )
            )
            history.append(ToolExecutionRecord(call=call, result=result))
            if isinstance(result.internal_result, (SearchKnowledgeResult, FileEvidenceResult)):
                for section in result.internal_result.sections:
                    if section not in evidence:
                        evidence.append(section)
            if isinstance(result.llm_result, (SearchKnowledgePayload, FileEvidencePayload)):
                for section_payload in result.llm_result.sections:
                    for citation in section_payload.citations:
                        if citation.source_handle not in citations:
                            citations.append(citation.source_handle)
        return {
            "messages": tuple(messages),
            "tool_history": tuple(history),
            "evidence": tuple(evidence),
            "citation_handles": tuple(citations),
            "retrieval_count": len({m.chunk_id for section in evidence for m in section.members}),
            "pending": None,
        }

    def finalize(state: AgentState, runtime: Runtime[ExecutionContext]) -> dict[str, object]:
        pending = state["pending"]
        if pending is None or not pending.text or pending.tool_calls:
            return {"failure": "STATE_ERROR", "final_answer": FAILURE_MESSAGE}
        try:
            answer = finalize_answer(pending.text.strip(), state, runtime.context.handles)
        except Exception:
            return {
                "failure": "UNSAFE_FINAL_OUTPUT",
                "final_answer": FAILURE_MESSAGE,
                "citations": (),
            }
        return {"final_answer": answer.answer, "citations": answer.citations}

    def fail_safe(state: AgentState) -> dict[str, object]:
        answer = CYCLE_LIMIT_MESSAGE if state["failure"] == "CYCLE_LIMIT" else FAILURE_MESSAGE
        messages = list(state["messages"])
        # Close any unexecuted assistant calls canonically; no more provider calls follow.
        answered = {m.call_id for m in messages if m.role == "TOOL"}
        if messages and messages[-1].tool_calls:
            for call in messages[-1].tool_calls:
                if call.call_id not in answered:
                    messages.append(
                        AgentMessage(
                            role="TOOL",
                            call_id=call.call_id,
                            text=json.dumps(
                                {"code": state["failure"] or "STATE_ERROR", "message": answer}
                            ),
                        )
                    )
        messages.append(AgentMessage(role="ASSISTANT", text=answer))
        return {"final_answer": answer, "messages": tuple(messages)}

    graph = StateGraph(AgentState, context_schema=ExecutionContext)
    graph.add_node("agent", agent)
    graph.add_node("execute_tools", execute_tools)
    graph.add_node("finalize", finalize)
    graph.add_node("fail_safe", fail_safe)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        route_after_agent,
        {"FINAL": "finalize", "TOOLS": "execute_tools", "ERROR": "fail_safe"},
    )
    graph.add_conditional_edges(
        "execute_tools",
        lambda state: "ERROR" if state["failure"] else "AGENT",
        {"ERROR": "fail_safe", "AGENT": "agent"},
    )
    graph.add_edge("finalize", END)
    graph.add_edge("fail_safe", END)
    return graph.compile()
