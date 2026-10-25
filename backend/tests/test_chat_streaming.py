"""Real native streaming adapter + agent/finalizer, synthetic evidence, zero network."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
import httpx
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionChunk

from app.agents.tool_rag.agent_service import ToolRagAgentService
from app.core.config import Settings
from app.agents.tool_rag.agent_models import AgentMessage, AgentResponseError
from app.llm.base import ChatError
from app.llm.openai_agent_service import OpenAIAgentChatService
from app.services.chat_stream import emit, event_stream, provisional_text, stream_sink
from tests.agents.tool_rag.test_tool_execution import InventoryDB, USER, chunk, file


class ProviderStream:
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False

    def __aiter__(self):
        return self.iterate()

    async def iterate(self):
        for delta, finish in self.chunks:
            if isinstance(delta, Exception):
                raise delta
            yield ChatCompletionChunk.model_validate(
                {
                    "id": "test",
                    "created": 1,
                    "model": "gpt-4o-mini",
                    "object": "chat.completion.chunk",
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                }
            )

    async def close(self):
        self.closed = True


def tool_stream():
    args = json.dumps({"query": "refund", "scope": {"kind": "ALL_ELIGIBLE_INDEXED_FILES"}})
    return ProviderStream(
        [
            (
                {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "search_knowledge", "arguments": args[:15]},
                        }
                    ]
                },
                None,
            ),
            ({"tool_calls": [{"index": 0, "function": {"arguments": args[15:]}}]}, "tool_calls"),
        ]
    )


async def agent_run(final_chunks, *, foreign=False):
    streams = [tool_stream(), ProviderStream(final_chunks)]
    create = AsyncMock(side_effect=streams)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    client.with_options = Mock(return_value=client)
    chat = OpenAIAgentChatService(Settings(_env_file=None), client=client)
    retriever = AsyncMock()
    retriever.retrieve.return_value = [chunk(file_id=11 if foreign else 10)]
    events = []

    async def sink(name, data):
        events.append((name, data))

    token = stream_sink.set(sink)
    try:
        result = await ToolRagAgentService(chat).run(
            "Refund policy?",
            user_id=USER,
            db=InventoryDB([file(), file(11, user=UUID(int=2))]),
            retriever=retriever,
        )
    finally:
        stream_sink.reset(token)
    assert create.await_count == 2
    assert client.with_options.call_count == 2
    client.with_options.assert_called_with(max_retries=0)
    assert all(call.kwargs["stream"] is True for call in create.await_args_list)
    assert all(s.closed for s in streams)
    retriever.retrieve.assert_awaited_once()
    return result, events


@pytest.mark.asyncio
async def test_native_tools_then_progressive_text_and_verified_citations():
    result, events = await agent_run(
        [
            ({"content": "The refund "}, None),
            ({"content": "policy applies "}, None),
            ({"content": "[source_1]."}, "stop"),
        ]
    )
    partials = [data["text"] for name, data in events if name == "provisional"]
    assert partials[:2] == ["The refund ", "The refund policy applies "]
    assert result["failure"] is None and result["final_answer"] == "The refund policy applies [1]."
    assert result["citations"][0].chunk_id == chunk().chunk_id
    assert "source_1" not in json.dumps(events) and "arguments" not in json.dumps(events)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "marker", ["[source_999]", "[99]", "source_1", "00000000-0000-0000-0000-000000000001"]
)
async def test_invalid_citations_cannot_become_a_verified_answer(marker):
    result, events = await agent_run(
        [({"content": "Provisional text "}, None), ({"content": marker}, "stop")]
    )
    assert result["failure"] == "UNSAFE_FINAL_OUTPUT" and not result["citations"]
    assert marker not in json.dumps(events)


@pytest.mark.asyncio
async def test_foreign_scope_never_streams_model_prose():
    result, events = await agent_run(
        [({"content": "Private fabricated claim "}, "stop")], foreign=True
    )
    assert not any(name == "provisional" for name, _ in events)
    assert "fabricated" not in result["final_answer"]
    assert not result["citations"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ending",
    [
        [(RuntimeError("private provider body"), None)],
        [({"content": "unfinished "}, None)],
        [({"content": "truncated "}, "length")],
    ],
)
async def test_provider_error_or_incomplete_generation_fails_closed(ending):
    result, _ = await agent_run(ending)
    assert result["failure"] == "MALFORMED_RESPONSE"
    assert not result["citations"]


def test_split_identifiers_and_citations_are_withheld():
    text = "Answer [source_1] 00000000-0000-0000-0000-000000000001 source_2 done "
    for end in range(len(text)):
        value = provisional_text(text[:end])
        assert "source_" not in value and "00000000-" not in value and "[" not in value


@pytest.mark.asyncio
async def test_sse_delivers_before_completion_and_disconnect_joins_cleanup():
    released = asyncio.Event()
    cancelled = asyncio.Event()

    async def operation():
        try:
            await emit("state", {"phase": "searching"})
            await released.wait()
        finally:
            cancelled.set()

    stream = event_stream(operation)
    first = await anext(stream)
    assert "event: state" in first and not released.is_set()
    await stream.aclose()
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_sse_public_error_does_not_leak_diagnostics():
    async def operation():
        raise RuntimeError("secret provider payload")

    frames = "".join([frame async for frame in event_stream(operation)])
    assert "event: error" in frames and "secret" not in frames


@pytest.mark.asyncio
async def test_streaming_503_uses_one_real_sdk_http_attempt_and_preserves_non_streaming_retries():
    attempts = []

    def upstream(request: httpx.Request) -> httpx.Response:
        attempts.append(json.loads(request.content))
        return httpx.Response(
            503,
            headers={"retry-after-ms": "1"},
            json={"error": {"message": "synthetic unavailable", "type": "server_error"}},
        )

    async with AsyncOpenAI(
        api_key="synthetic-test-key",
        base_url="https://upstream.invalid/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(upstream)),
    ) as client:
        chat = OpenAIAgentChatService(Settings(_env_file=None), client=client)
        messages = (AgentMessage(role="USER", text="Synthetic question"),)
        on_text = AsyncMock()
        assert client.max_retries == 2
        with pytest.raises(AgentResponseError):
            await chat.stream_step(messages=messages, tools=(), on_text=on_text)
        assert len(attempts) == 1
        assert attempts[0]["stream"] is True
        on_text.assert_not_awaited()
        assert client.max_retries == 2  # Per-request options must not mutate the shared client.

        attempts.clear()
        with pytest.raises(ChatError):
            await chat.step(messages=messages, tools=())
        assert len(attempts) == 3
        assert all("stream" not in body for body in attempts)
