"""Real PostgreSQL/Qdrant write-ahead, crash and classifier boundaries."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text, update
from qdrant_client import AsyncQdrantClient

from app.db.enums import DriveFileStatus, IndexingJobStatus, IndexingOperation
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.db.models.indexing_job import IndexingJob
from app.services.indexing_attempt import AttemptEvidenceError, digest, read_attempt
from app.services.indexing_classifier import IndexingClassifier
from app.services.indexing_worker import IndexingClaimLost, IndexingWorker, StageProgress
from app.services.indexing_service import IndexingService
from app.embeddings.vector_store import VectorStoreError
from app.services.indexing_job_service import IndexingJobService, IndexingAdmissionConflict
from .conftest import USER_A, USER_B, apply_revision
from .test_indexing_worker import (
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


async def expire(w, jid):
    async with w.factory() as db:
        await db.execute(
            update(IndexingJob)
            .where(IndexingJob.id == jid)
            .values(lease_expires_at=func.clock_timestamp() - text("interval '1 second'"))
        )
        await db.commit()


async def test_healthy_selection_snapshots_and_verified_receipts_precede_publication(
    world, monkeypatch
):
    w = world
    await document(w)
    await document(w, USER_B)
    jid = await enqueue(w, IndexingOperation.BUILD)
    checked = []
    for name in ["create_collection", "create_payload_index", "upsert"]:
        native = getattr(AsyncQdrantClient, name)

        def wrapper(operation, original):
            async def issue(client, *args, **kwargs):
                row = await job(w, jid)  # Independent session proves durable write-ahead intent.
                attempt = read_attempt(row)
                assert [f.file_id for f in attempt.files] == [w.files[USER_A]]
                evidence = attempt.files[0]
                assert evidence.phase == "PREPARED" and not evidence.sql_published
                assert evidence.document_id is not None and evidence.content_hash
                mutation = evidence.mutations[-1]
                assert mutation.operation == operation and mutation.outcome == "UNKNOWN"
                assert mutation.collection == w.settings.qdrant_collection
                async with w.factory() as db:
                    chunks = list(
                        (
                            await db.scalars(
                                select(Chunk.id).where(Chunk.document_id == evidence.document_id)
                            )
                        ).all()
                    )
                    assert evidence.chunk_digest == digest(sorted(str(i) for i in chunks))
                    assert evidence.chunk_count == len(chunks)
                checked.append(operation)
                return await original(client, *args, **kwargs)

            return issue

        monkeypatch.setattr(AsyncQdrantClient, name, wrapper(name, native))
    await w.worker.run_once()
    row = await job(w, jid)
    attempt = read_attempt(row)
    assert row.status == IndexingJobStatus.COMPLETED and not row.recovery_required
    assert attempt.completed() and checked == [
        "create_collection",
        "create_payload_index",
        "create_payload_index",
        "upsert",
    ]
    assert all(
        m.outcome == "ACKNOWLEDGED" and m.acknowledged_at for m in attempt.files[0].mutations
    )
    assert "Synthetic searchable" not in str(row.attempt_manifest)


@pytest.mark.parametrize("targeted", [False, True])
async def test_complete_selection_is_committed_before_first_file(world, monkeypatch, targeted):
    w = world
    await document(w)
    await document(w, USER_B)
    jid = await enqueue(w, IndexingOperation.BUILD, file_id=w.files[USER_A] if targeted else None)
    native = w.worker._file

    async def file(db, claim, fid, progress):
        row = await job(w, jid)
        manifest = read_attempt(row)
        assert manifest.target_file_id == (w.files[USER_A] if targeted else None)
        assert [f.file_id for f in manifest.files] == [w.files[USER_A]]
        assert manifest.files[0].phase == "SELECTED" and not manifest.files[0].mutations
        await native(db, claim, fid, progress)

    monkeypatch.setattr(w.worker, "_file", file)
    await w.worker.run_once()
    assert (await job(w, jid)).status == IndexingJobStatus.COMPLETED


async def test_zero_eligible_files_has_complete_empty_manifest(world):
    w = world
    jid = await enqueue(w, IndexingOperation.BUILD)
    await w.worker.run_once()
    row = await job(w, jid)
    assert row.status == IndexingJobStatus.COMPLETED
    assert read_attempt(row).files == [] and read_attempt(row).completed()


@pytest.mark.parametrize("boundary", ["selection", "first_intent", "intent", "remote", "receipt"])
async def test_process_loss_classification_respects_durable_remote_boundary(
    world, monkeypatch, boundary
):
    w = world
    await document(w)
    jid = await enqueue(w, IndexingOperation.BUILD)
    reached = asyncio.Event()

    async def no_terminal(*args, **kwargs):
        # Fault injection models process loss before terminal SQL publication.
        raise asyncio.CancelledError

    monkeypatch.setattr(w.worker, "finalize", no_terminal)
    if boundary == "selection":

        async def before_file(*args):
            reached.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(w.worker, "_file", before_file)
    elif boundary in {"first_intent", "intent", "remote"}:
        method = "create_collection" if boundary == "first_intent" else "upsert"
        original = getattr(AsyncQdrantClient, method)

        async def held(client, *args, **kwargs):
            if boundary == "remote":
                await original(client, *args, **kwargs)
            reached.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(AsyncQdrantClient, method, held)
    else:
        original = IndexingService._index_document

        async def held_publication(service, doc, **kwargs):
            validate = kwargs["before_persist"]

            async def before_persist():
                await validate()
                reached.set()
                await asyncio.Event().wait()

            kwargs["before_persist"] = before_persist
            return await original(service, doc, **kwargs)

        monkeypatch.setattr(IndexingService, "_index_document", held_publication)
    task = asyncio.create_task(w.worker.run_once())
    await asyncio.wait_for(reached.wait(), 5)
    before = await job(w, jid)
    manifest = read_attempt(before)
    if boundary == "selection":
        assert not manifest.files[0].mutations
    elif boundary == "first_intent":
        assert len(manifest.files[0].mutations) == 1
        assert manifest.files[0].mutations[0].operation == "create_collection"
        assert manifest.files[0].mutations[0].outcome == "UNKNOWN"
        assert not await w.client.collection_exists(w.settings.qdrant_collection)
    elif boundary in {"intent", "remote"}:
        assert manifest.files[0].mutations[-1].operation == "upsert"
        assert manifest.files[0].mutations[-1].outcome == "UNKNOWN"
    else:
        assert all(m.outcome == "ACKNOWLEDGED" for m in manifest.files[0].mutations)
        assert not manifest.files[0].sql_published
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await expire(w, jid)
    result = await IndexingClassifier(w.worker).classify(jid)
    row = await job(w, jid)
    assert row.status == IndexingJobStatus.FAILED
    assert row.recovery_required == (boundary != "selection")
    assert result == ("FAILED" if boundary == "selection" else "RECOVERY_REQUIRED")
    assert row.attempt_manifest == before.attempt_manifest
    assert await IndexingClassifier(w.worker).classify(jid) == "UNCHANGED"
    async with w.factory() as db:
        assert (await db.get(DriveFile, w.files[USER_A])).status != DriveFileStatus.INDEXED
    if boundary != "selection":
        async with w.factory() as db:
            with pytest.raises(IndexingAdmissionConflict):
                await IndexingJobService(db).admit(
                    USER_A, IndexingOperation.CHUNK, authorize=lambda: None
                )
    assert await enqueue(w, IndexingOperation.CHUNK, USER_B)


@pytest.mark.parametrize(
    "operation", [IndexingOperation.SYNC, IndexingOperation.INGEST, IndexingOperation.CHUNK]
)
async def test_expired_sql_only_attempt_is_failed_and_old_claim_fenced(world, operation):
    w = world
    jid = await enqueue(w, operation)
    claim = await w.worker.claim_next()
    assert await IndexingClassifier(w.worker).classify(jid) == "LIVE"
    await expire(w, jid)
    outcomes = await asyncio.gather(
        IndexingClassifier(w.worker).classify(jid), IndexingClassifier(w.worker).classify(jid)
    )
    assert sorted(outcomes) == ["FAILED", "UNCHANGED"]
    with pytest.raises(IndexingClaimLost):
        await w.worker.renew_lease(claim)
    assert not await w.worker.finalize(claim, StageProgress())
    assert await enqueue(w, IndexingOperation.CHUNK)


@pytest.mark.parametrize("state", ["queued", "null_lease", "legacy"])
async def test_unclassified_states_are_preserved(world, state):
    w = world
    if state == "legacy":
        async with w.factory() as db:
            row = IndexingJob(user_id=USER_A, status=IndexingJobStatus.RUNNING)
            db.add(row)
            await db.commit()
            jid = row.id
    else:
        jid = await enqueue(w, IndexingOperation.CHUNK)
        if state == "null_lease":
            await w.worker.claim_next()
            async with w.factory() as db:
                await db.execute(
                    update(IndexingJob).where(IndexingJob.id == jid).values(lease_expires_at=None)
                )
                await db.commit()
    before = await job(w, jid)
    async with w.factory() as db:
        assert await db.scalar(
            select(IndexingJob.attempt_manifest.is_(None)).where(IndexingJob.id == jid)
        )
    result = await IndexingClassifier(w.worker).classify(jid)
    after = await job(w, jid)
    assert result == ("REVIEW_REQUIRED" if state == "null_lease" else "UNCHANGED")
    assert after.status == before.status and after.claim_id == before.claim_id


@pytest.mark.parametrize("value", [None, {}, {"version": 99}, [], {"version": True}])
async def test_unknown_manifest_never_releases_expired_build(world, value):
    w = world
    jid = await enqueue(w, IndexingOperation.BUILD)
    await w.worker.claim_next()
    async with w.factory() as db:
        await db.execute(
            update(IndexingJob).where(IndexingJob.id == jid).values(attempt_manifest=value)
        )
        await db.commit()
    await expire(w, jid)
    assert await IndexingClassifier(w.worker).classify(jid) == "RECOVERY_REQUIRED"
    assert (await job(w, jid)).recovery_required


async def test_classifier_checks_expiry_after_waiting_for_unchanged_row_lock(world):
    w = world
    jid = await enqueue(w, IndexingOperation.CHUNK)
    claim = await w.worker.claim_next()
    async with w.factory() as blocker:
        row = await blocker.scalar(
            select(IndexingJob).where(IndexingJob.id == jid).with_for_update()
        )
        # Classifier is already waiting on the unchanged job before expiry.
        row.lease_expires_at = await blocker.scalar(
            select(func.clock_timestamp() + text("interval '0.4 seconds'"))
        )
        await blocker.commit()
        await blocker.scalar(select(IndexingJob.id).where(IndexingJob.id == jid).with_for_update())
        task = asyncio.create_task(IndexingClassifier(w.worker).classify(jid))
        async with w.factory() as observer, asyncio.timeout(2):
            await observer.scalar(select(func.pg_stat_clear_snapshot()))
            while not await observer.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE wait_event_type='Lock' AND query LIKE '%indexing_jobs%' AND pid <> pg_backend_pid())"
                )
            ):
                await observer.scalar(select(func.pg_stat_clear_snapshot()))
            while await observer.scalar(select(func.clock_timestamp())) <= row.lease_expires_at:
                pass
        await blocker.rollback()
        assert await task == "FAILED"
    assert not await w.worker.finalize(claim, StageProgress())


async def test_migration_preserves_historical_rows_and_refuses_evidence_loss(owner_engine):
    async with owner_engine.begin() as conn:
        await conn.run_sync(apply_revision, "20261013_1200", downgrade=True)
        jid = uuid4()
        await conn.execute(
            text(
                "INSERT INTO indexing_jobs(id,user_id,status,total,processed,succeeded,failed,skipped) VALUES (:id,:owner,'COMPLETED',3,3,2,0,1)"
            ),
            {"id": jid, "owner": USER_A},
        )
        old = (
            await conn.execute(
                text("SELECT row_to_json(indexing_jobs) FROM indexing_jobs WHERE id=:id"),
                {"id": jid},
            )
        ).scalar_one()
        await conn.run_sync(apply_revision, "20261013_1200")
        new = (
            await conn.execute(
                text("SELECT row_to_json(indexing_jobs) FROM indexing_jobs WHERE id=:id"),
                {"id": jid},
            )
        ).scalar_one()
        assert new.pop("attempt_manifest") is None and new == old
        await conn.execute(
            text("UPDATE indexing_jobs SET attempt_manifest='{}'::jsonb WHERE id=:id"), {"id": jid}
        )
    with pytest.raises(RuntimeError, match="Retain BUILD"):
        async with owner_engine.begin() as conn:
            await conn.run_sync(apply_revision, "20261013_1200", downgrade=True)


@pytest.mark.parametrize("change", ["reconnect", "disconnect"])
async def test_ingestion_checks_actual_download_grant_before_publication(
    world, monkeypatch, change
):
    import threading
    from app.db.models.google_oauth_token import GoogleOAuthToken

    w = world
    entered, returned = asyncio.Event(), asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    native = w.google.get_file_content

    def blocked(client, *args):
        loop.call_soon_threadsafe(entered.set)
        release.wait()
        loop.call_soon_threadsafe(returned.set)
        return native(client, *args)

    monkeypatch.setattr(w.google, "get_file_content", blocked)
    jid = await enqueue(w, IndexingOperation.INGEST, file_id=w.files[USER_A])
    task = asyncio.create_task(w.worker.run_once())
    try:
        await asyncio.wait_for(entered.wait(), 5)
        async with w.factory() as db:
            await db.execute(
                update(GoogleOAuthToken)
                .where(GoogleOAuthToken.user_id == USER_A)
                .values(
                    grant_epoch=GoogleOAuthToken.grant_epoch + 1,
                    grant_status="ACTIVE" if change == "reconnect" else "REAUTH_REQUIRED",
                )
            )
            await db.commit()
        release.set()
        await asyncio.wait_for(task, 5)
    finally:
        release.set()
        await asyncio.wait_for(returned.wait(), 5)
        if not task.done():
            await asyncio.wait_for(task, 5)
    assert (await job(w, jid)).status == IndexingJobStatus.FAILED
    async with w.factory() as db:
        assert await db.scalar(select(func.count()).select_from(Document)) == 0


async def test_healthy_heartbeat_wins_classifier_row_lock_race(world, monkeypatch):
    w = world
    jid = await enqueue(w, IndexingOperation.CHUNK)
    claim = await w.worker.claim_next()
    entered, release = asyncio.Event(), asyncio.Event()
    original = w.worker._database_time

    async def held_clock(db):
        current = asyncio.current_task()
        if current is not None and current.get_name() == "held-heartbeat":
            entered.set()
            await release.wait()  # Heartbeat already owns the job row.
        return await original(db)

    monkeypatch.setattr(w.worker, "_database_time", held_clock)
    renewal = asyncio.create_task(w.worker.renew_lease(claim), name="held-heartbeat")
    await asyncio.wait_for(entered.wait(), 2)
    classifier = asyncio.create_task(IndexingClassifier(w.worker).classify(jid))
    async with w.factory() as observer, asyncio.timeout(2):
        while not await observer.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE wait_event_type='Lock' AND query LIKE '%indexing_jobs%' AND pid<>pg_backend_pid())"
            )
        ):
            await observer.scalar(select(func.pg_stat_clear_snapshot()))
    release.set()
    await renewal
    assert await classifier == "LIVE"
    assert (await job(w, jid)).status == IndexingJobStatus.RUNNING


async def test_classifier_failed_transaction_retains_exclusion(world):
    from sqlalchemy import event
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session

    w = world
    jid = await enqueue(w, IndexingOperation.CHUNK)
    await w.worker.claim_next()
    await expire(w, jid)

    def invalidate(db, context, objects):
        for row in db.dirty:
            if isinstance(row, IndexingJob):
                row.processed = -1  # Real PostgreSQL CHECK failure.

    event.listen(Session, "before_flush", invalidate)
    try:
        with pytest.raises(IntegrityError):
            await IndexingClassifier(w.worker).classify(jid)
    finally:
        event.remove(Session, "before_flush", invalidate)
    assert (await job(w, jid)).status == IndexingJobStatus.RUNNING
    async with w.factory() as db:
        with pytest.raises(IndexingAdmissionConflict):
            await IndexingJobService(db).admit(
                USER_A, IndexingOperation.CHUNK, authorize=lambda: None
            )
    assert await IndexingClassifier(w.worker).classify(jid) == "FAILED"


async def test_multi_file_attempt_retains_first_publication_and_later_unknown_write(
    world, monkeypatch
):
    from datetime import UTC, datetime

    w = world
    await document(w)
    async with w.factory() as db:
        extra = DriveFile(
            user_id=USER_A,
            drive_file_id="synthetic-extra",
            name="extra.txt",
            mime_type="text/plain",
            modified_at=datetime.now(UTC),
            status=DriveFileStatus.INDEXING,
        )
        db.add(extra)
        await db.flush()
        db.add(
            Document(
                drive_file_id=extra.id,
                extracted_text="Synthetic second document.",
                extracted_text_hash="second-hash",
            )
        )
        await db.commit()
    jid = await enqueue(w, IndexingOperation.BUILD)
    original = AsyncQdrantClient.upsert
    count = 0

    async def second_failure(client, *args, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise VectorStoreError("Synthetic unknown second-file outcome")
        return await original(client, *args, **kwargs)

    monkeypatch.setattr(AsyncQdrantClient, "upsert", second_failure)
    await w.worker.run_once()
    row = await job(w, jid)
    manifest = read_attempt(row)
    assert row.status == IndexingJobStatus.FAILED and row.recovery_required
    assert row.processed == 2 and row.succeeded == row.failed == 1
    assert len(manifest.files) == 2
    assert manifest.files[0].phase == "INDEXED" and manifest.files[0].sql_published
    assert (
        manifest.files[1].phase == "FAILED" and manifest.files[1].mutations[-1].outcome == "UNKNOWN"
    )
    assert all(
        m.sequence == i for i, m in enumerate([m for f in manifest.files for m in f.mutations])
    )


@pytest.mark.parametrize(
    "corrupt", ["version", "owner", "digest", "oversized", "prior_uncertainty"]
)
async def test_corrupt_or_prior_uncertain_manifest_is_not_safe_to_release(
    world, monkeypatch, corrupt
):
    w = world
    await document(w)
    jid = await enqueue(w, IndexingOperation.BUILD)

    async def stop_file(*args):
        raise RuntimeError("Stop before preparation")

    monkeypatch.setattr(w.worker, "_file", stop_file)
    await w.worker.run_once()
    row = await job(w, jid)
    raw = row.attempt_manifest
    if corrupt == "version":
        raw["version"] = True
    elif corrupt == "owner":
        raw["user_id"] = str(USER_B)
    elif corrupt == "digest":
        raw["files"][0]["chunk_digest"] = "malformed"
    elif corrupt == "oversized":
        raw["collection"] = "x" * (2 * 1024 * 1024)
        row.attempt_manifest = raw
        with pytest.raises(AttemptEvidenceError):
            read_attempt(row)
        return
    else:
        raw["prior_recovery_required"] = True
    async with w.factory() as db:
        await db.execute(
            update(IndexingJob)
            .where(IndexingJob.id == jid)
            .values(status=IndexingJobStatus.RUNNING, attempt_manifest=raw)
        )
        await db.commit()
    await expire(w, jid)
    assert await IndexingClassifier(w.worker).classify(jid) == "RECOVERY_REQUIRED"


async def test_changed_sql_snapshot_cannot_receive_successful_terminal_publication(
    world, monkeypatch
):
    w = world
    did = await document(w)
    jid = await enqueue(w, IndexingOperation.BUILD)
    original = w.worker.finalize

    async def changed(claim, progress, **kwargs):
        async with w.factory() as db:
            await db.execute(
                update(Document)
                .where(Document.id == did)
                .values(extracted_text_hash="changed-after-file-publication")
            )
            await db.commit()
        return await original(claim, progress, **kwargs)

    monkeypatch.setattr(w.worker, "finalize", changed)
    await w.worker.run_once()
    row = await job(w, jid)
    assert row.status == IndexingJobStatus.FAILED and row.recovery_required


async def test_changed_document_after_selection_is_not_silently_recaptured(world, monkeypatch):
    w = world
    did = await document(w)
    jid = await enqueue(w, IndexingOperation.BUILD)
    original = w.worker._file

    async def changed(db, claim, fid, progress):
        captured = read_attempt(await job(w, jid)).file(fid)
        assert captured.document_id == did and captured.content_hash == "hash-" + str(USER_A)
        async with w.factory() as other:
            await other.execute(
                update(Document).where(Document.id == did).values(extracted_text_hash="newer-hash")
            )
            await other.commit()
        return await original(db, claim, fid, progress)

    monkeypatch.setattr(w.worker, "_file", changed)
    await w.worker.run_once()
    row = await job(w, jid)
    assert row.status == IndexingJobStatus.FAILED
    assert read_attempt(row).files[0].content_hash == "hash-" + str(USER_A)
    assert not read_attempt(row).files[0].mutations
    assert not await w.client.collection_exists(w.settings.qdrant_collection)


async def test_mutation_capacity_failure_preserves_previous_intent_without_new_write(
    world, monkeypatch
):
    import app.services.indexing_worker as module

    w = world
    await document(w)
    monkeypatch.setattr(module, "MAX_MUTATIONS", 1)
    jid = await enqueue(w, IndexingOperation.BUILD)
    await w.worker.run_once()
    row = await job(w, jid)
    evidence = read_attempt(row).files[0]
    assert row.status == IndexingJobStatus.FAILED and row.recovery_required
    assert len(evidence.mutations) == 1
    assert evidence.mutations[0].operation == "create_collection"
    assert evidence.mutations[0].outcome == "ACKNOWLEDGED"
    assert (await w.client.count(w.settings.qdrant_collection, exact=True)).count == 0


async def test_database_manifest_bound_rejects_without_destroying_prior_evidence(world):
    from sqlalchemy.exc import IntegrityError

    w = world
    await document(w)
    jid = await enqueue(w, IndexingOperation.BUILD)
    await w.worker.run_once()
    prior = (await job(w, jid)).attempt_manifest
    async with w.factory() as db:
        with pytest.raises(IntegrityError):
            await db.execute(
                update(IndexingJob)
                .where(IndexingJob.id == jid)
                .values(attempt_manifest={"oversized": "x" * (2 * 1024 * 1024)})
            )
        await db.rollback()
    assert (await job(w, jid)).attempt_manifest == prior


async def test_expired_terminal_authorization_rolls_back_dirty_recovery_flag(world, monkeypatch):
    w = world
    worker = IndexingWorker(w.factory, w.settings, lease_seconds=0.5, heartbeat_seconds=0.1)
    jid = await enqueue(w, IndexingOperation.BUILD)
    claim = await worker.claim_next()
    assert claim is not None
    deadline = (await job(w, jid)).lease_expires_at
    original = worker._guard
    calls = 0

    async def delayed(db, attempt):
        nonlocal calls
        calls += 1
        if calls == 2:
            # The absent manifest has made recovery_required dirty in memory.
            # Let actual DATABASE time expire while terminal publication waits.
            async with w.factory() as observer, asyncio.timeout(2):
                while await observer.scalar(select(func.clock_timestamp())) <= deadline:
                    pass
        return await original(db, attempt)

    monkeypatch.setattr(worker, "_guard", delayed)
    assert not await worker.finalize(claim, StageProgress())
    row = await job(w, jid)
    assert row.status == IndexingJobStatus.RUNNING and not row.recovery_required
    assert row.attempt_manifest is None


async def test_queued_row_with_preexisting_unknown_evidence_is_quarantined(world):
    w = world
    jid = await enqueue(w, IndexingOperation.BUILD)
    prior = {"version": 99, "unknown_prior_attempt": True}
    async with w.factory() as db:
        await db.execute(
            update(IndexingJob).where(IndexingJob.id == jid).values(attempt_manifest=prior)
        )
        await db.commit()
    await w.worker.run_once()
    row = await job(w, jid)
    assert row.status == IndexingJobStatus.FAILED and row.recovery_required
    assert row.attempt_manifest == prior
    assert not await w.client.collection_exists(w.settings.qdrant_collection)
    async with w.factory() as db:
        with pytest.raises(IndexingAdmissionConflict):
            await IndexingJobService(db).admit(
                USER_A, IndexingOperation.CHUNK, authorize=lambda: None
            )
