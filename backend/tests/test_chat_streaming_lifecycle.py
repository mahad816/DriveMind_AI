"""Streaming keeps durable submit, failure, ownership and cancellation boundaries."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import conversation_chat_service as module
from app.services.chat_stream import emit, event_stream, stream_sink
from tests.services.test_conversation_failure_diagnostics import execution as execution


@pytest.fixture
def streaming(execution, monkeypatch):
    class Receipt(SimpleNamespace):
        def model_dump(self, **kwargs):
            return {"turn": {"status": self.turn.status}, "replayed": self.replayed}

    monkeypatch.setattr(module, "ConversationSubmission", lambda **kw: Receipt(**kw))
    execution.service._status.side_effect = [
        SimpleNamespace(status=module.TurnStatus.RUNNING),
        SimpleNamespace(status=module.TurnStatus.COMPLETED),
    ]
    return execution


@pytest.mark.asyncio
async def test_stream_uses_same_reservation_and_atomic_publication(streaming):
    x = streaming
    events = []

    async def sink(name, data):
        events.append((name, data))
        if name in {"accepted", "state"}:
            x.repo.complete.assert_not_awaited()

    token = stream_sink.set(sink)
    try:
        response, code = await x.service.submit(x.principal, x.cid, x.body)
    finally:
        stream_sink.reset(token)
    assert code == 200 and response.turn.status == "COMPLETED"
    x.repo.reserve.assert_awaited_once()
    x.rag.ask.assert_awaited_once()
    x.service._citations.assert_awaited_once()
    x.repo.complete.assert_awaited_once()
    assert [event[0] for event in events] == ["accepted", "state", "state"]


@pytest.mark.asyncio
async def test_changed_citation_authority_fails_without_publishing_partial_answer(streaming):
    x = streaming
    x.service._citations.side_effect = module.CitationAuthorityLost()
    x.service._status.side_effect = [
        SimpleNamespace(status="RUNNING"),
        SimpleNamespace(status="FAILED"),
    ]
    events = []

    async def sink(name, data):
        events.append((name, data))

    token = stream_sink.set(sink)
    try:
        response, code = await x.service.submit(x.principal, x.cid, x.body)
    finally:
        stream_sink.reset(token)
    assert code == 503 and response.turn.status == "FAILED"
    x.repo.complete.assert_not_awaited()
    assert not any(name == "complete" for name, _ in events)


@pytest.mark.asyncio
async def test_cancel_during_stream_marks_interrupted_without_publication(streaming):
    x = streaming
    started = asyncio.Event()

    async def generation(*args, **kwargs):
        await emit("provisional", {"text": "Unverified "})
        started.set()
        await asyncio.Event().wait()

    x.rag.ask = AsyncMock(side_effect=generation)

    async def sink(*args):
        pass

    token = stream_sink.set(sink)
    task = asyncio.create_task(x.service.submit(x.principal, x.cid, x.body))
    stream_sink.reset(token)
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    x.repo.interrupt_attempt.assert_awaited_once()
    x.repo.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_replay_does_not_repeat_generation_or_retrieval(streaming):
    x = streaming
    x.repo.reserve.return_value.replayed = True
    response, code = await x.service.submit(x.principal, x.cid, x.body)
    assert code == 202 and response.replayed
    x.rag.ask.assert_not_awaited()
    x.repo.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_session_expiry_after_provisional_text_interrupts_and_emits_safe_auth_error(
    streaming,
):
    x = streaming
    result = x.rag.ask.return_value

    async def generation(*args, **kwargs):
        await emit("provisional", {"text": "Unverified answer "})
        return result

    x.rag.ask.side_effect = generation
    x.service._citations.side_effect = module.ConversationSessionExpired(
        "private session diagnostic"
    )

    async def operation():
        await x.service.submit(x.principal, x.cid, x.body)

    frames = [frame async for frame in event_stream(operation)]
    assert "event: accepted" in frames[0]
    assert any("event: provisional" in frame for frame in frames[:-1])
    assert '"code": "SESSION_EXPIRED"' in frames[-1] and "event: error" in frames[-1]
    assert "private session diagnostic" not in "".join(frames)
    assert not any("event: complete" in frame for frame in frames)
    x.repo.complete.assert_not_awaited()
    x.repo.interrupt_attempt.assert_awaited_once()
    assert x.repo.interrupt_attempt.await_args.kwargs["error_code"] == "SESSION_UNAVAILABLE"
