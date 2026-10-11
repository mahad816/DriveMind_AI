"""Committed managed jobs, real PostgreSQL claims and real Qdrant writes.

Only Google network methods and embedding transport are faked. Transactions,
encrypted grants, stage algorithms, constraints and vector acknowledgements are real.
"""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker
from qdrant_client.models import UpdateResult, UpdateStatus

from app.connectors.google_drive.client import DriveFileMetadata
from app.db.enums import DriveFileStatus, IndexingJobStatus, IndexingOperation
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.db.models.drive_sync_state import DriveSyncState
from app.db.models.indexing_job import IndexingJob
from app.db.models.google_oauth_token import GoogleOAuthToken
from app.embeddings.vector_store import QdrantVectorStore
from app.services.drive_content_service import DriveContentService
from app.services.drive_sync_service import DriveSyncService
from app.services.indexing_job_service import IndexingJobService
from app.services.indexing_worker import IndexingWorker, StageProgress
from .conftest import USER_A, USER_B
from .test_encrypted_only_credentials import final_engine, keys, grant
from .test_owner_scoped_drive_identity import owner_engine
from .test_qdrant_tenant_io import qdrant_client
from .test_indexing_admission import admission

__all__ = ["final_engine", "keys", "owner_engine", "qdrant_client", "admission"]


class Embeddings:
    model_name = "synthetic"
    embedding_dimension = 3

    async def embed_texts(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


@pytest.fixture
async def world(owner_engine, keys, qdrant_client, monkeypatch):
    import os

    settings = keys.model_copy(
        update={
            "qdrant_url": os.environ["QDRANT_TEST_URL"],
            "qdrant_collection": "drivemind_4e2_test_" + uuid4().hex,
        }
    )
    factory = async_sessionmaker(owner_engine, expire_on_commit=False)
    seen = []

    class Google:
        def __init__(self, owner):
            self.owner = owner

        def get_file_content(self, provider_id, mime):
            seen.append(("content", self.owner, provider_id))
            return f"Synthetic owner {self.owner} answer-bearing text.".encode()

        def get_start_page_token(self):
            return str(self.owner) + "-cursor"

        def list_files(self, *, supported_only=True, **kwargs):
            if not supported_only:
                return []
            seen.append(("sync", self.owner))
            return [
                DriveFileMetadata(
                    id="shared-provider",
                    name=str(self.owner) + ".txt",
                    mime_type="text/plain",
                    modified_time="2026-10-12T00:00:00Z",
                )
            ]

        def list_changes(self, token):
            seen.append(("changes", self.owner, token))
            return [], str(self.owner) + "-next-cursor"

    def client(service, snapshot):
        return Google(snapshot.record.user_id)

    monkeypatch.setattr(DriveSyncService, "_build_drive_client", client)
    monkeypatch.setattr(DriveContentService, "_build_drive_client", client)
    files = {}
    for owner in [USER_A, USER_B]:
        await grant(factory, settings, owner)
        async with factory() as db:
            file = DriveFile(
                user_id=owner,
                drive_file_id="shared-provider",
                name="shared.txt",
                mime_type="text/plain",
                modified_at=datetime.now(UTC),
            )
            db.add(file)
            await db.commit()
            files[owner] = file.id
    worker = IndexingWorker(factory, settings, embedding_service=Embeddings())
    try:
        yield SimpleNamespace(
            factory=factory,
            settings=settings,
            worker=worker,
            files=files,
            seen=seen,
            google=Google,
            client=qdrant_client,
            engine=owner_engine,
        )
    finally:
        if await qdrant_client.collection_exists(settings.qdrant_collection):
            await qdrant_client.delete_collection(settings.qdrant_collection)


async def enqueue(w, operation, owner=USER_A, file_id=None, full=False):
    async with w.factory() as db:
        job = await IndexingJobService(db).admit(
            owner,
            operation,
            file_id=file_id,
            full_sync=full,
        )
        return job.id


async def job(w, job_id):
    async with w.factory() as db:
        return await db.get(IndexingJob, job_id)


async def document(w, owner=USER_A, text="Synthetic searchable chunk text."):
    async with w.factory() as db:
        file = await db.get(DriveFile, w.files[owner])
        file.status = DriveFileStatus.INDEXING
        doc = Document(
            drive_file_id=file.id, extracted_text=text, extracted_text_hash="hash-" + str(owner)
        )
        db.add(doc)
        await db.commit()
        return doc.id


async def test_two_workers_claim_once_and_other_owner_is_independent(world):
    w = world
    first = await enqueue(w, IndexingOperation.CHUNK)
    other = IndexingWorker(w.factory, w.settings, embedding_service=Embeddings())
    claims = await asyncio.gather(w.worker.claim_next(), other.claim_next())
    assert sum(c is not None for c in claims) == 1
    claim = next(c for c in claims if c is not None)
    assert claim.job_id == first
    assert (await job(w, first)).claim_id == claim.claim_id
    second = await enqueue(w, IndexingOperation.CHUNK, USER_B)
    b = await other.claim_next()
    assert b is not None
    assert b.job_id == second and b.user_id == USER_B
    await asyncio.gather(w.worker.execute(claim), other.execute(b))
    assert (await job(w, first)).status == IndexingJobStatus.COMPLETED
    assert (await job(w, second)).status == IndexingJobStatus.COMPLETED


async def test_skip_locked_and_historical_jobs_are_not_claimed(world):
    w = world
    async with w.factory() as db:
        db.add(IndexingJob(user_id=USER_A, status=IndexingJobStatus.QUEUED))
        await db.commit()
    assert await w.worker.claim_next() is None
    async with w.factory() as db:
        await db.execute(
            update(IndexingJob)
            .where(IndexingJob.operation.is_(None))
            .values(status=IndexingJobStatus.COMPLETED)
        )
        await db.commit()
    a = await enqueue(w, IndexingOperation.CHUNK)
    b = await enqueue(w, IndexingOperation.CHUNK, USER_B)
    async with w.factory() as blocker:
        await blocker.scalar(select(IndexingJob).where(IndexingJob.id == a).with_for_update())
        claim = await w.worker.claim_next()
        assert claim.job_id == b
        await blocker.rollback()
    assert (await w.worker.claim_next()).job_id == a


@pytest.mark.parametrize("operation", list(IndexingOperation))
async def test_owner_bound_stage_uses_existing_job_and_real_storage(world, operation):
    w = world
    if operation in [IndexingOperation.CHUNK, IndexingOperation.BUILD]:
        await document(w, USER_A)
        await document(w, USER_B, text="Foreign B-only content.")
    jid = await enqueue(
        w, operation, file_id=None if operation == IndexingOperation.SYNC else w.files[USER_A]
    )
    assert await w.worker.run_once()
    completed = await job(w, jid)
    assert completed.status == IndexingJobStatus.COMPLETED
    assert completed.processed == 1
    async with w.factory() as db:
        assert await db.scalar(select(func.count()).select_from(IndexingJob)) == 1
        b = await db.get(DriveFile, w.files[USER_B])
        assert b.status == (
            DriveFileStatus.INDEXING
            if operation in [IndexingOperation.CHUNK, IndexingOperation.BUILD]
            else DriveFileStatus.DISCOVERED
        )
        if operation == IndexingOperation.INGEST:
            doc = await db.scalar(select(Document).where(Document.drive_file_id == w.files[USER_A]))
            assert str(USER_A) in doc.extracted_text and str(USER_B) not in doc.extracted_text
        if operation == IndexingOperation.BUILD:
            chunk = await db.scalar(
                select(Chunk).join(Document).where(Document.drive_file_id == w.files[USER_A])
            )
            records = await w.client.retrieve(
                w.settings.qdrant_collection, [str(chunk.id)], with_vectors=True
            )
            assert records[0].payload["user_id"] == str(USER_A)
            assert records[0].payload["drive_file_id"] == str(w.files[USER_A])
            assert records[0].payload["chunk_id"] == str(chunk.id)
            store = QdrantVectorStore(w.settings, client=w.client)
            assert [
                h.chunk_id
                for h in await store.search_similar([1.0, 0.0, 0.0], user_id=USER_A, limit=1)
            ] == [chunk.id]
            assert await store.search_similar([1.0, 0.0, 0.0], user_id=USER_B, limit=1) == []


async def test_incremental_sync_cursors_and_accounts_stay_separate(world):
    w = world
    for owner in [USER_A, USER_B]:
        async with w.factory() as db:
            db.add(DriveSyncState(user_id=owner, changes_page_token=str(owner) + "-old"))
            await db.commit()
        jid = await enqueue(w, IndexingOperation.SYNC, owner)
        assert await w.worker.run_once()
        assert (await job(w, jid)).status == IndexingJobStatus.COMPLETED
    assert ("changes", USER_A, str(USER_A) + "-old") in w.seen
    assert ("changes", USER_B, str(USER_B) + "-old") in w.seen


@pytest.mark.parametrize(
    "operation", [IndexingOperation.INGEST, IndexingOperation.CHUNK, IndexingOperation.BUILD]
)
async def test_deleted_target_never_becomes_all_files(world, operation):
    w = world
    jid = await enqueue(w, operation, file_id=w.files[USER_A])
    async with w.factory() as db:
        await db.execute(delete(DriveFile).where(DriveFile.id == w.files[USER_A]))
        await db.commit()
    await w.worker.run_once()
    assert (await job(w, jid)).status == IndexingJobStatus.FAILED
    assert not w.seen
    assert not await w.client.collection_exists(w.settings.qdrant_collection)


async def test_foreign_target_is_rejected_even_for_tampered_persisted_inputs(world):
    w = world
    jid = await enqueue(w, IndexingOperation.INGEST)
    async with w.factory() as db:
        await db.execute(
            update(IndexingJob).where(IndexingJob.id == jid).values(file_id=w.files[USER_B])
        )
        await db.commit()
    await w.worker.run_once()
    assert (await job(w, jid)).status == IndexingJobStatus.FAILED
    assert not w.seen


async def test_claim_fencing_and_only_one_terminal_transition(world):
    w = world
    jid = await enqueue(w, IndexingOperation.CHUNK)
    claim = await w.worker.claim_next()
    assert not await w.worker.finalize(replace(claim, claim_id=uuid4()), StageProgress())
    winners = await asyncio.gather(
        w.worker.finalize(claim, StageProgress()),
        w.worker.finalize(claim, StageProgress(), error="safe failure"),
    )
    assert winners.count(True) == 1
    assert (await job(w, jid)).status in [IndexingJobStatus.FAILED, IndexingJobStatus.COMPLETED]


async def test_sql_flush_failure_rolls_back_and_uses_fresh_finalization(world, monkeypatch):
    w = world
    from app.services.chunking_service import ChunkingService
    from sqlalchemy.sql.dml import Update
    from sqlalchemy.ext.asyncio import AsyncSession

    broken_sessions, finishing_sessions = [], []
    original_execute = AsyncSession.execute

    async def observe(session, statement, *args, **kwargs):
        if (
            isinstance(statement, Update)
            and getattr(statement.table, "name", None) == "indexing_jobs"
        ):
            finishing_sessions.append(session)
        return await original_execute(session, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", observe)

    await document(w)

    async def invalid(service, doc, **kwargs):
        broken_sessions.append(service.db)
        service.db.add(
            Chunk(document_id=uuid4(), chunk_index=0, text="secret-marker", metadata_json={})
        )
        await service.db.flush()  # Actual PostgreSQL FK violation poisons the stage session.

    monkeypatch.setattr(ChunkingService, "_replace_chunks", invalid)
    jid = await enqueue(w, IndexingOperation.CHUNK)
    await w.worker.run_once()
    result = await job(w, jid)
    assert result.status == IndexingJobStatus.FAILED
    assert "secret-marker" not in result.error
    assert len(finishing_sessions) == 1
    assert finishing_sessions[0] is not broken_sessions[0]
    async with w.factory() as db:
        assert await db.scalar(select(func.count()).select_from(Chunk)) == 0


async def test_content_read_does_not_commit_caller_writes(world):
    w = world
    async with w.factory() as db:
        file = await db.get(DriveFile, w.files[USER_A])
        file.name = "uncommitted caller write"
        content = await DriveContentService(db, w.settings).fetch_file_content(file.id, USER_A)
        assert content.data
        async with w.factory() as observer:
            assert (await observer.get(DriveFile, file.id)).name == "shared.txt"
        await db.rollback()


@pytest.mark.parametrize("operation", [IndexingOperation.SYNC, IndexingOperation.INGEST])
async def test_revoked_grant_never_uses_second_account(world, operation):
    w = world
    async with w.factory() as db:
        await db.execute(
            update(GoogleOAuthToken)
            .where(GoogleOAuthToken.user_id == USER_A)
            .values(grant_status="REAUTH_REQUIRED")
        )
        await db.commit()
    jid = await enqueue(w, operation)
    await w.worker.run_once()
    assert (await job(w, jid)).status == IndexingJobStatus.FAILED
    assert not w.seen


async def test_stale_document_after_embedding_cannot_be_indexed(world):
    w = world
    doc_id = await document(w)

    class Changed(Embeddings):
        async def embed_texts(self, texts):
            async with w.factory() as db:
                await db.execute(
                    update(Document)
                    .where(Document.id == doc_id)
                    .values(extracted_text_hash="new-hash")
                )
                await db.commit()
            return await super().embed_texts(texts)

    w.worker.embedding_service = Changed()
    jid = await enqueue(w, IndexingOperation.BUILD)
    await w.worker.run_once()
    result = await job(w, jid)
    assert result.status == IndexingJobStatus.FAILED and result.recovery_required
    async with w.factory() as db:
        assert (await db.get(DriveFile, w.files[USER_A])).status != DriveFileStatus.INDEXED


@pytest.mark.parametrize("status", [UpdateStatus.ACKNOWLEDGED, UpdateStatus.COMPLETED])
async def test_partial_or_lost_qdrant_acknowledgement_is_not_success(world, monkeypatch, status):
    w = world
    await document(w)
    from qdrant_client import AsyncQdrantClient

    original = AsyncQdrantClient.upsert

    async def uncertain(client, **kwargs):
        await original(client, **kwargs)  # Actual vectors written to the disposable server.
        if status == UpdateStatus.COMPLETED:
            raise ConnectionError("synthetic-secret provider-body")  # Lost acknowledgement.
        return UpdateResult(operation_id=1, status=status)

    monkeypatch.setattr(AsyncQdrantClient, "upsert", uncertain)
    jid = await enqueue(w, IndexingOperation.BUILD)
    await w.worker.run_once()
    result = await job(w, jid)
    assert result.status == IndexingJobStatus.FAILED and result.recovery_required
    assert "synthetic-secret" not in result.error
    assert (await w.client.count(w.settings.qdrant_collection, exact=True)).count == 1


async def test_cancellation_finalizes_without_false_success(world):
    w = world
    await document(w)
    entered = asyncio.Event()

    class Blocked(Embeddings):
        async def embed_texts(self, texts):
            entered.set()
            await asyncio.Event().wait()
            return []

    w.worker.embedding_service = Blocked()
    jid = await enqueue(w, IndexingOperation.BUILD)
    task = asyncio.create_task(w.worker.run_once())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    result = await job(w, jid)
    assert result.status == IndexingJobStatus.FAILED and result.recovery_required


async def test_empty_chunk_outcome_and_default_activation(world):
    w = world
    await document(w, text="   ")
    jid = await enqueue(w, IndexingOperation.BUILD)
    await w.worker.run_once()
    assert (await job(w, jid)).status == IndexingJobStatus.COMPLETED
    async with w.factory() as db:
        assert (await db.get(DriveFile, w.files[USER_A])).status == DriveFileStatus.SKIPPED
    from app.main import create_app

    assert create_app().state.indexing_admission_ready is False
    with pytest.raises(ValueError, match="demo"):
        IndexingWorker(w.factory, w.settings.model_copy(update={"demo_mode": True}))


async def test_startup_cleanup_does_not_corrupt_managed_running_jobs(world, monkeypatch):
    w = world
    import app.main as main

    jid = await enqueue(w, IndexingOperation.CHUNK)
    claim = await w.worker.claim_next()
    monkeypatch.setattr(main, "SessionLocal", w.factory)
    await main._cleanup_stuck_jobs()
    current = await job(w, jid)
    assert current.status == IndexingJobStatus.RUNNING and current.claim_id == claim.claim_id


async def test_independent_owners_build_concurrently_without_crossing_lineage(world, monkeypatch):
    w = world
    store = QdrantVectorStore(w.settings, client=w.client)
    jobs = {}
    for owner in [USER_A, USER_B]:
        await document(w, owner, text=f"Private corpus for {owner}.")
        jobs[owner] = await enqueue(w, IndexingOperation.BUILD, owner, w.files[owner])
    other = IndexingWorker(w.factory, w.settings, embedding_service=Embeddings())
    from qdrant_client import AsyncQdrantClient

    original_exists = AsyncQdrantClient.collection_exists
    barrier = asyncio.Barrier(2)
    checks = 0

    async def concurrent_initialization(client, collection_name):
        nonlocal checks
        exists = await original_exists(client, collection_name)
        checks += 1
        if checks <= 2:
            assert not exists
            await barrier.wait()
        return exists

    monkeypatch.setattr(AsyncQdrantClient, "collection_exists", concurrent_initialization)
    await asyncio.gather(w.worker.run_once(), other.run_once())
    for owner in [USER_A, USER_B]:
        assert (await job(w, jobs[owner])).status == IndexingJobStatus.COMPLETED
        hits = await store.search_similar([1.0, 0.0, 0.0], user_id=owner, limit=10)
        assert len(hits) == 1
        async with w.factory() as db:
            actual_owner = await db.scalar(
                select(DriveFile.user_id)
                .join(Document)
                .join(Chunk)
                .where(Chunk.id == hits[0].chunk_id)
            )
            assert actual_owner == owner


async def test_partial_ingestion_preserves_success_and_marks_failed_job(world, monkeypatch):
    w = world
    from app.connectors.google_drive.client import DriveClientError

    original = w.google.get_file_content

    def download(client, provider, mime):
        if provider == "synthetic-failed-provider":
            raise DriveClientError("secret-provider-body")
        return original(client, provider, mime)

    monkeypatch.setattr(w.google, "get_file_content", download)
    async with w.factory() as db:
        bad = DriveFile(
            user_id=USER_A,
            drive_file_id="synthetic-failed-provider",
            name="failed.txt",
            mime_type="text/plain",
            modified_at=datetime.now(UTC),
        )
        db.add(bad)
        await db.commit()
        bad_id = bad.id
    jid = await enqueue(w, IndexingOperation.INGEST)
    await w.worker.run_once()
    result = await job(w, jid)
    assert result.status == IndexingJobStatus.FAILED
    assert (result.total, result.processed, result.succeeded, result.failed) == (2, 2, 1, 1)
    assert "secret-provider-body" not in result.error
    async with w.factory() as db:
        assert (await db.get(DriveFile, bad_id)).status == DriveFileStatus.FAILED
        assert (await db.get(DriveFile, w.files[USER_A])).status == DriveFileStatus.INDEXING


@pytest.mark.parametrize("change", ["chunk", "claim", "grant"])
async def test_changes_during_external_work_are_fenced(world, change, monkeypatch):
    w = world
    if change == "grant":
        original = w.google.list_files

        def reconnect(client, **kwargs):
            # Google calls execute in a thread. Return controlled metadata only;
            # the pre-apply hook below performs the synthetic concurrent SQL write.
            return original(client, **kwargs)

        monkeypatch.setattr(w.google, "list_files", reconnect)
        from app.services.google_credential_repository import GoogleCredentialRepository
        from pydantic import SecretStr

        original_full = DriveSyncService._run_full_sync

        async def changed(service, user, client, *, before_apply=None):
            async with w.factory() as db:
                await GoogleCredentialRepository(db, w.settings).write_verified_grant(
                    USER_A,
                    access_token=SecretStr("new-synthetic"),
                    refresh_token=SecretStr("new-refresh"),
                    token_expiry=datetime.now(UTC),
                    scopes="readonly",
                )
                await db.commit()
            return await original_full(service, user, client, before_apply=before_apply)

        monkeypatch.setattr(DriveSyncService, "_run_full_sync", changed)
        jid = await enqueue(w, IndexingOperation.SYNC)
        await w.worker.run_once()
        assert (await job(w, jid)).status == IndexingJobStatus.FAILED
        async with w.factory() as db:
            assert (await db.get(DriveFile, w.files[USER_A])).name == "shared.txt"
        return
    await document(w)
    jid = await enqueue(w, IndexingOperation.BUILD)
    replacement = uuid4()

    class Changed(Embeddings):
        async def embed_texts(self, texts):
            async with w.factory() as db:
                if change == "chunk":
                    await db.execute(update(Chunk).values(text="changed snapshot"))
                else:
                    await db.execute(
                        update(IndexingJob)
                        .where(IndexingJob.id == jid)
                        .values(claim_id=replacement)
                    )
                await db.commit()
            return await super().embed_texts(texts)

    w.worker.embedding_service = Changed()
    await w.worker.run_once()
    result = await job(w, jid)
    if change == "claim":
        assert result.status == IndexingJobStatus.RUNNING and result.claim_id == replacement
    else:
        assert result.status == IndexingJobStatus.FAILED
    assert result.recovery_required
    async with w.factory() as db:
        assert (await db.get(DriveFile, w.files[USER_A])).status != DriveFileStatus.INDEXED


async def test_partial_remote_batch_is_visible_and_recovery_blocks_new_admission(
    world, monkeypatch
):
    w = world
    await document(w, text="Synthetic text. " * 500)
    from qdrant_client import AsyncQdrantClient
    from app.services.indexing_job_service import IndexingAdmissionConflict

    original = AsyncQdrantClient.upsert

    async def partial(client, **kwargs):
        kwargs["points"] = kwargs["points"][:1]
        await original(client, **kwargs)
        raise ConnectionError("Lost synthetic batch response")

    monkeypatch.setattr(AsyncQdrantClient, "upsert", partial)
    jid = await enqueue(w, IndexingOperation.BUILD)
    await w.worker.run_once()
    result = await job(w, jid)
    assert result.status == IndexingJobStatus.FAILED and result.recovery_required
    assert (await w.client.count(w.settings.qdrant_collection, exact=True)).count == 1
    with pytest.raises(IndexingAdmissionConflict):
        await enqueue(w, IndexingOperation.CHUNK)
    assert await w.worker.claim_next() is None


async def test_managed_demo_identity_cannot_be_claimed_in_normal_mode(world):
    w = world
    from .conftest import DEMO_USER

    async with w.factory() as db:
        db.add(
            IndexingJob(
                user_id=DEMO_USER,
                operation=IndexingOperation.CHUNK,
                status=IndexingJobStatus.QUEUED,
            )
        )
        await db.commit()
    assert await w.worker.claim_next() is None


async def test_real_session_admission_worker_and_exact_job_polling(admission):
    r = admission
    async with r.factory() as db:
        file = await db.get(DriveFile, r.files[USER_A])
        file.status = DriveFileStatus.INDEXING
        db.add(
            Document(
                drive_file_id=file.id,
                extracted_text="Owned API worker evidence.",
                extracted_text_hash="api-hash",
            )
        )
        await db.commit()
    response = await r.client.post(
        "/api/v1/index/chunk", headers=r.headers[USER_A], params={"file_id": str(r.files[USER_A])}
    )
    assert response.status_code == 202
    from uuid import UUID

    jid = UUID(response.json()["job_id"])
    async with r.factory() as db:
        accepted = await db.get(IndexingJob, jid)
        assert accepted.status == IndexingJobStatus.QUEUED and accepted.user_id == USER_A
    worker = IndexingWorker(r.factory, r.settings)
    assert await worker.run_once()
    status = await r.client.get(
        "/api/v1/index/status", headers=r.headers[USER_A], params={"job_id": str(jid)}
    )
    assert status.status_code == 200
    assert status.json()["job"]["id"] == str(jid)
    assert status.json()["job"]["status"] == "completed"
    foreign = await r.client.get(
        "/api/v1/index/status", headers=r.headers[USER_B], params={"job_id": str(jid)}
    )
    assert foreign.status_code == 404


@pytest.mark.parametrize("operation", [IndexingOperation.CHUNK, IndexingOperation.BUILD])
async def test_skipped_target_stops_before_loading_preserved_text(world, operation):
    w = world
    doc_id = await document(w, text="Preserved synthetic stale content.")
    async with w.factory() as db:
        await db.execute(
            update(DriveFile)
            .where(DriveFile.id == w.files[USER_A])
            .values(status=DriveFileStatus.SKIPPED)
        )
        await db.commit()
    jid = await enqueue(w, operation, file_id=w.files[USER_A])
    from sqlalchemy import event

    statements = []

    def observe(connection, cursor, statement, params, context, many):
        statements.append(statement.lower())

    event.listen(w.engine.sync_engine, "before_cursor_execute", observe)
    try:
        await w.worker.run_once()
    finally:
        event.remove(w.engine.sync_engine, "before_cursor_execute", observe)
    assert not any("from documents" in statement for statement in statements)
    result = await job(w, jid)
    assert result.status == IndexingJobStatus.COMPLETED and result.skipped == 1
    async with w.factory() as db:
        assert (
            await db.get(Document, doc_id)
        ).extracted_text == "Preserved synthetic stale content."
        assert (await db.get(DriveFile, w.files[USER_A])).status == DriveFileStatus.SKIPPED
    assert not await w.client.collection_exists(w.settings.qdrant_collection)


async def test_real_qdrant_write_rejection_cannot_complete_build(world):
    w = world
    await document(w)
    from qdrant_client.models import Distance, VectorParams

    # Existing incompatible vector dimensions cause a genuine server-side 400.
    await w.client.create_collection(
        w.settings.qdrant_collection, vectors_config=VectorParams(size=4, distance=Distance.COSINE)
    )
    jid = await enqueue(w, IndexingOperation.BUILD)
    await w.worker.run_once()
    result = await job(w, jid)
    assert result.status == IndexingJobStatus.FAILED and result.recovery_required
    assert (await w.client.count(w.settings.qdrant_collection, exact=True)).count == 0
    async with w.factory() as db:
        assert (await db.get(DriveFile, w.files[USER_A])).status == DriveFileStatus.FAILED


async def test_actual_commit_failure_rolls_back_and_does_not_count_success(world, monkeypatch):
    w = world
    from sqlalchemy import inspect
    from app.services.chunking_service import ChunkingService

    await document(w)
    # Change only this disposable fixture's FK timing: flush succeeds, COMMIT
    # genuinely fails in PostgreSQL. This is not a mocked commit failure.
    async with w.engine.begin() as conn:
        foreign_keys = await conn.run_sync(lambda c: inspect(c).get_foreign_keys("chunks"))
        name = next(
            fk["name"] for fk in foreign_keys if fk["constrained_columns"] == ["document_id"]
        )
        quoted = conn.dialect.identifier_preparer.quote(name)
        await conn.exec_driver_sql(
            f"ALTER TABLE chunks ALTER CONSTRAINT {quoted} DEFERRABLE INITIALLY DEFERRED"
        )

    async def invalid(service, doc, **kwargs):
        service.db.add(
            Chunk(
                document_id=uuid4(), chunk_index=0, text="synthetic-commit-secret", metadata_json={}
            )
        )
        return "chunked"

    monkeypatch.setattr(ChunkingService, "_replace_chunks", invalid)
    jid = await enqueue(w, IndexingOperation.CHUNK)
    await w.worker.run_once()
    result = await job(w, jid)
    assert result.status == IndexingJobStatus.FAILED
    assert result.processed == result.succeeded == 0
    assert "synthetic-commit-secret" not in result.error
    async with w.factory() as db:
        assert await db.scalar(select(func.count()).select_from(Chunk)) == 0


async def test_owned_polling_loop_finishes_current_job_then_stops_claiming(world):
    w = world
    stop = asyncio.Event()
    for owner in [USER_A, USER_B]:
        await document(w, owner)
    a = await enqueue(w, IndexingOperation.BUILD, USER_A, w.files[USER_A])
    b = await enqueue(w, IndexingOperation.BUILD, USER_B, w.files[USER_B])
    async with w.factory() as db:
        await db.execute(
            update(IndexingJob)
            .where(IndexingJob.id == a)
            .values(created_at=datetime(2026, 1, 1, tzinfo=UTC))
        )
        await db.execute(
            update(IndexingJob)
            .where(IndexingJob.id == b)
            .values(created_at=datetime(2026, 1, 2, tzinfo=UTC))
        )
        await db.commit()

    class StopDuringEmbedding(Embeddings):
        async def embed_texts(self, texts):
            stop.set()
            return await super().embed_texts(texts)

    w.worker.embedding_service = StopDuringEmbedding()
    await asyncio.wait_for(w.worker.run(stop), timeout=10)
    assert (await job(w, a)).status == IndexingJobStatus.COMPLETED
    pending = await job(w, b)
    assert pending.status == IndexingJobStatus.QUEUED and pending.claim_id is None
