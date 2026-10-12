"""Database-time ownership and real-store mutation fences, with controlled ordering."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select, text, update

from app.db.enums import DriveFileStatus, IndexingJobStatus, IndexingOperation
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.db.models.indexing_job import IndexingJob
from app.services.indexing_worker import IndexingClaimLost, IndexingWorker, StageProgress
from .conftest import USER_A, USER_B
from .test_indexing_worker import (
    Embeddings,
    document,
    enqueue,
    final_engine,
    job,
    keys,
    owner_engine,
    qdrant_client,
    world,
)

__all__ = ["world", "final_engine", "keys", "owner_engine", "qdrant_client"]


async def claimed(w, operation=IndexingOperation.CHUNK):
    jid = await enqueue(w, operation)
    claim = await w.worker.claim_next()
    assert claim is not None and claim.job_id == jid
    return claim


async def expire(w, claim):
    async with w.factory() as db:
        await db.execute(
            update(IndexingJob)
            .where(IndexingJob.id == claim.job_id)
            .values(lease_expires_at=func.clock_timestamp() - text("interval '1 second'"))
        )
        await db.commit()


async def clock(w):
    async with w.factory() as db:
        return await db.scalar(select(func.clock_timestamp()))


async def test_claim_initializes_database_time_and_validated_settings(world):
    w = world
    before = await clock(w)
    claim = await claimed(w)
    after = await clock(w)
    row = await job(w, claim.job_id)
    assert before <= row.heartbeat_at <= after
    assert row.started_at == row.heartbeat_at
    assert row.lease_expires_at == row.heartbeat_at + timedelta(seconds=60)
    for options in [
        dict(lease_seconds=0),
        dict(heartbeat_seconds=60),
        dict(lock_timeout_seconds=0),
        dict(lease_seconds=float("nan")),
    ]:
        with pytest.raises(ValueError):
            IndexingWorker(w.factory, w.settings, **options)


@pytest.mark.parametrize("operation", ["guard", "heartbeat", "finalize"])
async def test_expiry_during_unchanged_row_lock_wait_is_rejected(world, operation):
    w = world
    claim = await claimed(w)
    async with w.factory() as db:
        deadline = await db.scalar(select(func.clock_timestamp() + text("interval '0.6 seconds'")))
        await db.execute(
            update(IndexingJob)
            .where(IndexingJob.id == claim.job_id)
            .values(lease_expires_at=deadline)
        )
        await db.commit()
    async with w.factory() as blocker:
        await blocker.scalar(
            select(IndexingJob.id).where(IndexingJob.id == claim.job_id).with_for_update()
        )
        pid_ready = asyncio.Event()
        pid = None

        async def attempt():
            nonlocal pid
            if operation == "guard":
                async with w.factory() as db:
                    pid = await db.scalar(select(func.pg_backend_pid()))
                    pid_ready.set()
                    await w.worker._guard(db, claim)
            else:
                # Observe the real session used by renewal/finalization, not a stubbed guard.
                original = w.worker._transaction_limits

                async def limits(db):
                    nonlocal pid
                    pid = await db.scalar(select(func.pg_backend_pid()))
                    pid_ready.set()
                    await original(db)

                w.worker._transaction_limits = limits
                if operation == "heartbeat":
                    await w.worker.renew_lease(claim)
                else:
                    return await w.worker.finalize(claim, StageProgress(processed=1))

        task = asyncio.create_task(attempt())
        await asyncio.wait_for(pid_ready.wait(), 2)
        async with asyncio.timeout(2):
            async with w.factory() as observer:
                while not await observer.scalar(
                    text("SELECT wait_event_type = 'Lock' FROM pg_stat_activity WHERE pid=:pid"),
                    {"pid": pid},
                ):
                    pass
                # Only database clock passage is used, after confirming actual lock contention.
                while await observer.scalar(select(func.clock_timestamp())) <= deadline:
                    pass
        assert not task.done()
        await blocker.rollback()  # Unchanged row: exposes the pre-lock WHERE pitfall.
        if operation == "finalize":
            assert await task is False
        else:
            with pytest.raises(IndexingClaimLost):
                await task
    row = await job(w, claim.job_id)
    assert row.status == IndexingJobStatus.RUNNING and row.processed == 0
    assert row.lease_expires_at == deadline  # Renewal did not resurrect it.


@pytest.mark.parametrize("loss", ["expired", "replaced"])
async def test_dirty_stage_cannot_autoflush_or_publish_after_authority_loss(world, loss):
    w = world
    did = await document(w)
    claim = await claimed(w)
    async with w.factory() as stage:
        doc = await stage.get(Document, did)
        mutable_job = await stage.get(IndexingJob, claim.job_id)
        doc.extracted_text = "UNAUTHORIZED DIRTY PUBLICATION"
        mutable_job.processed = 7
        stage.add(Chunk(document_id=did, chunk_index=91, text="pending", metadata_json={}))
        async with w.factory() as revoker:
            values = (
                dict(lease_expires_at=func.clock_timestamp() - text("interval '1 second'"))
                if loss == "expired"
                else dict(claim_id=uuid4())
            )
            await revoker.execute(
                update(IndexingJob).where(IndexingJob.id == claim.job_id).values(**values)
            )
            await revoker.commit()
        writes = []

        def observe(conn, cursor, statement, params, context, many):
            if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
                writes.append(statement)

        event.listen(w.engine.sync_engine, "before_cursor_execute", observe)
        try:
            with pytest.raises(IndexingClaimLost):
                await w.worker._commit(stage, claim)
        finally:
            event.remove(w.engine.sync_engine, "before_cursor_execute", observe)
        assert writes == []
    async with w.factory() as db:
        assert (await db.get(Document, did)).extracted_text != "UNAUTHORIZED DIRTY PUBLICATION"
        assert await db.scalar(select(func.count()).select_from(Chunk)) == 0
        assert (await db.get(IndexingJob, claim.job_id)).processed == 0


async def test_replaced_claim_rejects_heartbeat_progress_and_terminal(world):
    w = world
    claim = await claimed(w)
    newer = uuid4()
    async with w.factory() as db:
        await db.execute(
            update(IndexingJob).where(IndexingJob.id == claim.job_id).values(claim_id=newer)
        )
        await db.commit()
    with pytest.raises(IndexingClaimLost):
        await w.worker.renew_lease(claim)
    async with w.factory() as db:
        with pytest.raises(IndexingClaimLost):
            await w.worker._commit(db, claim)
    assert not await w.worker.finalize(claim, StageProgress(processed=9))
    row = await job(w, claim.job_id)
    assert row.claim_id == newer and row.processed == 0 and row.status == IndexingJobStatus.RUNNING


async def test_guard_preserves_dirty_progress_and_recovery(world):
    w = world
    claim = await claimed(w)
    async with w.factory() as db:
        row = await w.worker._guard(db, claim)
        row.processed = 1
        row.recovery_required = True
        await w.worker._commit(db, claim)
    persisted = await job(w, claim.job_id)
    assert persisted.processed == 1 and persisted.recovery_required


async def test_heartbeat_failure_cancels_blocked_embedding_and_never_starts_write(world):
    w = world
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    class Blocking(Embeddings):
        async def embed_texts(self, texts):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
            raise AssertionError("Blocked embedding unexpectedly resumed")

    worker = IndexingWorker(
        w.factory, w.settings, embedding_service=Blocking(), heartbeat_seconds=0.02
    )
    original = worker.renew_lease
    count = 0

    async def renew(claim):
        nonlocal count
        count += 1
        if count > 1:
            await entered.wait()
            raise RuntimeError("synthetic-secret-must-not-be-persisted")
        await original(claim)

    worker.renew_lease = renew
    await document(w)
    jid = await enqueue(w, IndexingOperation.BUILD)
    await asyncio.wait_for(worker.run_once(), 5)
    assert cancelled.is_set()
    row = await job(w, jid)
    assert row.status == IndexingJobStatus.FAILED and row.recovery_required
    assert row.error == "Indexing heartbeat failed."
    assert (await w.client.count(w.settings.qdrant_collection, exact=True)).count == 0
    assert not any(
        t.get_name() in {"indexing-heartbeat", "indexing-stage"} for t in asyncio.all_tasks()
    )


async def test_healthy_heartbeat_outlives_original_lease_then_joins(world):
    w = world
    entered, release, renewed = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class Blocking(Embeddings):
        async def embed_texts(self, texts):
            entered.set()
            await release.wait()
            return await super().embed_texts(texts)

    worker = IndexingWorker(
        w.factory,
        w.settings,
        embedding_service=Blocking(),
        lease_seconds=0.8,
        heartbeat_seconds=0.1,
    )
    original = worker.renew_lease
    deadline = None

    async def renew(claim):
        nonlocal deadline
        await original(claim)
        row = await job(w, claim.job_id)
        if deadline is None:
            deadline = row.lease_expires_at
        elif await clock(w) > deadline:
            renewed.set()

    worker.renew_lease = renew
    await document(w)
    jid = await enqueue(w, IndexingOperation.BUILD)
    task = asyncio.create_task(worker.run_once())
    await asyncio.wait_for(entered.wait(), 5)
    await asyncio.wait_for(renewed.wait(), 5)
    assert (await job(w, jid)).lease_expires_at > await clock(w)
    release.set()
    await asyncio.wait_for(task, 5)
    assert (await job(w, jid)).status == IndexingJobStatus.COMPLETED
    assert not any(
        t.get_name() in {"indexing-heartbeat", "indexing-stage"} for t in asyncio.all_tasks()
    )


async def test_independent_owner_runs_while_a_renewal_waits_on_job_lock(world):
    w = world
    a = await claimed(w)
    b = await enqueue(w, IndexingOperation.CHUNK, USER_B)
    other = IndexingWorker(w.factory, w.settings, embedding_service=Embeddings())
    async with w.factory() as blocker:
        await blocker.scalar(
            select(IndexingJob.id).where(IndexingJob.id == a.job_id).with_for_update()
        )
        renewal = asyncio.create_task(w.worker.renew_lease(a))
        await asyncio.wait_for(other.run_once(), 2)
        assert (await job(w, b)).status == IndexingJobStatus.COMPLETED
        await blocker.rollback()
        await renewal


@pytest.mark.parametrize("during_request", [False, True])
async def test_real_vector_write_claim_loss_blocks_following_batch_and_preserves_uncertainty(
    world, monkeypatch, during_request
):
    w = world
    w.settings.qdrant_upsert_batch_size = 1
    await document(w, text="Synthetic content for multiple chunks. " * 500)
    jid = await enqueue(w, IndexingOperation.BUILD)
    from qdrant_client import AsyncQdrantClient

    original = AsyncQdrantClient.upsert
    issued = []
    response_pending = asyncio.Event()

    async def upsert(client, *args, **kwargs):
        result = await original(client, *args, **kwargs)  # REAL acknowledged Qdrant mutation.
        issued.append(kwargs["points"][0].id)
        if len(issued) == 1:
            async with w.factory() as db:
                await db.execute(
                    update(IndexingJob).where(IndexingJob.id == jid).values(claim_id=uuid4())
                )
                await db.commit()
            response_pending.set()
            if during_request:
                await asyncio.Event().wait()  # Response lost, not the remote side effect.
        return result

    monkeypatch.setattr(AsyncQdrantClient, "upsert", upsert)
    worker = IndexingWorker(
        w.factory, w.settings, embedding_service=Embeddings(), heartbeat_seconds=0.03
    )
    await asyncio.wait_for(worker.run_once(), 5)
    assert response_pending.is_set() and len(issued) == 1
    assert (await w.client.count(w.settings.qdrant_collection, exact=True)).count == 1
    row = await job(w, jid)
    assert row.status == IndexingJobStatus.RUNNING and row.recovery_required
    async with w.factory() as db:
        assert (await db.get(DriveFile, w.files[USER_A])).status != DriveFileStatus.INDEXED


@pytest.mark.parametrize("method", ["delete", "set_payload", "upsert"])
async def test_each_vector_mutation_checks_hook_after_reads_before_issue(
    world, monkeypatch, method
):
    # A direct store regression guards all native mutation types. Real server
    # reads/setup; a revoked hook must prevent the actual SDK write entirely.
    from app.embeddings.vector_store import QdrantVectorStore, VectorPoint
    from .test_worker_vector_reconciliation import prepare, payload
    from qdrant_client.models import PointStruct

    w = world
    chunk = (await prepare(w, USER_A))[0]
    store = QdrantVectorStore(w.settings, client=w.client, verify_writes=True)
    await store.ensure_collection(vector_size=3)
    await w.client.upsert(
        w.settings.qdrant_collection,
        points=[
            PointStruct(id=str(chunk.id), vector=[1.0, 0.0, 0.0], payload=payload(w, USER_A, chunk))
        ],
        wait=True,
    )
    before = (
        await w.client.retrieve(
            w.settings.qdrant_collection, ids=[str(chunk.id)], with_vectors=True
        )
    )[0].model_dump()

    async def denied():
        raise IndexingClaimLost()

    store.before_mutation = denied
    with pytest.raises(IndexingClaimLost):
        if method == "delete":
            await store.delete_points([chunk.id])
        elif method == "set_payload":
            await store.update_unchanged_point_owners(
                {chunk.id: chunk.metadata_json["extracted_text_hash"]},
                user_id=USER_A,
                drive_file_id=w.files[USER_A],
            )
        else:
            await store.upsert_points(
                [VectorPoint(chunk.id, [0.0, 1.0, 0.0], payload(w, USER_A, chunk))], user_id=USER_A
            )
    after = (
        await w.client.retrieve(
            w.settings.qdrant_collection, ids=[str(chunk.id)], with_vectors=True
        )
    )[0].model_dump()
    assert after == before


async def test_poison_blocks_stage_that_swallows_cancellation(world):
    w = world
    entered = asyncio.Event()
    swallowed = asyncio.Event()

    class UncooperativeEmbedding(Embeddings):
        async def embed_texts(self, texts):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                swallowed.set()
                return await super().embed_texts(texts)
            raise AssertionError("Blocked embedding unexpectedly resumed")

    worker = IndexingWorker(
        w.factory, w.settings, embedding_service=UncooperativeEmbedding(), heartbeat_seconds=0.02
    )

    async def unexpected_exit(claim, stop):
        await entered.wait()
        # Unexpected normal return is fatal too, not just exceptions.

    worker._heartbeat = unexpected_exit
    await document(w)
    jid = await enqueue(w, IndexingOperation.BUILD)
    await asyncio.wait_for(worker.run_once(), 5)
    assert swallowed.is_set()
    row = await job(w, jid)
    assert row.status == IndexingJobStatus.FAILED and row.recovery_required
    assert row.error == "Indexing heartbeat failed."
    assert (await w.client.count(w.settings.qdrant_collection, exact=True)).count == 0


async def test_heartbeat_updates_only_lease_and_preserves_counters_and_uncertainty(world):
    w = world
    claim = await claimed(w, IndexingOperation.BUILD)
    async with w.factory() as db:
        await db.execute(
            update(IndexingJob)
            .where(IndexingJob.id == claim.job_id)
            .values(processed=3, succeeded=2, failed=1, recovery_required=True)
        )
        await db.commit()
    old = await job(w, claim.job_id)
    await w.worker.renew_lease(claim)
    new = await job(w, claim.job_id)
    assert (new.processed, new.succeeded, new.failed, new.recovery_required) == (3, 2, 1, True)
    assert new.heartbeat_at > old.heartbeat_at
    assert new.lease_expires_at > old.lease_expires_at


async def test_lock_waits_are_bounded_without_touching_other_owner(world):
    w = world
    claim = await claimed(w)
    w.worker.lock_timeout_seconds = 0.05
    async with w.factory() as blocker:
        await blocker.scalar(
            select(IndexingJob.id).where(IndexingJob.id == claim.job_id).with_for_update()
        )
        from sqlalchemy.exc import DBAPIError

        with pytest.raises(DBAPIError):
            await asyncio.wait_for(w.worker.renew_lease(claim), 1)
        await blocker.rollback()
    row = await job(w, claim.job_id)
    assert row.status == IndexingJobStatus.RUNNING


@pytest.mark.parametrize(
    "field,value",
    [("worker_id", uuid4()), ("user_id", USER_B), ("full_sync", True), ("file_id", uuid4())],
)
async def test_claim_options_cannot_be_substituted(world, field, value):
    w = world
    claim = await claimed(w)
    altered = replace(claim, **{field: value})
    with pytest.raises(IndexingClaimLost):
        await w.worker.renew_lease(altered)
    assert not await w.worker.finalize(altered, StageProgress())
    assert (await job(w, claim.job_id)).status == IndexingJobStatus.RUNNING


async def test_repeated_caller_cancellation_joins_stage_cleanup_and_heartbeat(world):
    w = world
    entered, cleanup, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    recancelled = []

    class CleaningEmbedding(Embeddings):
        async def embed_texts(self, texts):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleanup.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    recancelled.append(True)
                    raise
            raise AssertionError("Blocked embedding unexpectedly resumed")

    worker = IndexingWorker(
        w.factory, w.settings, embedding_service=CleaningEmbedding(), heartbeat_seconds=0.03
    )
    await document(w)
    jid = await enqueue(w, IndexingOperation.BUILD)
    task = asyncio.create_task(worker.run_once())
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    await asyncio.wait_for(cleanup.wait(), 5)
    task.cancel()
    # The owned join swallows this cancellation, not the stage's interrupted outcome.
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert recancelled == []
    row = await job(w, jid)
    assert row.status == IndexingJobStatus.FAILED and row.recovery_required
    assert row.error == "Indexing execution interrupted."
    assert not any(
        t.get_name() in {"indexing-heartbeat", "indexing-stage"} for t in asyncio.all_tasks()
    )


async def test_stalled_heartbeat_transport_has_bounded_supervised_failure(world):
    w = world
    entered = asyncio.Event()
    renewal_cancelled = asyncio.Event()

    class Blocking(Embeddings):
        async def embed_texts(self, texts):
            entered.set()
            await asyncio.Event().wait()
            raise AssertionError("Blocked embedding unexpectedly resumed")

    worker = IndexingWorker(
        w.factory,
        w.settings,
        embedding_service=Blocking(),
        lease_seconds=1.2,
        heartbeat_seconds=0.05,
    )
    original = worker.renew_lease
    count = 0

    async def stall(claim):
        nonlocal count
        count += 1
        if count == 1:
            await original(claim)
        else:
            await entered.wait()
            try:
                await asyncio.Event().wait()
            finally:
                renewal_cancelled.set()

    worker.renew_lease = stall
    await document(w)
    jid = await enqueue(w, IndexingOperation.BUILD)
    await asyncio.wait_for(worker.run_once(), 5)
    assert renewal_cancelled.is_set()
    row = await job(w, jid)
    assert row.status == IndexingJobStatus.FAILED and row.recovery_required
    assert row.error == "Indexing heartbeat failed."
    assert (await w.client.count(w.settings.qdrant_collection, exact=True)).count == 0
