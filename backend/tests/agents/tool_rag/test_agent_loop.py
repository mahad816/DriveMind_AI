"""Bounded native tool-agent workflows, using D1 execution and zero network."""

import json
from collections.abc import Sequence
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID
from typing import cast

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tool_rag.agent_models import (
    AgentMessage,
    AgentStepResult,
    ToolCallRequest,
    ToolDefinition,
    AgentResponseError,
)
from app.agents.tool_rag.agent_service import ToolRagAgentService
from app.agents.tool_rag.graph import CYCLE_LIMIT_MESSAGE
from app.agents.tool_rag.contracts import FileEvidencePayload
from app.agents.tool_rag.execution.executor import ToolExecutor
from app.agents.tool_rag.registry import ToolRegistry
from app.llm.openai_agent_service import OpenAIAgentChatService
from app.llm.base import ChatError
from app.core.config import Settings
from tests.agents.tool_rag.test_tool_execution import InventoryDB, file, chunk, USER


class ScriptChat:
    def __init__(self, steps):
        self.steps = list(steps)
        self.received = []

    async def step(
        self, *, messages: Sequence[AgentMessage], tools: Sequence[ToolDefinition]
    ) -> AgentStepResult:
        self.received.append(tuple(messages))
        assert {t.name for t in tools} == {
            "files_query",
            "resolve_file",
            "search_knowledge",
            "file_evidence",
        }
        value = self.steps.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def call(name, args, identifier="call_1"):
    return AgentStepResult(
        tool_calls=(ToolCallRequest(call_id=identifier, tool_name=name, arguments=args),)
    )


def inventory(operation="LIST"):
    return {"operation": operation, "scope": {"kind": "ALL_ELIGIBLE_INDEXED_FILES"}}


def evidence_args():
    return {"file_handle": {"kind": "FILE", "value": "file_1"}, "query": "summary"}


class RecordingExecutor(ToolExecutor):
    def __init__(self):
        super().__init__()
        self.contexts = []
        self.calls = []

    async def execute(self, name, arguments_json, context):
        self.contexts.append(context)
        self.calls.append(name)
        return await super().execute(name, arguments_json, context)


async def run(steps, question="Synthetic question", files=None, executor=None, max_cycles=6):
    chat = ScriptChat(steps)
    db = InventoryDB(files if files is not None else [file()])
    retriever = AsyncMock()
    retriever.retrieve.return_value = [chunk()]
    service = ToolRagAgentService(chat, executor=executor, max_cycles=max_cycles)
    state = await service.run(
        question, user_id=USER, db=cast(AsyncSession, db), retriever=retriever
    )
    return state, chat, retriever


def test_domain_final_and_multiple_calls():
    assert AgentStepResult(text="Hello").tool_calls == ()
    a = call("files_query", inventory()).tool_calls[0]
    b = call("files_query", inventory("COUNT"), "call_2").tool_calls[0]
    assert len(AgentStepResult(tool_calls=(a, b)).tool_calls) == 2
    for data in [
        {},
        {"text": "   "},
        {"tool_calls": [{"call_id": "", "tool_name": "files_query", "arguments": {}}]},
        {"tool_calls": [{"call_id": "id", "tool_name": "files_query", "arguments": []}]},
        {"tool_calls": [a.model_dump(), a.model_dump()]},
    ]:
        with pytest.raises(ValidationError):
            AgentStepResult.model_validate_json(json.dumps(data))
    with pytest.raises(ValidationError):
        AgentMessage.model_validate({"role": "UNKNOWN", "text": "x"})
    with pytest.raises(ValidationError):
        AgentMessage(role="TOOL", text="x")


@pytest.mark.asyncio
async def test_direct_conversation_zero_tools():
    state, chat, retriever = await run([AgentStepResult(text="Hello!")], question="Hello")
    assert state["final_answer"] == "Hello!" and not state["tool_history"]
    assert state["cycle_count"] == 1 and len(chat.received) == 1
    assert state["original_question"] == "Hello"
    retriever.retrieve.assert_not_awaited()


@pytest.mark.asyncio
async def test_knowledge_search_evidence_history():
    state, chat, _ = await run(
        [
            call(
                "search_knowledge",
                {"query": "refund policy", "scope": {"kind": "ALL_ELIGIBLE_INDEXED_FILES"}},
            ),
            AgentStepResult(text="Approval is required. [source_1]"),
        ]
    )
    assert len(state["tool_history"]) == 1 and len(state["evidence"]) == 1
    assert state["retrieval_count"] == 1 and state["citation_handles"][0].value == "source_1"
    assert chat.received[1][-1].role == "TOOL" and chat.received[1][-1].call_id == "call_1"
    assert state["evidence"][0].combined_text == chunk().text


@pytest.mark.asyncio
@pytest.mark.parametrize("producer", ["LIST", "LATEST"])
async def test_actual_producer_handle_to_evidence(producer):
    executor = RecordingExecutor()
    state, chat, retriever = await run(
        [
            call("files_query", inventory(producer)),
            call("file_evidence", evidence_args(), "call_2"),
            AgentStepResult(text="Here is the summary. [source_1]"),
        ],
        question="List my files and summarize the first one.",
        files=[file(), file(11, "z.pdf")],
        executor=executor,
    )
    assert executor.calls == ["files_query", "file_evidence"]
    assert executor.contexts[0].handles is executor.contexts[1].handles
    payload = state["tool_history"][1].result.llm_result
    assert isinstance(payload, FileEvidencePayload)
    assert executor.contexts[0].handles.resolve_file(payload.file_handle) == UUID(int=10)
    assert retriever.retrieve.await_args.args[0].scope.file_ids == (UUID(int=10),)
    history = json.dumps(
        [m.model_dump(mode="json") for messages in chat.received for m in messages]
    )
    assert all(str(i) not in history for i in [USER, UUID(int=10), UUID(int=90), UUID(int=100)])
    assert state["failure"] is None and len(state["evidence"]) == 1
    assert [m.call_id for m in state["messages"] if m.role == "TOOL"] == ["call_1", "call_2"]


@pytest.mark.asyncio
async def test_resolve_then_evidence():
    state, _, retriever = await run(
        [
            call("resolve_file", {"reference": "report.pdf"}),
            call("file_evidence", evidence_args(), "call_2"),
            AgentStepResult(text="Summary [source_1]"),
        ]
    )
    assert [record.call.tool_name for record in state["tool_history"]] == [
        "resolve_file",
        "file_evidence",
    ]
    retriever.retrieve.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("files,kind", [([], "NOT_FOUND"), ([file(), file(11)], "AMBIGUOUS")])
async def test_not_found_or_ambiguous_explanation(files, kind):
    state, chat, retriever = await run(
        [
            call("resolve_file", {"reference": "report.pdf"}),
            AgentStepResult(text="Please clarify the file reference."),
        ],
        files=files,
    )
    assert kind in chat.received[1][-1].text
    assert state["failure"] is None
    retriever.retrieve.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,args",
    [
        ("unknown", {}),
        ("files_query", {"operation": "DELETE"}),
        ("file_evidence", {"file_handle": {"kind": "FILE", "value": "file_99"}, "query": "x"}),
        ("file_evidence", {"file_handle": {"kind": "SOURCE", "value": "source_1"}, "query": "x"}),
        ("search_knowledge", {"query": "x", "scope": {"kind": "FOLDER_REFERENCE"}}),
    ],
)
async def test_invalid_calls_safe_tool_messages_no_fallback(name, args):
    state, chat, retriever = await run(
        [call(name, args), AgentStepResult(text="I cannot complete that tool request.")]
    )
    assert state["tool_history"][0].result.error is not None
    assert chat.received[1][-1].role == "TOOL"
    assert "code" in chat.received[1][-1].text
    retriever.retrieve.assert_not_awaited()


@pytest.mark.asyncio
async def test_malformed_arguments_safe_tool_error_not_execution():
    bad = AgentStepResult(
        tool_calls=(
            ToolCallRequest(
                call_id="bad",
                tool_name="files_query",
                arguments={},
                argument_error="INVALID_ARGUMENT",
            ),
        )
    )
    executor = RecordingExecutor()
    state, chat, _ = await run([bad, AgentStepResult(text="Please clarify.")], executor=executor)
    assert not executor.calls and "INVALID_ARGUMENT" in chat.received[1][-1].text
    assert state["tool_history"][0].call.call_id == "bad"


@pytest.mark.asyncio
async def test_multiple_calls_sequential_provider_order():
    executor = RecordingExecutor()
    step = AgentStepResult(
        tool_calls=(
            call("files_query", inventory("COUNT"), "a").tool_calls[0],
            call("files_query", inventory("LIST"), "b").tool_calls[0],
        )
    )
    state, chat, _ = await run([step, AgentStepResult(text="Done.")], executor=executor)
    assert executor.calls == ["files_query", "files_query"]
    assert [m.call_id for m in chat.received[1] if m.role == "TOOL"] == ["a", "b"]
    assert len(state["tool_history"]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["files_query", "unknown"])
async def test_cycle_limit_no_extra_tools_or_llm(name):
    executor = RecordingExecutor()
    steps = [
        call(name, inventory() if name == "files_query" else {}, f"call_{i}") for i in range(6)
    ]
    state, chat, _ = await run(steps, executor=executor)
    assert state["failure"] == "CYCLE_LIMIT" and state["final_answer"] == CYCLE_LIMIT_MESSAGE
    assert len(chat.received) == 6 and state["cycle_count"] == 6
    assert len(executor.calls) == len(state["tool_history"]) == 5
    assert state["messages"][-2].call_id == "call_5" and state["messages"][-2].role == "TOOL"


@pytest.mark.asyncio
async def test_registry_isolated_between_runs():
    executor = RecordingExecutor()
    chat = ScriptChat(
        [
            call("files_query", inventory()),
            AgentStepResult(text="Done"),
            call("files_query", inventory()),
            AgentStepResult(text="Done"),
        ]
    )
    service = ToolRagAgentService(chat, executor=executor)
    for _ in range(2):
        await service.run("List files", user_id=USER, db=cast(AsyncSession, InventoryDB([file()])))
    assert executor.contexts[0].handles is not executor.contexts[1].handles
    assert executor.contexts[0].handles.register_file(UUID(int=10)).value == "file_1"
    assert executor.contexts[1].handles.register_file(UUID(int=10)).value == "file_1"


@pytest.mark.asyncio
async def test_private_errors_and_provider_errors_hidden():
    _, _, _ = await run(
        [call("files_query", inventory("COUNT")), AgentStepResult(text="Unable to count.")],
        files=None,
    )
    # Independent provider failure never includes the exception body in public history.
    failed, _, _ = await run([ChatError("private credential traceback")])
    assert failed["failure"] == "PROVIDER_ERROR"
    assert "private" not in json.dumps([m.model_dump(mode="json") for m in failed["messages"]])
    malformed, _, _ = await run([AgentResponseError("private response")])
    assert malformed["failure"] == "MALFORMED_RESPONSE"


def provider_response(text=None, calls=()):
    return SimpleNamespace(
        model="synthetic-model",
        usage=SimpleNamespace(prompt_tokens=30, completion_tokens=10),
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=text,
                    tool_calls=[
                        SimpleNamespace(
                            type="function", id=i, function=SimpleNamespace(name=n, arguments=a)
                        )
                        for i, n, a in calls
                    ],
                )
            )
        ],
    )


def adapter(response):
    client = AsyncMock()
    client.chat.completions.create.return_value = response
    return OpenAIAgentChatService(Settings(), client=client), client


def definitions():
    return tuple(ToolDefinition.model_validate(d) for d in ToolRegistry().definitions())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        provider_response("Hello"),
        provider_response(calls=(("a", "files_query", json.dumps(inventory())),)),
        provider_response(
            calls=(
                ("a", "files_query", json.dumps(inventory())),
                ("b", "resolve_file", '{"reference":"report.pdf"}'),
            )
        ),
    ],
)
async def test_native_openai_final_and_calls(response):
    service, client = adapter(response)
    result = await service.step(
        messages=(AgentMessage(role="USER", text="question"),), tools=definitions()
    )
    assert result.text or result.tool_calls
    kwargs = client.chat.completions.create.await_args.kwargs
    assert kwargs["tool_choice"] == "auto" and len(kwargs["tools"]) == 4
    assert all(t["type"] == "function" for t in kwargs["tools"])
    assert kwargs["messages"][0] == {"role": "user", "content": "question"}
    assert result.usage.input_tokens == 30
    client.chat.completions.create.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw", ["{bad", "[]", "null", '{"operation":"LIST","operation":"COUNT"}', '{"number":NaN}']
)
async def test_malformed_native_arguments_rejected(raw):
    service, client = adapter(provider_response(calls=(("a", "files_query", raw),)))
    result = await service.step(
        messages=(AgentMessage(role="USER", text="question"),), tools=definitions()
    )
    assert (
        result.tool_calls[0].argument_error == "INVALID_ARGUMENT"
        and result.tool_calls[0].arguments == {}
    )
    client.chat.completions.create.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        provider_response(),
        provider_response(calls=(("", "files_query", "{}"),)),
        provider_response(calls=(("a", "", "{}"),)),
    ],
)
async def test_malformed_provider_response_rejected(response):
    service, _ = adapter(response)
    with pytest.raises(AgentResponseError):
        await service.step(
            messages=(AgentMessage(role="USER", text="question"),), tools=definitions()
        )


@pytest.mark.asyncio
async def test_native_history_call_ids_and_safe_provider_error():
    service, client = adapter(provider_response("Done"))
    messages = (
        AgentMessage(role="USER", text="Count"),
        AgentMessage(
            role="ASSISTANT", tool_calls=call("files_query", inventory("COUNT"), "a").tool_calls
        ),
        AgentMessage(role="TOOL", call_id="a", text='{"result":{"kind":"COUNT","count":2}}'),
    )
    await service.step(messages=messages, tools=definitions())
    sent = client.chat.completions.create.await_args.kwargs["messages"]
    assert sent[1]["tool_calls"][0]["id"] == sent[2]["tool_call_id"] == "a"
    client.chat.completions.create.side_effect = RuntimeError("private API key")
    with pytest.raises(ChatError, match="Agent provider request failed") as error:
        await service.step(messages=messages, tools=definitions())
    assert "private" not in str(error.value)


@pytest.mark.asyncio
async def test_executor_private_diagnostic_never_enters_history():
    db = InventoryDB([file()])
    db.scalar = AsyncMock(side_effect=RuntimeError("private credential and SQL traceback"))
    chat = ScriptChat(
        [call("files_query", inventory("COUNT")), AgentStepResult(text="Unable to count safely.")]
    )
    state = await ToolRagAgentService(chat).run(
        "Count files", user_id=USER, db=cast(AsyncSession, db)
    )
    error = state["tool_history"][0].result.error
    assert error is not None and error.private_diagnostic is not None
    assert "private" in error.private_diagnostic
    assert "private" not in json.dumps([m.model_dump(mode="json") for m in state["messages"]])
    assert state["failure"] is None


@pytest.mark.asyncio
async def test_duplicate_call_id_and_history_budget_stop_safely(monkeypatch):
    executor = RecordingExecutor()
    state, _, _ = await run(
        [call("files_query", inventory(), "same"), call("files_query", inventory(), "same")],
        executor=executor,
    )
    assert state["failure"] == "STATE_ERROR" and len(executor.calls) == 1
    from app.agents.tool_rag import graph

    monkeypatch.setattr(graph, "MAX_MODEL_HISTORY_CHARS", 1)
    state, chat, _ = await run([])
    assert state["failure"] == "MESSAGE_LIMIT" and not chat.received


@pytest.mark.parametrize("limit", [0, 7, True])
def test_max_cycles_application_bounded(limit):
    with pytest.raises(ValueError):
        ToolRagAgentService(ScriptChat([]), max_cycles=limit)


@pytest.mark.asyncio
async def test_prose_is_not_parsed_into_tools():
    service, client = adapter(provider_response("<tool_call>files_query</tool_call>"))
    out = await service.step(
        messages=(AgentMessage(role="USER", text="question"),), tools=definitions()
    )
    assert not out.tool_calls and out.text == "<tool_call>files_query</tool_call>"
    client.chat.completions.create.assert_awaited_once()


def test_new_runtime_has_no_old_router_or_jev_dependency():
    import ast
    from pathlib import Path
    import app.agents.tool_rag

    root = Path(app.agents.tool_rag.__file__).parent
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text())
        names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                names.append(node.module or "")
            if isinstance(node, ast.Name):
                names.append(node.id)
        assert not any(
            "jev" in name.casefold()
            or "drive_graph" in name
            or "classify_intent" in name
            or "retrieval_plan" in name
            for name in names
        )
