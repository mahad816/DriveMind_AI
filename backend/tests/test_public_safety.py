"""Public demo limits and errors use no network or database operations."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.api.chat import get_rag_service
from app.api.dependencies import require_demo_index
from app.core.config import Settings, get_settings
from app.core.public_safety import DemoChatLimits, PUBLIC_ERROR
from app.llm.base import ChatError
from app.main import create_app
from app.services.rag_service import RagResult, RagService


@pytest.fixture
async def demo(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[tuple[AsyncClient, MagicMock]]:
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("DEMO_CHAT_CONCURRENCY", "1")
    monkeypatch.setenv("DEMO_CHAT_RATE_LIMIT", "2")
    monkeypatch.setenv("DEMO_CHAT_MAX_QUESTION_CHARS", "40")
    monkeypatch.setenv("DEMO_CHAT_MAX_BODY_BYTES", "131072")
    get_settings.cache_clear()
    app = create_app()
    service = MagicMock()
    service.ask = AsyncMock(
        return_value=RagResult(
            query_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            question="Question",
            answer="Grounded answer [1].",
            citations=[],
            retrieval_count=1,
        )
    )
    app.dependency_overrides[get_rag_service] = lambda: service
    app.dependency_overrides[require_demo_index] = lambda: None
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        yield client, service
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_question_limit_accepts_valid_and_rejects_oversized(
    demo: tuple[AsyncClient, MagicMock],
) -> None:
    client, service = demo
    assert (await client.post("/api/v1/chat", json={"question": "q" * 40})).status_code == 200
    service.ask.reset_mock()
    response = await client.post("/api/v1/chat", json={"question": "q" * 41})
    assert response.status_code == 422
    assert "q" * 41 not in response.text
    service.ask.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "history",
    [
        [{"role": "user", "text": "x"}] * 9,
        [{"role": "user", "text": "x" * 8001}],
        [{"role": "user", "text": "x" * 8000}] * 4,
    ],
)
async def test_history_limits_reject_before_execution(
    demo: tuple[AsyncClient, MagicMock], history: list[dict[str, str]]
) -> None:
    client, service = demo
    response = await client.post(
        "/api/v1/chat", json={"question": "hello", "conversation_id": "id", "history": history}
    )
    assert response.status_code == 422
    service.ask.assert_not_awaited()


@pytest.mark.asyncio
async def test_body_limit_checks_stream_without_content_length(
    demo: tuple[AsyncClient, MagicMock],
) -> None:
    client, service = demo

    async def body() -> AsyncIterator[bytes]:
        yield b"x" * 65536
        yield b"x" * 65537

    response = await client.post("/api/v1/chat", content=body())
    assert response.status_code == 413
    service.ask.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrency_rejects_without_queue_and_releases_on_success(
    demo: tuple[AsyncClient, MagicMock],
) -> None:
    client, service = demo
    entered, release = asyncio.Event(), asyncio.Event()
    result = service.ask.return_value

    async def waiting(question: str) -> RagResult:
        entered.set()
        await release.wait()
        return result

    service.ask.side_effect = waiting
    task = asyncio.create_task(client.post("/api/v1/chat", json={"question": "hello"}))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        assert (await client.post("/api/v1/chat", json={"question": "hello"})).status_code == 429
        assert (await client.get("/api/v1/health")).status_code == 200
        assert service.ask.await_count == 1
    finally:
        release.set()
        await task
    service.ask.side_effect = None
    assert (await client.post("/api/v1/chat", json={"question": "hello"})).status_code == 200


@pytest.mark.asyncio
async def test_rate_limit_rejects_before_rag(demo: tuple[AsyncClient, MagicMock]) -> None:
    client, service = demo
    for _ in range(2):
        assert (await client.post("/api/v1/chat", json={"question": "hello"})).status_code == 200
    response = await client.post(
        "/api/v1/chat", json={"question": "hello"}, headers={"X-Forwarded-For": "192.0.2.8"}
    )
    assert response.status_code == 429
    assert "Retry-After" in response.headers
    assert service.ask.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error, status",
    [(ChatError("secret provider path"), 503), (RuntimeError("secret database path"), 500)],
)
async def test_errors_are_sanitized_logged_and_permit_released(
    demo: tuple[AsyncClient, MagicMock],
    caplog: pytest.LogCaptureFixture,
    error: Exception,
    status: int,
) -> None:
    client, service = demo
    service.ask.side_effect = error
    response = await client.post("/api/v1/chat", json={"question": "hello"})
    assert response.status_code == status
    assert response.json()["detail"] == PUBLIC_ERROR
    assert "secret" not in response.text
    assert any(record.exc_info for record in caplog.records)
    service.ask.side_effect = None
    assert (await client.post("/api/v1/chat", json={"question": "hello"})).status_code == 200


@pytest.mark.asyncio
async def test_intentional_http_errors_unchanged(demo: tuple[AsyncClient, MagicMock]) -> None:
    client, service = demo
    service.ask.side_effect = HTTPException(404, "Requested item not found")
    response = await client.post("/api/v1/chat", json={"question": "hello"})
    assert response.status_code == 404
    assert response.json()["detail"] == "Requested item not found"
    assert (await client.get("/api/v1/auth/google")).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("debug", [False, True])
async def test_non_demo_limits_disabled_and_production_errors_safe(
    demo: tuple[AsyncClient, MagicMock], debug: bool
) -> None:
    client, service = demo
    settings = get_settings()
    settings.demo_mode = False
    settings.debug = debug
    for _ in range(4):
        assert (await client.post("/api/v1/chat", json={"question": "q" * 100})).status_code == 200
    service.ask.side_effect = ChatError("private provider detail")
    response = await client.post("/api/v1/chat", json={"question": "hello"})
    assert response.status_code == 503
    assert response.json()["detail"] == ("private provider detail" if debug else PUBLIC_ERROR)


@pytest.mark.asyncio
async def test_limiter_expiry_bounded_state_and_non_demo_bypass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(demo_mode=True, demo_chat_rate_limit=2, demo_chat_concurrency=1)
    limits = DemoChatLimits()
    monkeypatch.setattr("app.core.public_safety.monotonic", lambda: 0.0)
    for _ in range(2):
        async with limits.execution(settings):
            pass
    for _ in range(10):
        with pytest.raises(HTTPException):
            async with limits.execution(settings):
                pass
    assert len(limits.admitted) == 2
    monkeypatch.setattr("app.core.public_safety.monotonic", lambda: 61.0)
    async with limits.execution(settings):
        pass
    assert len(limits.admitted) == 1
    settings.demo_mode = False
    for _ in range(5):
        async with limits.execution(settings):
            assert limits.active == 0
    assert len(limits.admitted) == 1


@pytest.mark.asyncio
async def test_cancellation_releases_admission() -> None:
    limits = DemoChatLimits()
    settings = Settings(demo_mode=True)
    with pytest.raises(asyncio.CancelledError):
        async with limits.execution(settings):
            raise asyncio.CancelledError()
    assert limits.active == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("demo_mode", [True, False])
async def test_demo_history_is_not_persisted_but_normal_history_is(demo_mode: bool) -> None:
    db = AsyncMock()
    db.add = MagicMock()
    service = RagService(
        db, Settings(demo_mode=demo_mode), retriever=MagicMock(), chat_service=MagicMock()
    )

    async def refresh(row: object) -> None:
        row.id = uuid.uuid4()  # type: ignore[attr-defined]

    db.refresh.side_effect = refresh
    query_id = await service._persist_query_history(
        user_id=uuid.uuid4(), question="q", answer="a", citations=[]
    )
    assert isinstance(query_id, uuid.UUID)
    assert db.add.call_count == (0 if demo_mode else 1)
    assert db.commit.await_count == (0 if demo_mode else 1)
