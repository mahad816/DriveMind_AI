"""The managed Qdrant client: one client and connection pool per event loop, closed at application shutdown.

Before this, every vector search built a fresh ``AsyncQdrantClient`` (a new connection pool and TCP connection) and
never closed it.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import Settings
from app.embeddings import qdrant_connection
from app.embeddings.qdrant_connection import close_shared_qdrant_clients, shared_qdrant_client
from app.embeddings.vector_store import QdrantVectorStore
from app.main import create_app
from app.services.google_credential_service import GoogleRefreshLifecycle

CHUNK_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER = uuid.UUID("22222222-2222-2222-2222-222222222222")
VECTOR = [0.1] * 8


def settings_for(host: str = "qdrant.local", port: int = 7333, **extra: object) -> Settings:
    return Settings(qdrant_host=host, qdrant_port=port, qdrant_url="", qdrant_api_key="", **extra)  # type: ignore[arg-type]


def response() -> MagicMock:
    return MagicMock(points=[MagicMock(id=str(CHUNK_ID), score=0.9, payload=None)])


@pytest.fixture
def made(monkeypatch: pytest.MonkeyPatch) -> list[AsyncMock]:
    """Every AsyncQdrantClient the factory builds, each a fresh mock that answers searches."""
    clients: list[AsyncMock] = []

    def construct(*_: object, **__: object) -> AsyncMock:
        client = AsyncMock()
        client.query_points = AsyncMock(return_value=response())
        clients.append(client)
        return client

    monkeypatch.setattr("app.embeddings.qdrant_connection.AsyncQdrantClient", construct)
    return clients


def search(store: QdrantVectorStore):
    return store.search_similar(VECTOR, user_id=USER, limit=8, expected_vector_size=len(VECTOR))


async def test_searches_from_many_stores_reuse_one_client(made: list[AsyncMock]) -> None:
    settings = settings_for()
    for _ in range(5):
        hits = await search(QdrantVectorStore(settings))  # a store per request, like RagService
        assert [h.chunk_id for h in hits] == [CHUNK_ID]
    assert len(made) == 1
    assert made[0].query_points.await_count == 5


async def test_one_store_repeating_searches_also_reuses_the_client(made: list[AsyncMock]) -> None:
    store = QdrantVectorStore(settings_for())
    for _ in range(3):
        await search(store)
    assert len(made) == 1


async def test_a_different_connection_configuration_gets_its_own_client(
    made: list[AsyncMock],
) -> None:
    await search(QdrantVectorStore(settings_for(port=7333)))
    await search(QdrantVectorStore(settings_for(port=7444)))
    await search(QdrantVectorStore(settings_for(port=7333)))
    assert len(made) == 2


async def test_an_injected_client_wins_and_is_never_shared_or_closed(made: list[AsyncMock]) -> None:
    injected = AsyncMock()
    injected.query_points = AsyncMock(return_value=response())
    await search(QdrantVectorStore(settings_for(), client=injected))
    injected.query_points.assert_awaited_once()
    assert made == []  # nothing managed was created
    await close_shared_qdrant_clients()
    injected.close.assert_not_awaited()  # the caller owns an injected client


async def test_concurrent_c2_style_searches_share_one_client_and_really_overlap(
    made: list[AsyncMock],
) -> None:
    settings = settings_for()
    barrier = asyncio.Barrier(2)

    async def both_in_flight(*_: object, **__: object) -> MagicMock:
        await barrier.wait()  # returns only if the second search is in flight at the same time
        return response()

    first = shared_qdrant_client(settings)
    first.query_points.side_effect = both_in_flight  # type: ignore[attr-defined]
    hits = await asyncio.wait_for(
        asyncio.gather(search(QdrantVectorStore(settings)), search(QdrantVectorStore(settings))),
        timeout=5,
    )
    assert [len(h) for h in hits] == [1, 1]
    assert len(made) == 1


async def test_many_concurrent_searches_create_exactly_one_client(made: list[AsyncMock]) -> None:
    settings = settings_for()
    await asyncio.gather(*(search(QdrantVectorStore(settings)) for _ in range(40)))
    assert len(made) == 1
    assert made[0].query_points.await_count == 40


async def test_a_failed_construction_is_not_cached(
    monkeypatch: pytest.MonkeyPatch, made: list[AsyncMock]
) -> None:
    real = qdrant_connection.AsyncQdrantClient
    calls = {"n": 0}

    def flaky(*args: object, **kwargs: object) -> AsyncMock:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("cannot build a client")
        return real(*args, **kwargs)  # type: ignore[no-any-return]

    monkeypatch.setattr("app.embeddings.qdrant_connection.AsyncQdrantClient", flaky)
    store = QdrantVectorStore(settings_for())
    with pytest.raises(RuntimeError, match="cannot build a client"):
        await search(store)
    assert made == []
    await search(store)  # the failure left nothing half-built: the next search builds and works
    assert len(made) == 1


async def test_an_invalid_configuration_still_fails_loudly_and_builds_nothing(
    made: list[AsyncMock],
) -> None:
    bad = Settings(qdrant_url="not a url", qdrant_api_key="")
    for _ in range(2):
        with pytest.raises(ValueError, match="QDRANT_URL"):
            await search(QdrantVectorStore(bad))
    assert made == []


async def test_closing_closes_this_loops_clients_once_and_a_later_search_builds_a_new_one(
    made: list[AsyncMock],
) -> None:
    settings = settings_for()
    await search(QdrantVectorStore(settings))
    await close_shared_qdrant_clients()
    made[0].close.assert_awaited_once()
    await close_shared_qdrant_clients()  # closing again is a no-op
    made[0].close.assert_awaited_once()
    await search(QdrantVectorStore(settings))  # never hands out a closed client
    assert len(made) == 2


async def test_closing_attempts_every_client_then_reports_the_first_failure(
    made: list[AsyncMock],
) -> None:
    await search(QdrantVectorStore(settings_for(port=7333)))
    await search(QdrantVectorStore(settings_for(port=7444)))
    made[0].close.side_effect = TimeoutError()
    with pytest.raises(TimeoutError):
        await close_shared_qdrant_clients()
    made[1].close.assert_awaited_once()  # the failure of one did not leave the other open
    await search(QdrantVectorStore(settings_for(port=7333)))  # and nothing stale is handed out
    assert len(made) == 3


def test_without_a_running_loop_nothing_is_shared(made: list[AsyncMock]) -> None:
    settings = settings_for()
    first = shared_qdrant_client(settings)
    second = shared_qdrant_client(settings)
    assert (
        first is not second and len(made) == 2
    )  # the pre-existing behaviour, never cached across loops


def test_sequential_event_loops_never_share_a_client(made: list[AsyncMock]) -> None:
    settings = settings_for()

    async def get() -> AsyncMock:
        return shared_qdrant_client(settings)  # type: ignore[return-value]

    first = asyncio.run(get())
    second = asyncio.run(get())
    assert first is not second and len(made) == 2


async def test_another_running_loop_gets_its_own_client_and_closing_here_leaves_it_alone(
    made: list[AsyncMock],
) -> None:
    settings = settings_for()
    mine = shared_qdrant_client(settings)
    other: list[object] = []
    ready, release = threading.Event(), threading.Event()

    def in_thread() -> None:
        async def work() -> None:
            other.append(shared_qdrant_client(settings))
            ready.set()
            while not release.is_set():
                await asyncio.sleep(0.01)
            await close_shared_qdrant_clients()  # closes only the thread loop's client

        asyncio.run(work())

    thread = threading.Thread(target=in_thread)
    thread.start()
    await asyncio.to_thread(ready.wait, 5)
    assert other[0] is not mine and len(made) == 2
    await close_shared_qdrant_clients()  # this loop only
    made[0].close.assert_awaited_once()
    made[1].close.assert_not_awaited()
    release.set()
    await asyncio.to_thread(thread.join, 5)
    made[1].close.assert_awaited_once()


async def test_the_same_hits_come_back_through_a_shared_or_an_injected_client(
    made: list[AsyncMock],
) -> None:
    # Retrieval behaviour is unchanged: arm A and arm C2 both see exactly what an injected client would return.
    injected = AsyncMock()
    injected.query_points = AsyncMock(return_value=response())
    expected = await search(QdrantVectorStore(settings_for(), client=injected))
    assert await search(QdrantVectorStore(settings_for())) == expected
    assert made[0].query_points.await_args.kwargs == injected.query_points.await_args.kwargs


# ---- application lifecycle -----------------------------------------------------------------------------------


@pytest.fixture
def app_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    return Settings(
        demo_mode=True,
        demo_user_id=str(USER),
        database_url="postgresql+asyncpg://demo:demo@localhost/demo_test",
        qdrant_collection="demo_test",
        qdrant_host="qdrant.local",
        qdrant_port=7333,
    )


def lifespan_app(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> tuple[object, AsyncMock]:
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    engine = AsyncMock()
    monkeypatch.setattr("app.main.engine", engine)
    monkeypatch.setattr("app.main.google_refresh_lifecycle", GoogleRefreshLifecycle())
    return create_app(), engine


async def test_the_client_is_closed_when_the_application_shuts_down(
    monkeypatch: pytest.MonkeyPatch, made: list[AsyncMock], app_settings: Settings
) -> None:
    application, engine = lifespan_app(monkeypatch, app_settings)
    async with application.router.lifespan_context(application):  # type: ignore[attr-defined]
        await search(QdrantVectorStore(app_settings))
        await search(QdrantVectorStore(app_settings))
        made[0].close.assert_not_awaited()  # still open while the application serves
    assert len(made) == 1
    made[0].close.assert_awaited_once()
    engine.dispose.assert_awaited_once()


async def test_shutdown_with_no_search_creates_and_closes_nothing(
    monkeypatch: pytest.MonkeyPatch, made: list[AsyncMock], app_settings: Settings
) -> None:
    application, _ = lifespan_app(monkeypatch, app_settings)
    async with application.router.lifespan_context(application):  # type: ignore[attr-defined]
        pass
    assert made == []  # the client is lazy: startup needs no Qdrant connection


async def test_a_failing_close_still_disposes_the_database_and_the_demo_client(
    monkeypatch: pytest.MonkeyPatch, made: list[AsyncMock], app_settings: Settings
) -> None:
    application, engine = lifespan_app(monkeypatch, app_settings)
    demo_close = AsyncMock()
    monkeypatch.setattr(application.state.demo_readiness_client, "close", demo_close)  # type: ignore[attr-defined]
    with pytest.raises(TimeoutError):
        async with application.router.lifespan_context(application):  # type: ignore[attr-defined]
            await search(QdrantVectorStore(app_settings))
            made[0].close.side_effect = TimeoutError()
    engine.dispose.assert_awaited_once()
    demo_close.assert_awaited_once()


async def test_a_failing_demo_client_close_still_closes_the_shared_qdrant_clients(
    monkeypatch: pytest.MonkeyPatch, made: list[AsyncMock], app_settings: Settings
) -> None:
    application, engine = lifespan_app(monkeypatch, app_settings)
    monkeypatch.setattr(
        application.state.demo_readiness_client,  # type: ignore[attr-defined]
        "close",
        AsyncMock(side_effect=TimeoutError()),
    )
    with pytest.raises(TimeoutError):
        async with application.router.lifespan_context(application):  # type: ignore[attr-defined]
            await search(QdrantVectorStore(app_settings))
    made[0].close.assert_awaited_once()
    engine.dispose.assert_awaited_once()
