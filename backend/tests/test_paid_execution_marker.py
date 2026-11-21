"""M0-SEC ticket 05: the paid-execution marker and the five provider-request chokepoints.

No network, no database, no key: every client is a fake. Each chokepoint test fails if its
``mark_paid_started()`` call is removed, and checks the marker is set before the request is sent,
so a request that then raises or is cancelled still counts.
"""

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.agents.drive_graph.nodes as nodes
from app.agents.tool_rag.agent_models import AgentMessage
from app.core.config import Settings
from app.core.paid_execution import PaidExecutionMarker, install_marker, mark_paid_started
from app.embeddings.openai_service import OpenAIEmbeddingService
from app.llm.base import ChatConfigurationError, ChatError
from app.llm.openai_agent_service import OpenAIAgentChatService
from app.llm.openai_service import OpenAIChatService
from app.retrieval.owned import gather_owned

SETTINGS = Settings(_env_file=None, openai_api_key="sk-test-key")  # type: ignore[call-arg]


# --- the holder ------------------------------------------------------------------------------


def test_marker_without_installation_is_a_harmless_noop():
    mark_paid_started()  # no marker installed: indexing, evaluation and demo mode are unaffected


def test_marker_is_set_once_and_idempotent_and_uninstalled_afterwards():
    marker = PaidExecutionMarker()
    with install_marker(marker):
        assert marker.started is False
        mark_paid_started()
        mark_paid_started()
        assert marker.started is True
    from app.core import paid_execution

    assert paid_execution._marker.get() is None  # pyright: ignore[reportPrivateUsage]
    later = PaidExecutionMarker()
    mark_paid_started()  # uninstalled again: touches neither marker
    assert later.started is False
    assert marker.started is True


async def test_marker_set_in_child_tasks_is_seen_by_the_parent():
    marker = PaidExecutionMarker()

    async def child() -> None:
        mark_paid_started()

    async def idle() -> None:
        return None

    with install_marker(marker):
        await gather_owned(idle(), child())  # ensure_future children, as the retrievers run
    assert marker.started is True

    second = PaidExecutionMarker()
    with install_marker(second):
        task = asyncio.ensure_future(child())
        await task
    assert second.started is True


async def test_concurrent_requests_do_not_share_a_marker():
    first, second = PaidExecutionMarker(), PaidExecutionMarker()
    ready = asyncio.Event()

    async def request(marker: PaidExecutionMarker, *, pays: bool) -> None:
        with install_marker(marker):
            if pays:
                mark_paid_started()
                ready.set()
            else:
                await ready.wait()  # the other request has already marked its own marker

    await asyncio.gather(request(first, pays=True), request(second, pays=False))
    assert first.started is True and second.started is False


# --- the five chokepoints --------------------------------------------------------------------


def chat_client(create: Any) -> Any:
    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        with_options=lambda **_: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        ),
    )


async def run_marked(call, *, expect_error=None):
    """Run ``call`` with a marker installed; return whether the marker was set when it ended."""
    marker = PaidExecutionMarker()
    with install_marker(marker):
        if expect_error is None:
            await call()
        else:
            with pytest.raises(expect_error):
                await call()
    return marker.started


def seen_marker_at_request(started_log: list[bool]):
    """A fake ``create`` that records whether the marker was already set when it was called."""
    from app.core import paid_execution

    async def create(*_args, **_kwargs):
        marker = paid_execution._marker.get()  # pyright: ignore[reportPrivateUsage]
        started_log.append(marker is not None and marker.started)
        raise RuntimeError("provider failed")

    return create


async def test_chat_complete_marks_before_the_request_even_when_it_fails():
    log: list[bool] = []
    chat = OpenAIChatService(SETTINGS, client=chat_client(seen_marker_at_request(log)))
    assert await run_marked(lambda: chat._complete("s", "u"), expect_error=RuntimeError) is True
    assert log == [True]


async def test_chat_complete_without_a_key_makes_no_request_and_does_not_mark():
    no_key = Settings(_env_file=None, openai_api_key="")  # type: ignore[call-arg]
    chat = OpenAIChatService(no_key)
    started = await run_marked(
        lambda: chat._complete("s", "u"), expect_error=ChatConfigurationError
    )
    assert started is False


async def test_agent_step_marks_before_the_request_even_when_it_fails():
    log: list[bool] = []
    chat = OpenAIAgentChatService(SETTINGS, client=chat_client(seen_marker_at_request(log)))
    messages = [AgentMessage(role="USER", text="q")]
    assert (
        await run_marked(lambda: chat.step(messages=messages, tools=[]), expect_error=ChatError)
        is True
    )
    assert log == [True]


async def test_agent_stream_step_marks_before_the_request_even_when_it_fails():
    log: list[bool] = []
    chat = OpenAIAgentChatService(SETTINGS, client=chat_client(seen_marker_at_request(log)))
    messages = [AgentMessage(role="USER", text="q")]

    async def on_text(_: str) -> None:
        return None

    call = lambda: chat.stream_step(messages=messages, tools=[], on_text=on_text)  # noqa: E731
    assert await run_marked(call, expect_error=Exception) is True
    assert log == [True]


async def test_embedding_batch_marks_before_the_request_even_when_it_fails():
    log: list[bool] = []
    client: Any = SimpleNamespace(embeddings=SimpleNamespace(create=seen_marker_at_request(log)))
    service = OpenAIEmbeddingService(SETTINGS, client=client)
    started = await run_marked(lambda: service._embed_batch(["x"]), expect_error=RuntimeError)
    assert started is True and log == [True]


async def test_graph_rewrite_marks_before_the_request_even_when_it_fails(monkeypatch):
    log: list[bool] = []
    fake = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=seen_marker_at_request(log)))
    )
    monkeypatch.setattr(nodes, "AsyncOpenAI", lambda **_: fake)

    async def rewrite():
        return await nodes._rewrite_with_openai(  # pyright: ignore[reportPrivateUsage]
            settings=SETTINGS, question="q", working_query="q", evidence_reason="weak"
        )

    assert await run_marked(rewrite, expect_error=RuntimeError) is True
    assert log == [True]


async def test_a_cancelled_request_has_already_marked():
    entered = asyncio.Event()

    async def hangs(*_args, **_kwargs):
        entered.set()
        await asyncio.Event().wait()

    chat = OpenAIChatService(SETTINGS, client=chat_client(hangs))
    marker = PaidExecutionMarker()

    async def work():
        with install_marker(marker):
            await chat._complete("s", "u")

    task = asyncio.ensure_future(work())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert marker.started is True


async def test_an_sdk_retry_inside_one_request_is_still_one_started_marker():
    attempts = AsyncMock()

    async def create_with_internal_retry(*args, **kwargs):  # what the SDK does inside one call
        try:
            return await attempts(*args, **kwargs)
        except RuntimeError:
            return await attempts(*args, **kwargs)

    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content="ok"))]
    attempts.side_effect = [RuntimeError("503"), response]
    chat = OpenAIChatService(SETTINGS, client=chat_client(create_with_internal_retry))
    assert await run_marked(lambda: chat._complete("s", "u")) is True
    assert attempts.await_count == 2


async def test_conversation_history_recall_makes_no_provider_request_and_leaves_marker_unset():
    """A deterministic zero-call route: real chat service, fake client that must stay unused."""
    from uuid import UUID

    from app.services.rag_service import RagService

    owner = UUID(int=7)
    create = AsyncMock()
    chat = OpenAIChatService(SETTINGS, client=chat_client(create))
    db = AsyncMock()
    db.add = MagicMock()
    db.get = AsyncMock(return_value=SimpleNamespace(id=owner, email="o@example.com", google_id="g"))
    service = RagService(
        db,
        Settings(
            _env_file=None,  # type: ignore[call-arg]
            hybrid_retrieval_enabled=False,
            agent_graph_enabled=False,
        ),
        retriever=AsyncMock(),
        chat_service=chat,
        persist_query_history=False,
    )
    history = [
        {"role": "user", "text": "Where is the workshop held?"},
        {"role": "assistant", "text": "The workshop is in Hall B."},
    ]

    async def ask():
        return await service.ask(
            "What did you just reply?",
            user_id=owner,
            conversation_id="c",
            history=history,
            history_window_complete=True,
        )

    marker = PaidExecutionMarker()
    with install_marker(marker):
        result = await ask()
    assert result.retrieval_count == 0 and result.answer.startswith("My last answer was")
    create.assert_not_awaited()
    assert marker.started is False


async def test_closing_an_installed_marker_from_another_task_does_not_raise():
    """A stream torn down by the server may close the generator in a different context."""
    marker = PaidExecutionMarker()

    async def work():
        with install_marker(marker):
            mark_paid_started()
            yield

    gen = work()
    await gen.__anext__()
    await asyncio.ensure_future(gen.aclose())  # closed in another task's context
    assert marker.started is True
