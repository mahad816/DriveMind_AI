"""Owner-scoped provider identity, migration preservation and real PostgreSQL races."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError, DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.sql import Select

from app.connectors.google_drive.client import DriveChange, DriveFileMetadata
from app.core.config import get_settings
from app.db.enums import DriveFileStatus, IndexingJobStatus
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.db.models.drive_sync_state import DriveSyncState
from app.db.models.indexing_job import IndexingJob
from app.db.models.query_history import QueryHistory
from app.db.models.user import User
from app.db.session import get_db
from app.demo.manifest import load_manifest
from app.main import create_app
from app.security.principal import VerifiedGoogleIdentity
from app.security.session_helpers import session_cookie_policy
from app.services.application_session_service import ApplicationSessionService
from app.services.chunking_service import ChunkingService
from app.services.drive_content_service import DriveContentService
from app.services.drive_sync_service import DriveSyncService
from app.services.indexing_service import IndexingService
from app.services.ingestion_service import IngestionService
from app.services.source_service import SourceService
from .conftest import USER_A, USER_B, DEMO_USER, apply_revision
from .test_encrypted_only_credentials import final_engine

__all__ = ["final_engine"]
REVISION = "20261011_1300"
PROVIDER_ID = "synthetic-shared-google-file"


def metadata(name="shared.txt", timestamp="2026-01-01T00:00:00Z"):
    return DriveFileMetadata(
        id=PROVIDER_ID, name=name, mime_type="text/plain", modified_time=timestamp
    )


@pytest.fixture
async def owner_engine(final_engine):
    async with final_engine.begin() as conn:
        await conn.run_sync(apply_revision, REVISION)
    return final_engine


async def sync_one(factory, settings, owner, name="shared.txt"):
    async with factory() as db:
        outcome = await DriveSyncService(db, settings)._upsert_file(
            owner, metadata(name), folder_path=None
        )
        await db.commit()
        file = await db.scalar(
            select(DriveFile).where(
                DriveFile.user_id == owner, DriveFile.drive_file_id == PROVIDER_ID
            )
        )
        assert file is not None
        return outcome, file.id


async def test_migration_preserves_populated_lineage_and_other_data(final_engine, settings):
    factory = async_sessionmaker(final_engine, expire_on_commit=False)
    async with factory() as db:
        file = DriveFile(
            id=uuid4(),
            user_id=USER_A,
            drive_file_id=PROVIDER_ID,
            name="original.txt",
            mime_type="text/plain",
            modified_at=datetime.now(UTC),
            status=DriveFileStatus.INDEXED,
        )
        db.add(file)
        await db.flush()
        doc = Document(
            id=uuid4(),
            drive_file_id=file.id,
            extracted_text="preserved indexed text",
            extracted_text_hash="preserved-hash",
        )
        db.add(doc)
        await db.flush()
        chunk = Chunk(
            id=uuid4(),
            document_id=doc.id,
            chunk_index=0,
            text=doc.extracted_text,
            metadata_json={"preserved": True},
        )
        job = IndexingJob(id=uuid4(), user_id=USER_A, status=IndexingJobStatus.COMPLETED)
        query = QueryHistory(
            id=uuid4(),
            user_id=USER_A,
            question="preserved question",
            answer="preserved answer",
            citations_json=[{"chunk_id": str(chunk.id)}],
        )
        db.add_all(
            [
                chunk,
                job,
                query,
                DriveSyncState(user_id=USER_A, changes_page_token="preserved-cursor"),
            ]
        )
        await db.commit()
        ids = file.id, doc.id, chunk.id, job.id, query.id
    async with final_engine.begin() as conn:
        assert (await conn.run_sync(lambda c: inspect(c).get_unique_constraints("drive_files")))[0][
            "name"
        ] == "drive_files_drive_file_id_key"
        await conn.run_sync(apply_revision, REVISION)
        constraints = await conn.run_sync(
            lambda c: inspect(c).get_unique_constraints("drive_files")
        )
        assert [(c["name"], c["column_names"]) for c in constraints] == [
            ("uq_drive_files_user_id_drive_file_id", ["user_id", "drive_file_id"])
        ]
        indexes = await conn.run_sync(lambda c: inspect(c).get_indexes("drive_files"))
        assert any(i["name"] == "ix_drive_files_drive_file_id" and not i["unique"] for i in indexes)
        await conn.run_sync(apply_revision, REVISION, downgrade=True)
        await conn.run_sync(apply_revision, REVISION)
    async with factory() as db:
        f = await db.get(DriveFile, ids[0])
        d = await db.get(Document, ids[1])
        c = await db.get(Chunk, ids[2])
        j = await db.get(IndexingJob, ids[3])
        q = await db.get(QueryHistory, ids[4])
        assert f is not None and d is not None and c is not None
        assert j is not None and q is not None
        assert (
            f.user_id == USER_A and f.name == "original.txt" and f.status == DriveFileStatus.INDEXED
        )
        assert d.drive_file_id == f.id and d.extracted_text == "preserved indexed text"
        assert (
            c.document_id == d.id
            and c.text == d.extracted_text
            and c.metadata_json == {"preserved": True}
        )
        assert j.status == IndexingJobStatus.COMPLETED and q.answer == "preserved answer"
        state = await db.get(DriveSyncState, USER_A)
        assert state is not None and state.changes_page_token == "preserved-cursor"
        assert len((await db.scalars(select(User))).all()) == 3


async def test_two_owners_resync_preserves_independent_identity(owner_engine, settings):
    factory = async_sessionmaker(owner_engine, expire_on_commit=False)
    _, a = await sync_one(factory, settings, USER_A, "A.txt")
    _, b = await sync_one(factory, settings, USER_B, "B.txt")
    assert a != b
    assert await sync_one(factory, settings, USER_A, "A-renamed.txt") == ("updated", a)
    assert await sync_one(factory, settings, USER_B, "B-renamed.txt") == ("updated", b)
    assert await sync_one(factory, settings, USER_A, "A-renamed.txt") == ("unchanged", a)
    async with factory() as db:
        rows = {f.user_id: f for f in (await db.scalars(select(DriveFile))).all()}
        assert rows[USER_A].name == "A-renamed.txt" and rows[USER_B].name == "B-renamed.txt"
        db.add(
            DriveFile(
                user_id=USER_A,
                drive_file_id=PROVIDER_ID,
                name="duplicate",
                mime_type="text/plain",
                modified_at=datetime.now(UTC),
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()
    async with factory() as db:
        assert len((await db.scalars(select(DriveFile))).all()) == 2


@pytest.mark.parametrize("owners", [(USER_A, USER_B), (USER_A, USER_A)])
async def test_concurrent_first_insert_with_real_uniqueness_recovery(
    owner_engine, settings, owners
):
    factory = async_sessionmaker(owner_engine, expire_on_commit=False)
    barrier = asyncio.Barrier(2)

    async def worker(owner):
        async with factory() as db:
            scalar = db.scalar
            first = True

            async def synchronize_initial_lookup(statement, *args, **kwargs):
                nonlocal first
                result = await scalar(statement, *args, **kwargs)
                if first and isinstance(statement, Select):
                    first = False
                    assert result is None
                    await barrier.wait()
                return result

            with patch.object(db, "scalar", side_effect=synchronize_initial_lookup):
                outcome = await DriveSyncService(db, settings)._upsert_file(
                    owner, metadata(), folder_path=None
                )
                await db.commit()
                return outcome

    outcomes = await asyncio.wait_for(
        asyncio.gather(*(worker(owner) for owner in owners)), timeout=10
    )
    assert sorted(outcomes) == (
        ["created", "unchanged"] if owners[0] == owners[1] else ["created", "created"]
    )
    async with factory() as db:
        rows = list((await db.scalars(select(DriveFile))).all())
        assert len(rows) == len(set(owners))
        assert {r.user_id for r in rows} == set(owners)
        assert all(r.name == "shared.txt" and r.status == DriveFileStatus.DISCOVERED for r in rows)


async def test_concurrent_updates_use_current_locked_row(owner_engine, settings):
    factory = async_sessionmaker(owner_engine, expire_on_commit=False)
    _, identity = await sync_one(factory, settings, USER_A)
    outcomes = await asyncio.wait_for(
        asyncio.gather(
            sync_one(factory, settings, USER_A, "one.txt"),
            sync_one(factory, settings, USER_A, "two.txt"),
        ),
        timeout=10,
    )
    assert all(result == "updated" and file_id == identity for result, file_id in outcomes)
    async with factory() as db:
        rows = list((await db.scalars(select(DriveFile))).all())
        assert len(rows) == 1 and rows[0].name in {"one.txt", "two.txt"}


@pytest.mark.parametrize("change", ["removed", "trashed", "unsupported"])
async def test_changes_remove_only_the_correct_owner(owner_engine, settings, change):
    factory = async_sessionmaker(owner_engine, expire_on_commit=False)
    _, a = await sync_one(factory, settings, USER_A)
    _, b = await sync_one(factory, settings, USER_B)
    async with factory() as db:
        client = MagicMock()
        item = metadata()
        item.trashed = change == "trashed"
        if change == "unsupported":
            item.mime_type = "application/unsupported"
        client.list_files.return_value = []  # Folder lookup.
        client.list_changes.return_value = (
            [DriveChange(file_id=PROVIDER_ID, removed=change == "removed", file=item)],
            "A-next",
        )
        svc = DriveSyncService(db, settings)
        db.add(DriveSyncState(user_id=USER_A, changes_page_token="A-before"))
        await db.flush()
        state = await db.get(DriveSyncState, USER_A)
        user = await db.get(User, USER_A)
        assert user is not None and state is not None
        result = await svc._run_incremental_sync(user, client, state)
        await db.commit()
        assert result[3] == 1
        first, second = await db.get(DriveFile, a), await db.get(DriveFile, b)
        assert first is not None and second is not None
        assert first.status == DriveFileStatus.SKIPPED
        assert second.status == DriveFileStatus.DISCOVERED
        state = await db.get(DriveSyncState, USER_A)
        assert state is not None and state.changes_page_token == "A-next"
        assert await db.get(DriveSyncState, USER_B) is None


async def test_full_sync_missing_reconciliation_stays_with_owner(owner_engine, settings):
    factory = async_sessionmaker(owner_engine, expire_on_commit=False)
    _, a = await sync_one(factory, settings, USER_A)
    _, b = await sync_one(factory, settings, USER_B)
    async with factory() as db:
        client = MagicMock()
        client.get_start_page_token.return_value = "B-next"
        client.list_files.return_value = []
        user = await db.get(User, USER_B)
        assert user is not None
        result = await DriveSyncService(db, settings)._run_full_sync(user, client)
        await db.commit()
        assert result[3] == 1
        first, second = await db.get(DriveFile, a), await db.get(DriveFile, b)
        assert first is not None and second is not None
        assert first.status == DriveFileStatus.DISCOVERED
        assert second.status == DriveFileStatus.SKIPPED
        state = await db.get(DriveSyncState, USER_B)
        assert state is not None and state.changes_page_token == "B-next"
        assert await db.get(DriveSyncState, USER_A) is None


async def test_downgrade_refuses_duplicate_provider_ids_without_data_loss(owner_engine, settings):
    factory = async_sessionmaker(owner_engine, expire_on_commit=False)
    _, a = await sync_one(factory, settings, USER_A)
    _, b = await sync_one(factory, settings, USER_B)
    with pytest.raises(DBAPIError, match="Cannot restore global Drive file uniqueness"):
        async with owner_engine.begin() as conn:
            await conn.run_sync(apply_revision, REVISION, downgrade=True)
    async with factory() as db:
        assert {f.id for f in (await db.scalars(select(DriveFile))).all()} == {a, b}
    async with owner_engine.connect() as conn:
        assert (await conn.run_sync(lambda c: inspect(c).get_unique_constraints("drive_files")))[0][
            "name"
        ] == "uq_drive_files_user_id_drive_file_id"


async def test_same_provider_documents_chunks_vectors_and_private_routes(
    owner_engine, settings, monkeypatch
):
    factory = async_sessionmaker(owner_engine, expire_on_commit=False)
    _, a = await sync_one(factory, settings, USER_A)
    _, b = await sync_one(factory, settings, USER_B)
    chunks = {}
    async with factory() as db:
        for owner, file_id in ((USER_A, a), (USER_B, b)):
            file = await db.get(DriveFile, file_id)
            assert file is not None
            file.status = DriveFileStatus.INDEXING
            doc = Document(
                id=uuid4(),
                drive_file_id=file_id,
                extracted_text=f"Separate private text for {owner}.",
                extracted_text_hash=str(owner),
            )
            db.add(doc)
            await db.flush()
            await ChunkingService(db, settings).sync_document_chunks(doc)
            chunk = await db.scalar(select(Chunk).where(Chunk.document_id == doc.id))
            assert chunk is not None
            chunks[owner] = chunk.id
            assert IndexingService(db, settings)._chunk_payload(chunk, file)[
                "drive_file_id"
            ] == str(file_id)
            file.status = DriveFileStatus.INDEXED
        await db.flush()
        assert chunks[USER_A] != chunks[USER_B]
        for service in (
            IngestionService(db, settings),
            ChunkingService(db, settings),
            IndexingService(db, settings),
        ):
            assert (await service._get_drive_file(USER_A, a)).id == a
            with pytest.raises(ValueError, match="Synced file not found"):
                await service._get_drive_file(USER_A, b)
        assert await SourceService(db).get_source_chunk(chunks[USER_B], user_id=USER_A) is None
        issued = await ApplicationSessionService(db, settings).issue_google(
            VerifiedGoogleIdentity("verified-subject-a")
        )
        await db.commit()
    app = create_app()

    async def database():
        async with factory() as db:
            yield db

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_settings] = lambda: settings
    monkeypatch.setattr("app.services.drive_sync_service.get_settings", lambda: settings)
    monkeypatch.setattr("app.services.drive_content_service.get_settings", lambda: settings)
    forbidden = AsyncMock(side_effect=AssertionError("Foreign file must not load credentials"))
    monkeypatch.setattr(DriveContentService, "_load_oauth_token", forbidden)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://app.example.invalid"
    ) as client:
        client.cookies.set(
            session_cookie_policy(settings).name, issued.credential.get_secret_value()
        )
        listing = await client.get("/api/v1/files")
        assert [f["id"] for f in listing.json()["files"]] == [str(a)]
        assert (await client.get(f"/api/v1/files/{b}/content")).status_code == 404
        assert (await client.get(f"/api/v1/sources/{chunks[USER_B]}")).status_code == 404
        assert (await client.get(f"/api/v1/sources/{chunks[USER_A]}")).status_code == 200
    forbidden.assert_not_awaited()


async def test_demo_manifest_file_identity_is_compatible(owner_engine):
    factory = async_sessionmaker(owner_engine, expire_on_commit=False)
    entry = load_manifest().files[0]
    async with factory() as db:
        db.add(
            DriveFile(
                id=entry.id,
                user_id=DEMO_USER,
                drive_file_id=entry.external_id,
                name=entry.filename,
                mime_type="text/plain",
                folder_path="/HarborDesk samples",
                modified_at=load_manifest().modified_at,
                status=DriveFileStatus.INDEXED,
            )
        )
        await db.commit()
    async with factory() as db:
        file = await db.get(DriveFile, entry.id)
        assert file is not None
        assert file.user_id == DEMO_USER and file.drive_file_id == entry.external_id
        assert file.status == DriveFileStatus.INDEXED
