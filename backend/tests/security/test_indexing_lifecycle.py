"""Real FastAPI lifespan, PostgreSQL ownership, Qdrant and shutdown ordering."""

import asyncio
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.enums import IndexingJobStatus, IndexingOperation
from app.db.models.indexing_job import IndexingJob
from app.main import create_app
from app.security.principal import VerifiedGoogleIdentity
from app.security.session_helpers import session_cookie_policy
from app.services.application_session_service import ApplicationSessionService
from app.services.google_credential_service import GoogleRefreshLifecycle
from app.services.indexing_classifier import IndexingClassifier
from app.services.indexing_lifecycle import DisposableIndexingRuntime, IndexingSupervisor
from app.services.indexing_worker import IndexingWorker, StageProgress
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

__all__ = ["final_engine", "keys", "owner_engine", "qdrant_client", "world"]


async def runtime(w, **options):
    async with w.engine.connect() as conn:
        schema = await conn.scalar(text("SELECT current_schema()"))
    engine = create_async_engine(
        w.engine.url,
        hide_parameters=True,
        connect_args={"server_settings": {"search_path": schema}},
    )
    refresh = GoogleRefreshLifecycle(shutdown_grace=0.05, callback_timeout=0.1)
    sessions = async_sessionmaker(
        engine, expire_on_commit=False, info={"google_refresh_lifecycle": refresh}
    )
    worker = IndexingWorker(
        sessions,
        w.settings,
        embedding_service=Embeddings(),
        lease_seconds=2,
        heartbeat_seconds=0.05,
    )
    return DisposableIndexingRuntime(
        worker,
        refresh,
        poll_seconds=0.03,
        classifier_seconds=0.03,
        database_timeout=0.5,
        startup_timeout=2,
        drain_seconds=0.7,
        cleanup_seconds=0.1,
        **options,
    )


async def headers(w, owner=USER_A):
    async with w.factory() as db:
        sessions = ApplicationSessionService(db, w.settings)
        value = await sessions.issue_google(
            VerifiedGoogleIdentity(
                "verified-subject-a" if owner == USER_A else "verified-subject-b"
            )
        )
        credential = value.credential.get_secret_value()
        csrf = await sessions.csrf_token(credential)
        await db.commit()
    return {
        "Cookie": session_cookie_policy(w.settings).name + "=" + credential,
        "Origin": w.settings.frontend_url,
        "X-CSRF-Token": csrf.get_secret_value(),
    }


async def request(app, w, stage="chunk"):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=w.settings.frontend_url
    ) as client:
        return await client.post("/api/v1/index/" + stage, headers=await headers(w))


async def settled(task):
    return await asyncio.wait_for(asyncio.shield(task), 5)


@pytest.mark.parametrize("stage", ["sync", "ingest", "chunk", "build"])
async def test_real_lifespan_accepts_and_executes_owner_bound_job(world, monkeypatch, stage):
    w = world
    if stage in {"chunk", "build"}:
        await document(w)
        await document(w, USER_B)
    r = await runtime(w)
    app = create_app(indexing_test_runtime=r)
    completed = asyncio.Event()
    native = r.worker.finalize

    async def final(*args, **kw):
        result = await native(*args, **kw)
        completed.set()
        return result

    monkeypatch.setattr(r.worker, "finalize", final)
    async with app.router.lifespan_context(app):
        sup = app.state.indexing_supervisor
        assert sup.healthy and app.state.indexing_admission_ready
        response = await request(app, w, stage)
        assert response.status_code == 202
        jid = response.json()["job_id"]
        from uuid import UUID

        row = await job(w, UUID(jid))  # Independent session proves durable acceptance.
        assert row.user_id == USER_A and row.operation.name == stage.upper()
        await asyncio.wait_for(completed.wait(), 5)
        assert (await job(w, UUID(jid))).status == IndexingJobStatus.COMPLETED
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url=w.settings.frontend_url
        ) as c:
            own = await c.get(
                "/api/v1/index/status", params={"job_id": jid}, headers=await headers(w)
            )
            foreign = await c.get(
                "/api/v1/index/status", params={"job_id": jid}, headers=await headers(w, USER_B)
            )
            assert own.status_code == 200 and foreign.status_code == 404
            diagnostic = await c.get("/api/v1/health/indexing")
            assert diagnostic.json() == {"status": "ready", "admission": "available"}
    assert sup.health == "STOPPED" and not app.state.indexing_admission_ready
    assert all(task.done() for task in sup.tasks.values())
    assert app.state.indexing_disposal_task.done()


async def test_default_normal_lifespan_remains_inactive_with_queued_work(world, monkeypatch):
    import app.main as main

    w = world
    jid = await enqueue(w, IndexingOperation.CHUNK)
    refresh = GoogleRefreshLifecycle()
    monkeypatch.setattr(main, "SessionLocal", w.factory)
    monkeypatch.setattr(main, "engine", w.engine)
    monkeypatch.setattr(main, "get_settings", lambda: w.settings)
    app = create_app()
    app.state.google_refresh_lifecycle = refresh
    from app.db.session import get_db

    async def db():
        async with w.factory() as session:
            yield session

    app.dependency_overrides[get_db] = db
    from app.core.config import get_settings

    app.dependency_overrides[get_settings] = lambda: w.settings
    # An obsolete boolean alone cannot open the new health-bound gate.
    async with app.router.lifespan_context(app):
        app.state.indexing_admission_ready = True
        assert (await request(app, w)).status_code == 503
        assert app.state.indexing_supervisor is None
        assert (await job(w, jid)).status == IndexingJobStatus.QUEUED


async def test_handshake_must_poll_before_admission(world, monkeypatch):
    w = world
    r = await runtime(w)
    app = create_app(indexing_test_runtime=r)
    reached, release = asyncio.Event(), asyncio.Event()
    native = IndexingSupervisor._probe

    async def held(self, **kw):
        current = asyncio.current_task()
        if current is not None and current.get_name() == "indexing-polling":
            reached.set()
            await release.wait()
        return await native(self, **kw)

    monkeypatch.setattr(IndexingSupervisor, "_probe", held)
    context = app.router.lifespan_context(app)
    startup = asyncio.create_task(context.__aenter__())
    try:
        await asyncio.wait_for(reached.wait(), 5)
        assert (await request(app, w)).status_code == 503
        assert not app.state.indexing_admission_ready
        release.set()
        await settled(startup)
        assert app.state.indexing_supervisor.healthy
        with pytest.raises(RuntimeError, match="twice"):
            await app.state.indexing_supervisor.start()
        assert len(app.state.indexing_supervisor.tasks) == 2
    finally:
        release.set()
        await settled(startup)
        await context.__aexit__(None, None, None)


@pytest.mark.parametrize("fault", ["worker", "classifier", "return", "cancel"])
async def test_task_death_closes_actual_api_admission(world, monkeypatch, fault, caplog):
    w = world
    r = await runtime(w)
    app = create_app(indexing_test_runtime=r)
    entered, trigger = asyncio.Event(), asyncio.Event()
    if fault == "worker":

        async def broken():
            entered.set()
            await trigger.wait()
            raise RuntimeError("synthetic-secret-provider-body")

        monkeypatch.setattr(r.worker, "claim_next", broken)
    elif fault == "classifier":
        original = IndexingSupervisor._classification_round
        count = 0

        async def broken_classifier(self):
            nonlocal count
            count += 1
            if count > 1:
                entered.set()
                await trigger.wait()
                raise RuntimeError("synthetic-secret-provider-body")
            await original(self)

        monkeypatch.setattr(IndexingSupervisor, "_classification_round", broken_classifier)
    elif fault == "return":

        async def returns(self):
            self._worker_ready.set()
            await self._go.wait()
            entered.set()
            await trigger.wait()

        monkeypatch.setattr(IndexingSupervisor, "_poll", returns)
    async with app.router.lifespan_context(app):
        sup = app.state.indexing_supervisor
        assert sup.healthy
        if fault == "cancel":
            sup.tasks["worker"].cancel()
        else:
            await asyncio.wait_for(entered.wait(), 5)
            trigger.set()
        task = sup.tasks["classifier" if fault == "classifier" else "worker"]
        await asyncio.wait([task], timeout=2)
        assert task.done()
        assert not sup.healthy
        assert (await request(app, w)).status_code == 503
        assert "synthetic-secret-provider-body" not in caplog.text
        async with w.factory() as db:
            assert await db.scalar(select(func.count()).select_from(IndexingJob)) == 0


@pytest.mark.parametrize("contract", ["column", "exclusion", "evidence_bound"])
async def test_missing_schema_fails_startup_and_cleans_resources(world, contract):
    w = world
    r = await runtime(w)
    app = create_app(indexing_test_runtime=r)
    async with w.engine.begin() as conn:
        command = {
            "column": "ALTER TABLE indexing_jobs DROP COLUMN attempt_manifest",
            "exclusion": "DROP INDEX uq_indexing_jobs_unresolved_owner",
            "evidence_bound": "ALTER TABLE indexing_jobs DROP CONSTRAINT ck_indexing_jobs_manifest_size",
        }[contract]
        await conn.execute(text(command))
    with pytest.raises(Exception):
        async with app.router.lifespan_context(app):
            pytest.fail("Missing accepted schema cannot start")
    assert not app.state.indexing_admission_ready
    assert app.state.indexing_supervisor.health == "STOPPED"
    assert app.state.indexing_disposal_task.done()


async def test_database_loss_is_not_lease_expiry_or_healthy_admission(world, monkeypatch):
    w = world
    r = await runtime(w)
    app = create_app(indexing_test_runtime=r)
    jid = await enqueue(w, IndexingOperation.BUILD)
    # Keep a committed queued row outside the polling selection for this fault.
    async with w.factory() as db:
        await db.execute(update(IndexingJob).where(IndexingJob.id == jid).values(claim_id=uuid4()))
        await db.commit()
    async with app.router.lifespan_context(app):
        sup = app.state.indexing_supervisor
        async with w.engine.begin() as conn:
            await conn.execute(text("ALTER TABLE indexing_jobs RENAME TO audit_unavailable_jobs"))
        assert not await sup.authorize_admission()
        assert not sup.healthy
        async with w.engine.begin() as conn:
            await conn.execute(text("ALTER TABLE audit_unavailable_jobs RENAME TO indexing_jobs"))
        row = await job(w, jid)
        assert row.status == IndexingJobStatus.QUEUED and not row.recovery_required
        assert (await request(app, w)).status_code == 503


async def test_demo_lifespan_never_constructs_normal_supervisor(world, monkeypatch):
    import app.main as main

    w = world
    monkeypatch.setattr(
        main, "get_settings", lambda: w.settings.model_copy(update={"demo_mode": True})
    )
    monkeypatch.setattr(main, "engine", w.engine)

    def forbidden(*args):
        pytest.fail("Demo cannot construct a normal executor")

    monkeypatch.setattr(main, "IndexingSupervisor", forbidden)
    app = create_app()
    app.state.google_refresh_lifecycle = GoogleRefreshLifecycle()
    async with app.router.lifespan_context(app):
        assert app.state.indexing_supervisor is None
        assert not app.state.indexing_admission_ready


async def test_graceful_active_job_drains_with_heartbeat(world, monkeypatch):
    w = world
    await document(w)
    r = await runtime(w)
    app = create_app(indexing_test_runtime=r)
    entered, release, renewed = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class Blocking(Embeddings):
        async def embed_texts(self, texts):
            entered.set()
            await release.wait()
            return await super().embed_texts(texts)

    r.worker.embedding_service = Blocking()
    native = r.worker.renew_lease

    async def renewal(claim):
        await native(claim)
        if app.state.indexing_supervisor.stop.is_set():
            renewed.set()

    monkeypatch.setattr(r.worker, "renew_lease", renewal)
    context = app.router.lifespan_context(app)
    await context.__aenter__()
    jid = await enqueue(w, IndexingOperation.BUILD)
    await asyncio.wait_for(entered.wait(), 5)
    closing = asyncio.create_task(context.__aexit__(None, None, None))
    await asyncio.wait_for(renewed.wait(), 1)
    assert not app.state.indexing_admission_ready
    release.set()
    await settled(closing)
    assert (await job(w, jid)).status == IndexingJobStatus.COMPLETED
    assert app.state.indexing_supervisor.health == "STOPPED"


async def test_blocked_cancellation_cleanup_defers_engine_and_refresh_disposal(world, monkeypatch):
    w = world
    await document(w)
    r = await runtime(w)
    app = create_app(indexing_test_runtime=r)
    entered, cancelled, release, sql_cleaned = [asyncio.Event() for _ in range(4)]
    cancellations = 0

    class Blocking(Embeddings):
        async def embed_texts(self, texts):
            nonlocal cancellations
            entered.set()
            try:
                await asyncio.Event().wait()
                return await super().embed_texts(texts)
            except asyncio.CancelledError:
                cancellations += 1
                cancelled.set()
                await release.wait()
                async with r.worker.sessions() as db:
                    assert await db.scalar(select(1)) == 1
                sql_cleaned.set()
                raise

    r.worker.embedding_service = Blocking()
    disposed = []
    native_dispose = type(r.engine).dispose

    async def dispose(engine, *args, **kwargs):
        if engine is not r.engine:
            return await native_dispose(engine, *args, **kwargs)
        assert sql_cleaned.is_set()
        assert all(t.done() for t in app.state.indexing_supervisor.tasks.values())
        disposed.append(True)
        await native_dispose(engine, *args, **kwargs)

    monkeypatch.setattr(type(r.engine), "dispose", dispose)
    context = app.router.lifespan_context(app)
    await context.__aenter__()
    jid = await enqueue(w, IndexingOperation.BUILD)
    await asyncio.wait_for(entered.wait(), 5)
    try:
        await context.__aexit__(None, None, None)
        assert cancelled.is_set() and cancellations == 1
        assert not disposed and not r.refresh._closing
        assert not app.state.indexing_disposal_task.done()
        assert (await job(w, jid)).status == IndexingJobStatus.RUNNING
        # Repeated close cannot send a second cancellation into SQL cleanup.
        app.state.indexing_supervisor.begin_shutdown()
    finally:
        release.set()
        try:
            await settled(app.state.indexing_disposal_task)
        finally:
            # Also join under assertion-sensitivity faults that bypass the normal
            # disposal join; mutated tests must not leak tasks into fixture teardown.
            await settled(app.state.indexing_supervisor._shutdown_task)
    row = await job(w, jid)
    assert row.status == IndexingJobStatus.FAILED and row.recovery_required
    assert cancellations == 1 and disposed == [True] and r.refresh._closing


async def test_two_real_instances_start_and_shutdown_independently(world):
    w = world
    await document(w)
    await document(w, USER_B)
    a, b = await runtime(w), await runtime(w)
    app_a, app_b = create_app(indexing_test_runtime=a), create_app(indexing_test_runtime=b)
    entered, release = asyncio.Event(), asyncio.Event()

    class Held(Embeddings):
        async def embed_texts(self, texts):
            entered.set()
            await release.wait()
            return await super().embed_texts(texts)

    a.worker.embedding_service = Held()
    ca, cb = app_a.router.lifespan_context(app_a), app_b.router.lifespan_context(app_b)
    await ca.__aenter__()
    ja = await enqueue(w, IndexingOperation.BUILD)
    await asyncio.wait_for(entered.wait(), 5)
    before = await job(w, ja)
    try:
        await cb.__aenter__()
        assert await IndexingClassifier(b.worker).classify(ja) == "LIVE"
        assert (await job(w, ja)).claim_id == before.claim_id
        finished = asyncio.Event()
        native = b.worker.finalize

        async def final(*args, **kwargs):
            result = await native(*args, **kwargs)
            finished.set()
            return result

        b.worker.finalize = final
        jb = await enqueue(w, IndexingOperation.BUILD, USER_B)
        await asyncio.wait_for(finished.wait(), 5)
        assert (await job(w, jb)).status == IndexingJobStatus.COMPLETED
        release.set()
        await ca.__aexit__(None, None, None)
        assert app_b.state.indexing_supervisor.healthy
        assert (await job(w, ja)).status == IndexingJobStatus.COMPLETED
    finally:
        release.set()
        if app_a.state.indexing_supervisor.health != "STOPPED":
            await ca.__aexit__(None, None, None)
        if app_b.state.indexing_supervisor is not None:
            await cb.__aexit__(None, None, None)


async def test_expired_uncertain_build_is_classified_without_replay(world):
    w = world
    await document(w)
    # Use accepted claim/selection protocol, then model process loss before work.
    jid = await enqueue(w, IndexingOperation.BUILD)
    claim = await w.worker.claim_next()
    async with w.factory() as db:
        await db.execute(
            update(IndexingJob)
            .where(IndexingJob.id == jid)
            .values(
                lease_expires_at=func.clock_timestamp() - text("interval '1 second'"),
                recovery_required=True,
                attempt_manifest={"version": 99},
            )
        )
        legacy = IndexingJob(user_id=USER_B, status=IndexingJobStatus.RUNNING)
        db.add(legacy)
        await db.commit()
    r = await runtime(w)
    app = create_app(indexing_test_runtime=r)
    async with app.router.lifespan_context(app):
        row = await job(w, jid)
        assert row.status == IndexingJobStatus.FAILED and row.recovery_required
        assert row.claim_id == claim.claim_id
        assert (await job(w, legacy.id)).status == IndexingJobStatus.RUNNING
        assert not await w.client.collection_exists(w.settings.qdrant_collection)
        assert not await r.worker.finalize(claim, StageProgress())


async def test_application_cannot_start_a_second_owned_lifespan(world):
    r = await runtime(world)
    app = create_app(indexing_test_runtime=r)
    async with app.router.lifespan_context(app):
        owned = dict(app.state.indexing_supervisor.tasks)
        with pytest.raises(RuntimeError, match="twice"):
            async with app.router.lifespan_context(app):
                pytest.fail("Duplicate lifecycle admitted")
        assert app.state.indexing_supervisor.tasks == owned
        assert app.state.indexing_supervisor.healthy


async def test_idle_claim_connection_stall_is_bounded_and_unhealthy(world, monkeypatch):
    r = await runtime(world)
    app = create_app(indexing_test_runtime=r)
    entered = asyncio.Event()

    async def stall():
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(r.worker, "claim_next", stall)
    async with app.router.lifespan_context(app):
        await asyncio.wait_for(entered.wait(), 5)
        task = app.state.indexing_supervisor.tasks["worker"]
        await asyncio.wait([task], timeout=2)
        assert task.done() and not app.state.indexing_supervisor.healthy
        assert (await request(app, world)).status_code == 503


@pytest.mark.parametrize(
    "field,value",
    [
        ("poll_seconds", 0),
        ("classifier_seconds", 100),
        ("classification_batch", 0),
    ],
)
async def test_activation_settings_are_bounded(world, field, value):
    from dataclasses import replace

    r = await runtime(world)
    try:
        with pytest.raises(ValueError, match="bounded"):
            replace(r, **{field: value})
    finally:
        await r.engine.dispose()


async def test_activation_refuses_non_disposable_targets_and_demo(world, monkeypatch):
    from dataclasses import replace
    import app.main as main

    r = await runtime(world)
    try:
        old = r.worker.settings
        for change in [
            {"qdrant_url": "https://qdrant.example.invalid"},
            {"qdrant_collection": "HarborDesk"},
            {"demo_mode": True},
        ]:
            r.worker.settings = old.model_copy(update=change)
            with pytest.raises(ValueError, match="disposable"):
                replace(r)
        r.worker.settings = old
        monkeypatch.setattr(
            main, "get_settings", lambda: old.model_copy(update={"demo_mode": True})
        )
        with pytest.raises(ValueError, match="Demo"):
            create_app(indexing_test_runtime=r)
    finally:
        await r.engine.dispose()


async def test_real_unknown_remote_intent_is_not_replayed_on_startup(world, monkeypatch):
    from qdrant_client import AsyncQdrantClient

    w = world
    await document(w)
    jid = await enqueue(w, IndexingOperation.BUILD)
    entered = asyncio.Event()
    native = AsyncQdrantClient.upsert
    sends = 0

    async def lost_ack(client, *args, **kwargs):
        nonlocal sends
        await native(client, *args, **kwargs)
        sends += 1
        entered.set()
        await asyncio.Event().wait()

    async def crash(*args, **kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(AsyncQdrantClient, "upsert", lost_ack)
    monkeypatch.setattr(w.worker, "finalize", crash)
    task = asyncio.create_task(w.worker.run_once())
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with w.factory() as db:
        await db.execute(
            update(IndexingJob)
            .where(IndexingJob.id == jid)
            .values(lease_expires_at=func.clock_timestamp() - text("interval '1 second'"))
        )
        await db.commit()
    r = await runtime(w)
    app = create_app(indexing_test_runtime=r)
    async with app.router.lifespan_context(app):
        row = await job(w, jid)
        assert row.status == IndexingJobStatus.FAILED and row.recovery_required
        assert row.attempt_manifest["files"][0]["mutations"][-1]["outcome"] == "UNKNOWN"
        assert sends == 1
        assert (await request(app, w)).status_code == 409
        assert sends == 1


async def test_attempt_heartbeat_failure_is_visible_without_poisoning_other_owners(
    world, monkeypatch
):
    w = world
    await document(w)
    r = await runtime(w)
    app = create_app(indexing_test_runtime=r)
    entered, finalized = asyncio.Event(), asyncio.Event()

    class Blocking(Embeddings):
        async def embed_texts(self, texts):
            entered.set()
            await asyncio.Event().wait()
            return await super().embed_texts(texts)

    r.worker.embedding_service = Blocking()

    async def failed_heartbeat(claim, stop):
        await entered.wait()
        raise RuntimeError("Synthetic heartbeat failure")

    monkeypatch.setattr(r.worker, "_heartbeat", failed_heartbeat)
    original = r.worker.finalize

    async def final(*args, **kwargs):
        result = await original(*args, **kwargs)
        finalized.set()
        return result

    monkeypatch.setattr(r.worker, "finalize", final)
    async with app.router.lifespan_context(app):
        jid = await enqueue(w, IndexingOperation.BUILD)
        await asyncio.wait_for(finalized.wait(), 5)
        row = await job(w, jid)
        assert row.status == IndexingJobStatus.FAILED and row.recovery_required
        assert app.state.indexing_supervisor.healthy
        assert await enqueue(w, IndexingOperation.CHUNK, USER_B)


async def test_terminal_sql_failure_closes_executor_and_preserves_durable_attempt(
    world, monkeypatch
):
    w = world
    await document(w)
    r = await runtime(w)
    app = create_app(indexing_test_runtime=r)

    async def invalid(claim, *args, **kwargs):
        async with r.worker.sessions() as db:
            await db.execute(
                update(IndexingJob).where(IndexingJob.id == claim.job_id).values(processed=-1)
            )
            await db.commit()

    monkeypatch.setattr(r.worker, "finalize", invalid)
    async with app.router.lifespan_context(app):
        jid = await enqueue(w, IndexingOperation.BUILD)
        task = app.state.indexing_supervisor.tasks["worker"]
        await asyncio.wait([task], timeout=5)
        assert task.done() and not app.state.indexing_supervisor.healthy
        row = await job(w, jid)
        assert row.status == IndexingJobStatus.RUNNING and row.recovery_required
        assert row.processed == 1  # Invalid finalization rolled back, not overwritten.
        assert (await request(app, w)).status_code == 503


async def test_failure_during_claim_does_not_start_new_stage(world, monkeypatch):
    w = world
    r = await runtime(w)
    app = create_app(indexing_test_runtime=r)
    claimed, release = asyncio.Event(), asyncio.Event()
    native = r.worker.claim_next
    calls = []

    async def held():
        claim = await native()
        if claim is not None:
            claimed.set()
            await release.wait()
        return claim

    async def forbidden(*args):
        calls.append(True)
        pytest.fail("A new stage cannot begin after known local health failure")

    monkeypatch.setattr(r.worker, "claim_next", held)
    monkeypatch.setattr(r.worker, "execute", forbidden)
    async with app.router.lifespan_context(app):
        jid = await enqueue(w, IndexingOperation.CHUNK)
        await asyncio.wait_for(claimed.wait(), 5)
        sup = app.state.indexing_supervisor
        sup.tasks["classifier"].cancel()
        await asyncio.wait([sup.tasks["classifier"]], timeout=1)
        assert not sup.healthy
        release.set()
        await asyncio.wait([sup.tasks["worker"]], timeout=2)
        assert sup.tasks["worker"].done()
        assert not calls
        row = await job(w, jid)
        assert row.status == IndexingJobStatus.FAILED and not row.recovery_required


async def test_accepted_queued_job_survives_executor_failure(world, monkeypatch):
    w = world
    r = await runtime(w)
    app = create_app(indexing_test_runtime=r)
    entered, fail = asyncio.Event(), asyncio.Event()

    async def claim():
        entered.set()
        await fail.wait()
        raise RuntimeError("Synthetic connection failure before claim")

    monkeypatch.setattr(r.worker, "claim_next", claim)
    async with app.router.lifespan_context(app):
        await asyncio.wait_for(entered.wait(), 5)
        response = await request(app, w)
        assert response.status_code == 202
        from uuid import UUID

        jid = UUID(response.json()["job_id"])
        fail.set()
        sup = app.state.indexing_supervisor
        await asyncio.wait([sup.tasks["worker"]], timeout=2)
        assert not sup.healthy
        row = await job(w, jid)
        assert row.status == IndexingJobStatus.QUEUED and row.claim_id is None
        assert (await request(app, w)).status_code == 503


async def test_classifier_candidate_batch_excludes_demo_identity(world, monkeypatch):
    from .conftest import DEMO_USER

    w = world
    r = await runtime(w)
    jid = await enqueue(w, IndexingOperation.CHUNK)
    claim = await w.worker.claim_next()
    async with w.factory() as db:
        db.add(
            IndexingJob(
                user_id=DEMO_USER,
                operation=IndexingOperation.BUILD,
                status=IndexingJobStatus.RUNNING,
                claim_id=uuid4(),
                worker_id=uuid4(),
                lease_expires_at=func.clock_timestamp() - text("interval '2 seconds'"),
            )
        )
        await db.execute(
            update(IndexingJob)
            .where(IndexingJob.id == jid)
            .values(lease_expires_at=func.clock_timestamp() - text("interval '1 second'"))
        )
        await db.commit()
    sup = IndexingSupervisor(r)
    from dataclasses import replace

    sup.runtime = replace(r, classification_batch=1)
    called = []
    native = sup.classifier.classify

    async def classified(jid):
        called.append(jid)
        return await native(jid)

    monkeypatch.setattr(sup.classifier, "classify", classified)
    try:
        await sup._classification_round()
        assert called == [jid]  # Older demo work cannot starve real-owner expiry.
        assert (await job(w, jid)).status == IndexingJobStatus.FAILED
        assert not await w.worker.finalize(claim, StageProgress())
    finally:
        await r.refresh.shutdown_and_dispose(r.engine.dispose)
