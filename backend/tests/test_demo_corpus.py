"""Controlled corpus, loader safety, OAuth-free browsing, and readiness contracts."""

import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.api.chat import get_rag_service
from app.api.index import get_drive_sync_service
from app.api.sources import get_source_service
from app.core.config import Settings, get_settings
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.db.models.user import User
from app.db.enums import DriveFileStatus
from app.demo.load import load_corpus
from app.demo.manifest import load_manifest
from app.demo.service import DemoCorpusError, DemoCorpusService
from app.ingestion.chunking import chunk_text
from app.retrieval.query_router import QueryRoute, classify_query
from app.main import app
from app.main import lifespan
from app.schemas.source import SourceChunkRead
from app.services.drive_content_service import DriveContentService
from app.services.drive_sync_service import DriveSyncService

DEMO_ID = uuid.UUID("731b8717-6b2f-4a15-9c21-5f9950ac7d91")


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    return Settings(
        demo_mode=True,
        demo_user_id=str(DEMO_ID),
        database_url="postgresql+asyncpg://demo:demo@localhost/drivemind_demo_test",
        qdrant_collection="drivemind_demo_test",
    )


@pytest.fixture
def store() -> dict[type[object], list[object]]:
    return {User: [], DriveFile: [], Document: [], Chunk: []}


@pytest.fixture
def db(store: dict[type[object], list[object]]) -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock(side_effect=lambda obj: store[type(obj)].append(obj))

    async def scalars(query: object) -> MagicMock:
        entity = query.column_descriptions[0]["entity"]  # type: ignore[attr-defined]
        return MagicMock(all=lambda: store[entity])

    async def get(model: type[object], key: uuid.UUID) -> object | None:
        return next((obj for obj in store[model] if obj.id == key), None)  # type: ignore[attr-defined]

    session.scalars.side_effect = scalars
    session.get.side_effect = get
    session.scalar.return_value = None
    return session


def populate(db: AsyncMock) -> tuple[DriveFile, Document, Chunk]:
    manifest = load_manifest()
    entry = manifest.files[0]
    text = manifest.read_sample(entry.filename)
    db.add(User(id=DEMO_ID, email=f"demo-{DEMO_ID}@example.invalid", google_id=f"demo:{DEMO_ID}"))
    file = DriveFile(
        id=entry.id,
        user_id=DEMO_ID,
        name=entry.filename,
        drive_file_id=entry.external_id,
        mime_type="text/plain",
        folder_path="/HarborDesk samples",
        modified_at=manifest.modified_at,
        status=DriveFileStatus.INDEXED,
    )
    doc = Document(
        id=entry.document_id,
        drive_file_id=entry.id,
        extracted_text=text,
        extracted_text_hash=entry.sha256,
    )
    chunk = Chunk(
        id=uuid.uuid4(),
        document_id=doc.id,
        chunk_index=0,
        text=chunk_text(text)[0].text,
        metadata_json={"extracted_text_hash": entry.sha256},
    )
    db.add(file)
    db.add(doc)
    db.add(chunk)
    return file, doc, chunk


def test_manifest_is_reproducible_and_questions_cover_demo_routes() -> None:
    manifest = load_manifest()
    assert manifest.version == "harbordesk-v1"
    assert len(manifest.files) == 7
    assert len(manifest.questions) == 8
    assert classify_query(manifest.questions[3].question) == QueryRoute.FILE_INVENTORY
    assert classify_query(manifest.questions[1].question) == QueryRoute.FILE_TARGET
    assert {q.kind for q in manifest.questions} >= {
        "single_file",
        "named_file",
        "cross_file",
        "inventory",
        "no_evidence",
        "timeline",
    }
    for entry in manifest.files:
        assert manifest.read_sample(entry.filename)
        assert len(chunk_text(manifest.read_sample(entry.filename))) == 1


@pytest.mark.parametrize("filename", ["../../.env", "unknown.txt", "/etc/passwd"])
def test_manifest_refuses_non_allowlisted_paths(filename: str) -> None:
    with pytest.raises(ValueError, match="Unapproved"):
        load_manifest().read_sample(filename)


def test_manifest_refuses_modified_content_and_symlinks(tmp_path: Path) -> None:
    manifest = load_manifest()
    filename = manifest.files[0].filename
    path = tmp_path / filename
    path.write_text("Unapproved replacement")
    with pytest.raises(ValueError, match="approved manifest"):
        manifest.read_sample(filename, root=tmp_path)
    path.unlink()
    path.symlink_to(tmp_path / "other.txt")
    with pytest.raises(ValueError, match="inside the corpus"):
        manifest.read_sample(filename, root=tmp_path)


@pytest.mark.asyncio
async def test_demo_listing_and_preview_without_drive(db: AsyncMock, settings: Settings) -> None:
    file, doc, _ = populate(db)
    sync = DriveSyncService(db, settings)
    assert await sync.list_synced_files() == [file]
    assert not await sync.is_connected()
    assert not (await sync.get_pending_counts()).any_pending
    content_service = DriveContentService(db, settings)
    content_service._load_oauth_token = AsyncMock()  # type: ignore[method-assign]
    content_service._build_drive_client = MagicMock()  # type: ignore[method-assign]
    result = await content_service.fetch_file_content(file.id)
    assert result.data.decode() == doc.extracted_text
    assert result.mime_type == "text/plain"
    content_service._load_oauth_token.assert_not_called()
    content_service._build_drive_client.assert_not_called()
    for call in db.scalar.await_args_list:
        # Safety inspection may check that tokens are absent, but never loads a token/user fallback.
        sql = str(call.args[0])
        if "google_oauth_tokens" in sql:
            assert "LIMIT" in sql and "google_oauth_tokens.id" in sql
            assert "access_token" not in sql
        else:
            assert "count(" in sql and "drive_files.user_id =" in sql
    with pytest.raises(ValueError, match="not found"):
        await content_service.fetch_file_content(uuid.uuid4())


@pytest.mark.asyncio
@pytest.mark.parametrize("identity", ["", "invalid", str(uuid.uuid4())])
async def test_demo_browsing_never_falls_back(
    db: AsyncMock, settings: Settings, identity: str
) -> None:
    populate(db)
    settings.demo_user_id = identity
    with pytest.raises(ValueError, match="Demo identity"):
        await DriveSyncService(db, settings).list_synced_files()
    db.scalars.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("contamination", ["user", "oauth", "file", "document", "chunk"])
async def test_unapproved_storage_is_refused(
    db: AsyncMock, settings: Settings, contamination: str
) -> None:
    file, doc, chunk = populate(db)
    if contamination == "user":
        db.add(User(id=uuid.uuid4(), email="owner@example.invalid", google_id="owner"))
    elif contamination == "oauth":
        db.scalar.return_value = uuid.uuid4()
    elif contamination == "file":
        file.user_id = uuid.uuid4()
    elif contamination == "document":
        doc.extracted_text = "Unknown content"
    else:
        chunk.text = "Unknown evidence"
    with pytest.raises(DemoCorpusError):
        await DemoCorpusService(db, settings).inspect_database(DEMO_ID)


def test_demo_refuses_default_normal_storage(db: AsyncMock, settings: Settings) -> None:
    settings.qdrant_collection = "drivemind_chunks"
    with pytest.raises(DemoCorpusError, match="dedicated"):
        DemoCorpusService(db, settings)


@pytest.mark.asyncio
async def test_vector_checks_reject_foreign_points_and_detect_missing_vectors(
    db: AsyncMock, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    file, doc, chunk = populate(db)
    client = AsyncMock()
    monkeypatch.setattr("app.demo.service.create_qdrant_client", lambda settings: client)
    client.collection_exists.return_value = True
    record = SimpleNamespace(
        id=str(chunk.id),
        payload={
            "chunk_id": str(chunk.id),
            "drive_file_id": str(file.id),
            "extracted_text_hash": doc.extracted_text_hash,
        },
    )
    client.scroll.return_value = ([record], None)
    service = DemoCorpusService(db, settings)
    assert await service.inspect_vectors(chunks=[chunk])
    client.scroll.return_value = ([], None)
    assert not await service.inspect_vectors(chunks=[chunk])
    client.scroll.return_value = ([SimpleNamespace(id=str(uuid.uuid4()), payload={})], None)
    with pytest.raises(DemoCorpusError, match="unapproved point"):
        await service.inspect_vectors(chunks=[chunk])
    assert client.close.await_count == 3


@pytest.mark.asyncio
async def test_readiness_requires_complete_index_not_just_files(
    db: AsyncMock,
    store: dict[type[object], list[object]],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    populate(db)
    manifest = load_manifest()
    for entry in manifest.files[1:]:
        text = manifest.read_sample(entry.filename)
        db.add(
            DriveFile(
                id=entry.id,
                user_id=DEMO_ID,
                drive_file_id=entry.external_id,
                name=entry.filename,
                mime_type="text/plain",
                folder_path="/HarborDesk samples",
                modified_at=manifest.modified_at,
                status=DriveFileStatus.INDEXED,
            )
        )
        db.add(
            Document(
                id=entry.document_id,
                drive_file_id=entry.id,
                extracted_text=text,
                extracted_text_hash=entry.sha256,
            )
        )
        db.add(
            Chunk(
                id=uuid.uuid4(),
                document_id=entry.document_id,
                chunk_index=0,
                text=text,
                metadata_json={"extracted_text_hash": entry.sha256},
            )
        )
    vectors = AsyncMock(return_value=True)
    monkeypatch.setattr(DemoCorpusService, "inspect_vectors", vectors)
    service = DemoCorpusService(db, settings)
    assert await service.is_ready()
    vectors.return_value = False
    assert not await service.is_ready()
    vectors.return_value = True
    store[Chunk].pop()
    assert not await service.is_ready()


@pytest.mark.asyncio
async def test_loader_uses_explicit_identity_and_existing_builder_idempotently(
    db: AsyncMock,
    store: dict[type[object], list[object]],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(DemoCorpusService, "inspect_vectors", AsyncMock(return_value=False))
    monkeypatch.setattr(DemoCorpusService, "is_ready", AsyncMock(return_value=True))
    build = AsyncMock(return_value=SimpleNamespace(failed=0, skipped=0))
    factory = MagicMock(return_value=SimpleNamespace(build_index=build))
    monkeypatch.setattr("app.demo.load.IndexingService", factory)
    await load_corpus(db, settings, confirmed_isolated=True)
    await load_corpus(db, settings, confirmed_isolated=True)
    assert len(store[User]) == 1
    assert len(store[DriveFile]) == len(store[Document]) == 7
    assert {call.kwargs["user_id"] for call in build.await_args_list} == {DEMO_ID}
    factory.assert_called_with(db, settings)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", ["normal", "confirmation", "missing_id", "owner", "foreign_vector"]
)
async def test_loader_refuses_unsafe_conditions_before_writes(
    db: AsyncMock, settings: Settings, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    if failure == "normal":
        settings.demo_mode = False
    if failure == "missing_id":
        settings.demo_user_id = ""
    if failure == "owner":
        db.add(User(id=DEMO_ID, email="owner@example.invalid", google_id="owner"))
        db.add.reset_mock()
    vectors = AsyncMock(return_value=False)
    if failure == "foreign_vector":
        vectors.side_effect = DemoCorpusError("Unapproved points")
    monkeypatch.setattr(DemoCorpusService, "inspect_vectors", vectors)
    with pytest.raises(DemoCorpusError):
        await load_corpus(db, settings, confirmed_isolated=failure != "confirmation")
    db.add.assert_not_called()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_status_reports_index_readiness_without_claiming_drive_connection(
    async_client: AsyncClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = MagicMock()
    monkeypatch.setitem(app.dependency_overrides, get_settings, lambda: settings)
    monkeypatch.setitem(app.dependency_overrides, get_drive_sync_service, lambda: service)
    check = AsyncMock(return_value=True)
    monkeypatch.setattr(DemoCorpusService, "is_ready", check)
    response = await async_client.get("/api/v1/index/status")
    assert response.status_code == 200
    data = response.json()
    assert data["demo_ready"] is True and data["connected"] is False
    assert len(data["demo_questions"]) == 8
    service.is_connected.assert_not_called()
    check.side_effect = DemoCorpusError("Unavailable")
    response = await async_client.get("/api/v1/index/status")
    assert response.json()["demo_ready"] is False


@pytest.mark.asyncio
async def test_unavailable_demo_index_blocks_chat_before_rag(
    async_client: AsyncClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(app.dependency_overrides, get_settings, lambda: settings)
    monkeypatch.setattr(DemoCorpusService, "is_ready", AsyncMock(return_value=False))
    service = MagicMock()
    monkeypatch.setitem(app.dependency_overrides, get_rag_service, lambda: service)
    response = await async_client.post("/api/v1/chat", json={"question": "Pilot launch?"})
    assert response.status_code == 503
    assert response.json() == {"detail": "The sample knowledge base is unavailable."}
    service.ask.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("ready", [True, False])
async def test_demo_sources_keep_chunk_contract_only_for_ready_corpus(
    async_client: AsyncClient,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    ready: bool,
) -> None:
    entry = load_manifest().files[0]
    chunk_id = uuid.uuid4()
    source = SourceChunkRead(
        chunk_id=chunk_id,
        drive_file_id=entry.id,
        filename=entry.filename,
        mime_type="text/plain",
        chunk_index=0,
        text=load_manifest().read_sample(entry.filename),
        modified_at=load_manifest().modified_at,
    )
    service = MagicMock()
    service.get_source_chunk = AsyncMock(return_value=source)
    check = AsyncMock(return_value=ready)
    monkeypatch.setattr(DemoCorpusService, "is_ready", check)
    monkeypatch.setitem(app.dependency_overrides, get_settings, lambda: settings)
    monkeypatch.setitem(app.dependency_overrides, get_source_service, lambda: service)
    response = await async_client.get(f"/api/v1/sources/{chunk_id}")
    check.assert_awaited_once()
    if ready:
        assert response.status_code == 200
        assert response.json()["text"] == source.text
        assert response.json()["chunk_id"] == str(chunk_id)
        assert response.json()["drive_file_id"] == str(entry.id)
    else:
        assert response.status_code == 503
        service.get_source_chunk.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("demo_mode", [False, True])
async def test_startup_never_loads_corpus_and_demo_does_not_mutate_jobs(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, demo_mode: bool
) -> None:
    settings.demo_mode = demo_mode
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    cleanup = AsyncMock()
    monkeypatch.setattr("app.main._cleanup_stuck_jobs", cleanup)
    monkeypatch.setattr("app.main.engine", AsyncMock())
    loader = AsyncMock()
    monkeypatch.setattr("app.demo.load.load_corpus", loader)
    async with lifespan(app):
        pass
    assert cleanup.await_count == (0 if demo_mode else 1)
    loader.assert_not_called()
