"""Real PostgreSQL and FastAPI private-read ownership; provider calls are synthetic."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import get_settings
from app.db.enums import ApplicationSessionKind, DriveFileStatus
from app.db.models.application_session import ApplicationSession
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.db.models.user import User
from app.db.session import get_db
from app.demo.manifest import load_manifest
from app.ingestion.chunking import chunk_text
from app.main import create_app
from app.security.principal import VerifiedGoogleIdentity
from app.security.session_helpers import session_cookie_policy
from app.services.application_session_service import ApplicationSessionService
from app.services.drive_content_service import DriveContentService
from .conftest import USER_A, USER_B, DEMO_USER
from .test_encrypted_only_credentials import final_engine, keys, grant

__all__ = ["final_engine", "keys"]


@pytest.fixture
async def private_reads(final_engine, keys, monkeypatch):
    factory = async_sessionmaker(final_engine, expire_on_commit=False)
    app = create_app()

    async def database():
        async with factory() as db:
            yield db

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_settings] = lambda: keys
    # Service factories use get_settings directly, outside FastAPI dependency resolution.
    monkeypatch.setattr("app.services.drive_sync_service.get_settings", lambda: keys)
    monkeypatch.setattr("app.services.drive_content_service.get_settings", lambda: keys)
    files, chunks = {}, {}
    async with factory() as db:
        for owner in (USER_A, USER_B):
            file = DriveFile(
                id=uuid4(),
                user_id=owner,
                drive_file_id=f"synthetic-{owner}",
                name=f"{owner}.txt",
                mime_type="text/plain",
                modified_at=datetime.now(UTC),
                status=DriveFileStatus.INDEXED,
            )
            document = Document(
                id=uuid4(),
                drive_file_id=file.id,
                extracted_text=f"private text {owner}",
                extracted_text_hash="synthetic-hash",
            )
            chunk = Chunk(
                id=uuid4(),
                document_id=document.id,
                chunk_index=0,
                text=document.extracted_text,
                metadata_json={},
            )
            db.add(file)
            await db.flush()
            db.add(document)
            await db.flush()
            db.add(chunk)
            files[owner], chunks[owner] = file.id, chunk.id
        issued = await ApplicationSessionService(db, keys).issue_google(
            VerifiedGoogleIdentity("verified-subject-a")
        )
        await db.commit()
    provider = MagicMock()
    provider.get_file_content.return_value = b"synthetic authorized download"
    build = MagicMock(return_value=provider)
    monkeypatch.setattr(DriveContentService, "_build_drive_client", build)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://app.example.invalid"
    ) as client:
        yield SimpleNamespace(
            app=app,
            client=client,
            factory=factory,
            settings=keys,
            issued=issued,
            files=files,
            chunks=chunks,
            provider=provider,
            build=build,
        )
    app.dependency_overrides.clear()


def authenticate(reads):
    reads.client.cookies.set(
        session_cookie_policy(reads.settings).name, reads.issued.credential.get_secret_value()
    )


@pytest.mark.parametrize(
    "credential", ["missing", "malformed", "altered", "expired", "revoked", "wrong_kind"]
)
async def test_all_private_reads_reject_invalid_sessions(private_reads, credential):
    r = private_reads
    if credential != "missing":
        authenticate(r)
    if credential == "malformed":
        r.client.cookies.set(session_cookie_policy(r.settings).name, "not-a-session")
    elif credential == "altered":
        token = r.issued.credential.get_secret_value()
        r.client.cookies.set(
            session_cookie_policy(r.settings).name, ("A" if token[0] != "A" else "B") + token[1:]
        )
    elif credential in {"expired", "revoked", "wrong_kind"}:
        values = {"revoked_at": datetime.now(UTC)}
        if credential == "expired":
            values = {
                "created_at": datetime.now(UTC) - timedelta(days=2),
                "expires_at": datetime.now(UTC) - timedelta(days=1),
            }
        elif credential == "wrong_kind":
            values = {"kind": ApplicationSessionKind.DEMO_VISITOR, "user_id": None}
        async with r.factory() as db:
            await db.execute(
                update(ApplicationSession)
                .where(ApplicationSession.id == r.issued.session_id)
                .values(**values)
            )
            await db.commit()
    for path in ("/files", f"/files/{r.files[USER_A]}/content", f"/sources/{r.chunks[USER_A]}"):
        response = await r.client.get("/api/v1" + path)
        assert response.status_code == 401
        assert "private text" not in response.text
    r.build.assert_not_called()


async def test_listing_and_sources_ignore_supplied_actor(private_reads):
    r = private_reads
    authenticate(r)
    # Headers, query fields and even a GET body cannot establish ownership.
    response = await r.client.request(
        "GET",
        f"/api/v1/files?user_id={USER_B}",
        headers={"x-user-id": str(USER_B)},
        json={"user_id": str(USER_B)},
    )
    assert response.status_code == 200
    assert [f["id"] for f in response.json()["files"]] == [str(r.files[USER_A])]
    source = await r.client.get(f"/api/v1/sources/{r.chunks[USER_A]}?user_id={USER_B}")
    assert source.status_code == 200
    assert source.json()["text"] == f"private text {USER_A}"
    assert source.json()["drive_file_id"] == str(r.files[USER_A])


@pytest.mark.parametrize("resource", ["content", "source"])
async def test_foreign_and_absent_resources_have_identical_404(private_reads, resource):
    r = private_reads
    authenticate(r)
    foreign = r.files[USER_B] if resource == "content" else r.chunks[USER_B]

    def path(identity):
        return (
            f"/api/v1/files/{identity}/content"
            if resource == "content"
            else f"/api/v1/sources/{identity}"
        )

    responses = [await r.client.get(path(identity)) for identity in (foreign, uuid4())]
    assert [response.status_code for response in responses] == [404, 404]
    assert responses[0].json() == responses[1].json()
    assert "private text" not in responses[0].text
    r.build.assert_not_called()
    r.provider.get_file_content.assert_not_called()


async def test_authorized_download_uses_session_owner(private_reads):
    r = private_reads
    authenticate(r)
    await grant(r.factory, r.settings)
    response = await r.client.get(f"/api/v1/files/{r.files[USER_A]}/content?user_id={USER_B}")
    assert response.status_code == 200
    assert response.content == b"synthetic authorized download"
    snapshot = r.build.call_args.args[0]
    assert snapshot.record.user_id == USER_A
    r.provider.get_file_content.assert_called_once_with(f"synthetic-{USER_A}", "text/plain")


@pytest.mark.parametrize(
    "status",
    [
        DriveFileStatus.DISCOVERED,
        DriveFileStatus.INDEXING,
        DriveFileStatus.SKIPPED,
        DriveFileStatus.FAILED,
    ],
)
async def test_ineligible_sources_remain_inaccessible(private_reads, status):
    r = private_reads
    authenticate(r)
    async with r.factory() as db:
        await db.execute(
            update(DriveFile).where(DriveFile.id == r.files[USER_A]).values(status=status)
        )
        await db.commit()
    response = await r.client.get(f"/api/v1/sources/{r.chunks[USER_A]}")
    assert response.status_code == 404


async def test_anonymous_demo_admission_and_owner_scoping(private_reads):
    r = private_reads
    r.settings.demo_mode = True
    r.settings.qdrant_collection = "isolated-synthetic-4b-demo"
    # Dedicated generated PostgreSQL schema only. Build the frozen corpus without indexing/API calls.
    r.settings.database_url = (
        "postgresql+asyncpg://synthetic:synthetic@127.0.0.1/drivemind_session_test_demo"
    )
    manifest = load_manifest()
    vectors = []
    async with r.factory() as db:
        await db.execute(delete(User))
        db.add(User(id=DEMO_USER, email="demo@example.invalid", google_id="demo:synthetic"))
        await db.flush()
        for entry in manifest.files:
            text = manifest.read_sample(entry.filename)
            db.add(
                DriveFile(
                    id=entry.id,
                    user_id=DEMO_USER,
                    drive_file_id=entry.external_id,
                    name=entry.filename,
                    mime_type="text/plain",
                    folder_path="/HarborDesk samples",
                    modified_at=manifest.modified_at,
                    status=DriveFileStatus.INDEXED,
                )
            )
            await db.flush()
            db.add(
                Document(
                    id=entry.document_id,
                    drive_file_id=entry.id,
                    extracted_text=text,
                    extracted_text_hash=entry.sha256,
                )
            )
            await db.flush()
            for part in chunk_text(text):
                chunk = Chunk(
                    id=uuid4(),
                    document_id=entry.document_id,
                    chunk_index=part.chunk_index,
                    text=part.text,
                    metadata_json={"extracted_text_hash": entry.sha256},
                )
                db.add(chunk)
                vectors.append(
                    SimpleNamespace(
                        id=chunk.id,
                        payload={
                            "chunk_id": str(chunk.id),
                            "drive_file_id": str(entry.id),
                            "extracted_text_hash": entry.sha256,
                        },
                    )
                )
        await db.commit()
    vector_client = MagicMock()
    vector_client.collection_exists = AsyncMock(return_value=True)
    vector_client.scroll = AsyncMock(return_value=(vectors, None))
    r.app.state.demo_readiness_client = SimpleNamespace(get=AsyncMock(return_value=vector_client))
    listing = await r.client.get("/api/v1/files")
    assert listing.status_code == 200
    assert listing.json()["total"] == len(manifest.files)
    content = await r.client.get(f"/api/v1/files/{manifest.files[0].id}/content")
    assert content.status_code == 200
    assert content.text == manifest.read_sample(manifest.files[0].filename)
    source = await r.client.get(f"/api/v1/sources/{vectors[0].id}")
    assert source.status_code == 200
    for path in (f"/api/v1/files/{r.files[USER_A]}/content", f"/api/v1/sources/{r.chunks[USER_A]}"):
        assert (await r.client.get(path)).status_code == 404
    r.build.assert_not_called()
    # Approved-corpus checks must reject mixed storage before any read is served.
    async with r.factory() as db:
        db.add(User(id=USER_A, email="foreign@example.invalid", google_id="foreign-subject"))
        await db.commit()
    for path in (
        "/api/v1/files",
        f"/api/v1/files/{manifest.files[0].id}/content",
        f"/api/v1/sources/{vectors[0].id}",
    ):
        assert (await r.client.get(path)).status_code == 503


async def test_second_browser_has_independent_authorized_owner(private_reads):
    r = private_reads
    async with r.factory() as db:
        issued = await ApplicationSessionService(db, r.settings).issue_google(
            VerifiedGoogleIdentity("verified-subject-b")
        )
        await db.commit()
    r.client.cookies.set(
        session_cookie_policy(r.settings).name, issued.credential.get_secret_value()
    )
    listing = await r.client.get("/api/v1/files")
    assert listing.status_code == 200
    assert [file["id"] for file in listing.json()["files"]] == [str(r.files[USER_B])]
    own = await r.client.get(f"/api/v1/sources/{r.chunks[USER_B]}")
    assert own.status_code == 200
    assert own.json()["text"] == f"private text {USER_B}"
    foreign = await r.client.get(f"/api/v1/sources/{r.chunks[USER_A]}")
    assert foreign.status_code == 404
