"""Transport reuse never substitutes for fresh demo admission checks."""

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import Depends
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import require_demo_index
from app.api.index import get_drive_sync_service
from app.core.config import Settings, get_settings
from app.db.enums import DriveFileStatus
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.db.models.user import User
from app.db.session import get_db
from app.demo.manifest import load_manifest
from app.demo.readiness_client import DemoReadinessClient
from app.demo.service import DemoCorpusError, DemoCorpusService
from app.ingestion.chunking import chunk_text
from app.main import create_app
from app.services.drive_sync_service import DriveSyncService

DEMO_ID = UUID("731b8717-6b2f-4a15-9c21-5f9950ac7d91")


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    return Settings(
        demo_mode=True,
        demo_user_id=str(DEMO_ID),
        database_url="postgresql+asyncpg://demo:demo@localhost/demo_test",
        qdrant_collection="demo_test",
    )


@pytest.fixture
def store() -> dict[type[object], list[object]]:
    manifest = load_manifest()
    rows: dict[type[object], list[object]] = {
        User: [User(id=DEMO_ID, email="demo@example.invalid", google_id="demo")],
        DriveFile: [],
        Document: [],
        Chunk: [],
    }
    for entry in manifest.files:
        text = manifest.read_sample(entry.filename)
        rows[DriveFile].append(
            DriveFile(
                id=entry.id,
                user_id=DEMO_ID,
                name=entry.filename,
                drive_file_id=entry.external_id,
                mime_type="text/plain",
                folder_path="/HarborDesk samples",
                status=DriveFileStatus.INDEXED,
            )
        )
        rows[Document].append(
            Document(
                id=entry.document_id,
                drive_file_id=entry.id,
                extracted_text=text,
                extracted_text_hash=entry.sha256,
            )
        )
        for indexed in chunk_text(text):
            rows[Chunk].append(
                Chunk(
                    id=uuid4(),
                    document_id=entry.document_id,
                    chunk_index=indexed.chunk_index,
                    text=indexed.text,
                    metadata_json={"extracted_text_hash": entry.sha256},
                )
            )
    return rows


@pytest.fixture
def db(store: dict[type[object], list[object]]) -> AsyncMock:
    session = AsyncMock()
    session.get.return_value = store[User][0]
    session.scalar.return_value = None

    async def scalars(query: object) -> MagicMock:
        entity = query.column_descriptions[0]["entity"]  # type: ignore[attr-defined]
        return MagicMock(all=lambda: store[entity])

    session.scalars.side_effect = scalars
    return session


@pytest.fixture
def client(store: dict[type[object], list[object]]) -> AsyncMock:
    chunks = store[Chunk]
    entries = {str(entry.document_id): entry for entry in load_manifest().files}
    records = []
    for chunk in chunks:
        assert isinstance(chunk, Chunk)
        entry = entries[str(chunk.document_id)]  # type: ignore[attr-defined]
        records.append(
            SimpleNamespace(
                id=str(chunk.id),  # type: ignore[attr-defined]
                payload={
                    "chunk_id": str(chunk.id),
                    "drive_file_id": str(entry.id),  # type: ignore[attr-defined]
                    "extracted_text_hash": entry.sha256,
                },
            )
        )
    result = AsyncMock()
    result.collection_exists.return_value = True
    result.scroll.return_value = (records, None)
    return result


@pytest.fixture
def factory(client: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    result = MagicMock(return_value=client)
    monkeypatch.setattr("app.demo.readiness_client.create_qdrant_client", result)
    return result


@pytest.fixture
async def http(
    settings: Settings,
    db: AsyncMock,
    factory: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[AsyncClient]:
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    monkeypatch.setattr("app.main.engine", AsyncMock())
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_db] = lambda: db
    application.dependency_overrides[get_drive_sync_service] = lambda: DriveSyncService(
        db, settings
    )

    @application.get("/admission", dependencies=[Depends(require_demo_index)])
    async def admitted() -> dict[str, bool]:
        return {"ok": True}

    async with application.router.lifespan_context(application):
        factory.assert_not_called()
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as h:
            yield h
    factory.return_value.close.assert_awaited_once()


async def test_requests_share_transport_but_repeat_all_validation(
    http: AsyncClient,
    db: AsyncMock,
    client: AsyncMock,
    factory: MagicMock,
) -> None:
    for path in ("/api/v1/index/status", "/admission", "/api/v1/index/status"):
        response = await http.get(path)
        assert response.status_code == 200
        if path.endswith("status"):
            assert response.json()["demo_ready"] is True
    factory.assert_called_once()
    assert db.get.await_count == db.scalar.await_count == 3
    assert db.scalars.await_count == 12  # all users/files/documents/chunks each time
    assert client.collection_exists.await_count == client.scroll.await_count == 3
    client.close.assert_not_awaited()


@pytest.mark.parametrize(
    "change",
    [
        "missing_vector",
        "foreign_vector",
        "wrong_payload",
        "missing_collection",
        "timeout",
        "foreign_user",
        "oauth",
        "unindexed",
        "document_content",
        "chunk_content",
        "missing_user",
    ],
)
async def test_previous_success_never_authorizes_changed_store(
    http: AsyncClient,
    db: AsyncMock,
    client: AsyncMock,
    store: dict[type[object], list[object]],
    change: str,
) -> None:
    assert (await http.get("/api/v1/index/status")).json()["demo_ready"] is True
    records = client.scroll.return_value[0]
    if change == "missing_vector":
        records.pop()
    elif change == "foreign_vector":
        records.append(SimpleNamespace(id=str(uuid4()), payload={}))
    elif change == "wrong_payload":
        records[0].payload["extracted_text_hash"] = "changed"
    elif change == "missing_collection":
        client.collection_exists.return_value = False
    elif change == "timeout":
        client.scroll.side_effect = TimeoutError("private transport diagnostic")
    elif change == "foreign_user":
        store[User].append(User(id=uuid4()))
    elif change == "oauth":
        db.scalar.return_value = uuid4()
    elif change == "unindexed":
        store[DriveFile][0].status = DriveFileStatus.FAILED  # type: ignore[attr-defined]
    elif change == "document_content":
        store[Document][0].extracted_text = "changed"  # type: ignore[attr-defined]
    elif change == "chunk_content":
        store[Chunk][0].text = "changed"  # type: ignore[attr-defined]
    else:
        db.get.return_value = None
    response = await http.get("/api/v1/index/status")
    assert response.status_code == 200 and response.json()["demo_ready"] is False
    for path, method in (
        ("/admission", "GET"),
        ("/api/v1/chat", "POST"),
        (f"/api/v1/sources/{uuid4()}", "GET"),
    ):
        response = (
            await http.post(path, json={"question": "Hello"})
            if method == "POST"
            else await http.get(path)
        )
        assert response.status_code == 503
        assert response.json() == {"detail": "The sample knowledge base is unavailable."}
    client.close.assert_not_awaited()


async def test_concurrent_first_borrowers_create_exactly_one_client(
    factory: MagicMock,
    settings: Settings,
    client: AsyncMock,
) -> None:
    owner = DemoReadinessClient()
    borrowed = await asyncio.gather(*(owner.get(settings) for _ in range(10)))
    assert all(item is client for item in borrowed)
    factory.assert_called_once()
    await owner.close()
    await owner.close()
    client.close.assert_awaited_once()
    with pytest.raises(RuntimeError, match="closed"):
        await owner.get(settings)


async def test_app_instances_own_distinct_clients_and_shutdown(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients = [AsyncMock(), AsyncMock()]
    factory = MagicMock(side_effect=clients)
    monkeypatch.setattr("app.demo.readiness_client.create_qdrant_client", factory)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    engine = AsyncMock()
    monkeypatch.setattr("app.main.engine", engine)
    first, second = create_app(), create_app()
    async with first.router.lifespan_context(first), second.router.lifespan_context(second):
        assert await first.state.demo_readiness_client.get(settings) is clients[0]
        assert await second.state.demo_readiness_client.get(settings) is clients[1]
    assert factory.call_count == 2
    for client in clients:
        client.close.assert_awaited_once()
    assert engine.dispose.await_count == 2


async def test_configuration_and_event_loop_changes_rejected(
    factory: MagicMock,
    settings: Settings,
) -> None:
    owner = DemoReadinessClient()
    await owner.get(settings)
    with pytest.raises(RuntimeError, match="configuration changed"):
        await owner.get(settings.model_copy(update={"qdrant_collection": "another_collection"}))
    with pytest.raises(RuntimeError, match="another event loop"):
        await asyncio.to_thread(lambda: asyncio.run(owner.get(settings)))
    factory.assert_called_once()
    await owner.close()


@pytest.mark.parametrize("borrowed", [False, True])
@pytest.mark.parametrize("outcome", ["success", "missing", "timeout", "foreign", "cancel"])
async def test_client_ownership_on_success_failure_and_cancellation(
    settings: Settings,
    db: AsyncMock,
    client: AsyncMock,
    factory: MagicMock,
    store: dict[type[object], list[object]],
    monkeypatch: pytest.MonkeyPatch,
    borrowed: bool,
    outcome: str,
) -> None:
    monkeypatch.setattr("app.demo.service.create_qdrant_client", factory)
    owner = DemoReadinessClient() if borrowed else None
    service = DemoCorpusService(db, settings, readiness_client=owner)
    if outcome == "missing":
        client.collection_exists.return_value = False
    elif outcome == "timeout":
        client.scroll.side_effect = TimeoutError()
    elif outcome == "foreign":
        client.scroll.return_value = ([SimpleNamespace(id=str(uuid4()), payload={})], None)
    if outcome == "cancel":
        started = asyncio.Event()

        async def blocked(**kwargs: object) -> object:
            started.set()
            await asyncio.Event().wait()

        client.scroll.side_effect = blocked
        task = asyncio.create_task(service.is_ready())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    elif outcome in ("timeout", "foreign"):
        with pytest.raises((TimeoutError, DemoCorpusError)):
            await service.is_ready()
    else:
        assert await service.is_ready() is (outcome == "success")
    if owner is None:
        client.close.assert_awaited_once()
    else:
        client.close.assert_not_awaited()
        # A cancelled/failed request does not poison the shared resource.
        assert await owner.get(settings) is client
        if outcome == "cancel":
            client.scroll.side_effect = None
            assert await service.is_ready()
        await owner.close()
        client.close.assert_awaited_once()


async def test_factory_failure_can_retry_without_positive_cache(
    factory: MagicMock,
    client: AsyncMock,
    settings: Settings,
) -> None:
    factory.side_effect = [ValueError("invalid configuration"), client]
    owner = DemoReadinessClient()
    with pytest.raises(ValueError):
        await owner.get(settings)
    assert await owner.get(settings) is client
    assert factory.call_count == 2
    await owner.close()


async def test_normal_mode_does_not_acquire_demo_client(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings.demo_mode = False
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    cleanup = AsyncMock()
    monkeypatch.setattr("app.main._cleanup_stuck_jobs", cleanup)
    monkeypatch.setattr("app.main.engine", AsyncMock())
    factory = MagicMock()
    monkeypatch.setattr("app.demo.readiness_client.create_qdrant_client", factory)
    application = create_app()
    service = MagicMock()
    service.is_connected = AsyncMock(return_value=False)
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_drive_sync_service] = lambda: service
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as h:
            response = await h.get("/api/v1/index/status")
    assert response.json() == {"connected": False, "job": None}
    service.is_connected.assert_awaited_once()
    factory.assert_not_called()
    cleanup.assert_awaited_once()


async def test_construction_failure_keeps_status_and_admission_error_boundaries(
    http: AsyncClient,
    factory: MagicMock,
    client: AsyncMock,
) -> None:
    factory.side_effect = ValueError("private configuration diagnostic")
    response = await http.get("/api/v1/index/status")
    assert response.status_code == 200 and response.json()["demo_ready"] is False
    response = await http.get("/admission")
    assert response.status_code == 503
    assert "private" not in response.text
    factory.side_effect = None
    assert (await http.get("/api/v1/index/status")).json()["demo_ready"] is True
    client.close.assert_not_awaited()


async def test_shutdown_still_disposes_database_if_client_close_fails(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = AsyncMock()
    client.close.side_effect = TimeoutError()
    monkeypatch.setattr("app.demo.readiness_client.create_qdrant_client", lambda _: client)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    engine = AsyncMock()
    monkeypatch.setattr("app.main.engine", engine)
    application = create_app()
    with pytest.raises(TimeoutError):
        async with application.router.lifespan_context(application):
            await application.state.demo_readiness_client.get(settings)
    engine.dispose.assert_awaited_once()
