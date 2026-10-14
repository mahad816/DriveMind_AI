"""Actual normal lifespan, read-only activation, real disposable PostgreSQL/Qdrant."""

import asyncio
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from qdrant_client.models import Distance, VectorParams, PayloadSchemaType
from sqlalchemy import select, text, update

from app.core.config import get_settings
from app.db.session import get_db
from app.db.models.indexing_job import IndexingJob
from app.db.models.user import User
from app.db.enums import IndexingJobStatus, IndexingOperation
from app.services.indexing_runtime import (
    activation_target,
    IndexingActivationError,
    NormalIndexingRuntime,
)
from app.services.indexing_worker import IndexingWorker
from .conftest import USER_A, USER_B, apply_revision
from .test_indexing_worker import (
    world,
    final_engine,
    keys,
    owner_engine,
    qdrant_client,
    enqueue,
    document,
    job,
)
from .test_indexing_lifecycle import runtime, headers

__all__ = ["world", "final_engine", "keys", "owner_engine", "qdrant_client"]


class SyntheticEmbeddings:
    model_name = "text-embedding-3-small"
    embedding_dimension = 1536

    async def embed_texts(self, texts):
        return [[1.0] + [0.0] * 1535 for _ in texts]


async def normal_app(w, monkeypatch, *, schema=True, collection=True):
    from app import main
    from app.services import indexing_runtime

    r = await runtime(w)
    async with w.engine.begin() as db:
        name = await db.scalar(text("SELECT current_schema()"))
        if schema and not await db.scalar(text("SELECT to_regclass('alembic_version')")):
            await db.run_sync(apply_revision, "20261015_1200")
            await db.execute(
                text("CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)")
            )
            await db.execute(text("INSERT INTO alembic_version VALUES ('20261015_1200')"))
    settings = w.settings.model_copy(
        update={
            "database_url": r.engine.url.render_as_string(hide_password=False),
            "indexing_enabled": True,
            "indexing_database_schema": name,
            "google_application_sessions_enabled": True,
            "google_session_redirect_uri": w.settings.frontend_url
            + "/api/v1/auth/session/google/callback",
            "openai_api_key": "synthetic-unused",
            "indexing_dependency_seconds": 0.05,
            "indexing_dependency_timeout": 0.6,
            "indexing_poll_seconds": 0.05,
            "indexing_classifier_seconds": 0.05,
            "indexing_startup_timeout": 5,
            "indexing_drain_seconds": 0.2,
            "indexing_cleanup_seconds": 0.05,
        }
    )
    settings.indexing_activation_target = activation_target(settings)
    if collection and not await w.client.collection_exists(settings.qdrant_collection):
        await w.client.create_collection(
            settings.qdrant_collection,
            vectors_config=VectorParams(size=1536, distance=Distance.COSINE),
        )
        for field in ("user_id", "drive_file_id"):
            await w.client.create_payload_index(
                settings.qdrant_collection,
                field_name=field,
                field_schema=PayloadSchemaType.KEYWORD,
                wait=True,
            )
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    monkeypatch.setattr(main, "SessionLocal", r.worker.sessions)
    monkeypatch.setattr(main, "engine", r.engine)
    monkeypatch.setattr(main, "google_refresh_lifecycle", r.refresh)
    monkeypatch.setattr(
        indexing_runtime, "get_embedding_service", lambda _settings: SyntheticEmbeddings()
    )
    app = main.create_app()  # No disposable injection: run the actual configuration path.

    async def database():
        async with r.worker.sessions() as db:
            yield db

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_settings] = lambda: settings
    return app, settings, r


async def post(app, w, owner=USER_A, stage="chunk", auth=None):
    async with AsyncClient(transport=ASGITransport(app), base_url=w.settings.frontend_url) as c:
        return await c.post(
            "/api/v1/index/" + stage, headers=auth if auth is not None else await headers(w, owner)
        )


async def test_default_off_ignores_app_state_runtime_override(world, monkeypatch):
    app, settings, r = await normal_app(world, monkeypatch)
    settings.indexing_enabled = False
    app.state.indexing_test_runtime = r  # Diagnostic state must not grant authority.
    async with app.router.lifespan_context(app):
        assert app.state.indexing_supervisor is None
        assert (await post(app, world)).status_code == 503


async def test_demo_activation_rejected_without_network(world, monkeypatch):
    from app import main

    _, settings, r = await normal_app(world, monkeypatch)
    settings.demo_mode = True
    with pytest.raises(ValueError, match="Demo applications"):
        main.create_app()
    await r.refresh.shutdown_and_dispose(r.engine.dispose)


@pytest.mark.parametrize(
    "fault,code",
    [
        ("binding", "ACTIVATION_TARGET_MISMATCH"),
        ("schema", "SCHEMA_INCOMPATIBLE"),
        ("index_predicate", "SCHEMA_INCOMPATIBLE"),
        ("collection", "CONCRETE_COLLECTION_REQUIRED"),
        ("dimension", "VECTOR_CONFIGURATION_INCOMPATIBLE"),
        ("distance", "VECTOR_CONFIGURATION_INCOMPATIBLE"),
        ("named", "VECTOR_CONFIGURATION_INCOMPATIBLE"),
        ("alias", "CONCRETE_COLLECTION_REQUIRED"),
        ("embedding_key", "EMBEDDING_CREDENTIAL_REQUIRED"),
        ("payload", "PAYLOAD_INDEXES_REQUIRED"),
        ("security", "SECURITY_OR_TARGET_CONFIGURATION_INVALID"),
    ],
)
async def test_activation_refuses_invalid_dependencies_before_claim_or_mutation(
    world, monkeypatch, fault, code
):
    w = world
    app, settings, _ = await normal_app(w, monkeypatch)
    queued = await enqueue(w, IndexingOperation.CHUNK)
    if fault == "binding":
        settings.indexing_activation_target = "invalid"
    elif fault == "schema":
        async with w.engine.begin() as db:
            await db.execute(
                text("ALTER TABLE indexing_jobs DROP CONSTRAINT ck_indexing_jobs_manifest_size")
            )
    elif fault == "index_predicate":
        async with w.engine.begin() as db:
            await db.execute(text("DROP INDEX uq_indexing_jobs_unresolved_owner"))
            await db.execute(
                text(
                    "CREATE UNIQUE INDEX uq_indexing_jobs_unresolved_owner ON indexing_jobs(user_id) WHERE operation IS NOT NULL AND (status IN ('QUEUED','RUNNING') AND recovery_required)"
                )
            )
    elif fault == "collection":
        await w.client.delete_collection(settings.qdrant_collection)
    elif fault == "dimension":
        await w.client.delete_collection(settings.qdrant_collection)
        await w.client.create_collection(
            settings.qdrant_collection,
            vectors_config=VectorParams(size=3, distance=Distance.COSINE),
        )
    elif fault in {"distance", "named"}:
        await w.client.delete_collection(settings.qdrant_collection)
        vectors = VectorParams(
            size=1536, distance=Distance.EUCLID if fault == "distance" else Distance.COSINE
        )
        await w.client.create_collection(
            settings.qdrant_collection,
            vectors_config={"dense": vectors} if fault == "named" else vectors,
        )
    elif fault == "alias":
        from qdrant_client.models import CreateAliasOperation, CreateAlias

        await w.client.update_collection_aliases(
            [
                CreateAliasOperation(
                    create_alias=CreateAlias(
                        collection_name=settings.qdrant_collection,
                        alias_name=settings.qdrant_collection + "_alias",
                    )
                )
            ]
        )
        settings.qdrant_collection += "_alias"
        settings.indexing_activation_target = activation_target(settings)
    elif fault == "embedding_key":
        settings.openai_api_key = ""
    elif fault == "payload":
        await w.client.delete_payload_index(
            settings.qdrant_collection, field_name="user_id", wait=True
        )
    else:
        settings.google_credential_encryption_keyring = None
    with pytest.raises(IndexingActivationError, match=code):
        async with app.router.lifespan_context(app):
            pytest.fail("Invalid activation started")
    assert not app.state.indexing_admission_ready
    assert (await job(w, queued)).status == IndexingJobStatus.QUEUED
    assert (await post(app, w)).status_code == 503
    if fault == "collection":
        assert not await w.client.collection_exists(settings.qdrant_collection)
    else:
        assert (await w.client.count(settings.qdrant_collection, exact=True)).count == 0


async def test_normal_lifespan_synthetic_two_owner_pipeline_and_exact_job_polling(
    world, monkeypatch
):
    w = world
    app, settings, _ = await normal_app(w, monkeypatch)
    async with app.router.lifespan_context(app):
        sup = app.state.indexing_supervisor
        assert isinstance(sup.runtime, NormalIndexingRuntime) and sup.healthy
        assert set(sup.tasks) == {"worker", "classifier", "dependencies"}
        completed = asyncio.Queue()
        native = sup.worker.finalize

        async def final(claim, *args, **kwargs):
            value = await native(claim, *args, **kwargs)
            await completed.put(claim.job_id)
            return value

        monkeypatch.setattr(sup.worker, "finalize", final)
        for owner in (USER_A, USER_B):
            for stage in ("sync", "ingest", "chunk", "build"):
                response = await post(app, w, owner, stage)
                assert response.status_code == 202, response.text
                jid = UUID(response.json()["job_id"])
                assert (await job(w, jid)).user_id == owner
                assert await asyncio.wait_for(completed.get(), 5) == jid
                assert (await job(w, jid)).status == IndexingJobStatus.COMPLETED
                async with AsyncClient(
                    transport=ASGITransport(app), base_url=settings.frontend_url
                ) as c:
                    polled = await c.get(
                        f"/api/v1/index/status?job_id={jid}",
                        headers=await headers(w, owner),
                    )
                    assert (
                        polled.status_code == 200 and polled.json()["job"]["status"] == "completed"
                    )
                    foreign = USER_B if owner == USER_A else USER_A
                    assert (
                        await c.get(
                            f"/api/v1/index/status?job_id={jid}", headers=await headers(w, foreign)
                        )
                    ).status_code == 404
        points, _ = await w.client.scroll(settings.qdrant_collection, limit=100, with_vectors=True)
        assert {point.payload["user_id"] for point in points} == {str(USER_A), str(USER_B)}
        assert all(len(point.vector) == 1536 for point in points)
    assert sup.health == "STOPPED" and all(task.done() for task in sup.tasks.values())


@pytest.mark.parametrize("dependency", ["database", "qdrant"])
async def test_runtime_dependency_loss_closes_health_and_http_admission(
    world, monkeypatch, dependency
):
    w = world
    app, settings, _ = await normal_app(w, monkeypatch)
    async with app.router.lifespan_context(app):
        sup = app.state.indexing_supervisor
        if dependency == "qdrant":
            await w.client.delete_collection(settings.qdrant_collection)
        else:
            async with w.engine.begin() as db:
                await db.execute(text("ALTER TABLE indexing_jobs RENAME TO unavailable_jobs"))
        await asyncio.wait([sup.tasks["dependencies"]], timeout=4)
        assert sup.tasks["dependencies"].done() and not sup.healthy
        assert (await post(app, w)).status_code == 503
        assert sup.failure_reason is not None
        if dependency == "database":
            async with w.engine.begin() as db:
                await db.execute(text("ALTER TABLE unavailable_jobs RENAME TO indexing_jobs"))
        else:
            assert not await w.client.collection_exists(settings.qdrant_collection)


async def test_normal_restart_preserves_live_claim_and_uncertain_build(world, monkeypatch):
    w = world
    live_id = await enqueue(w, IndexingOperation.CHUNK, owner=USER_A)
    live = await w.worker.claim_next()
    uncertain = await enqueue(w, IndexingOperation.BUILD, owner=USER_B)
    async with w.factory() as db:
        await db.execute(
            update(IndexingJob)
            .where(IndexingJob.id == uncertain)
            .values(
                status=IndexingJobStatus.RUNNING,
                claim_id=uuid4(),
                worker_id=uuid4(),
                lease_expires_at=text("clock_timestamp() - interval '1 second'"),
                recovery_required=True,
            )
        )
        await db.commit()
    app, _, _ = await normal_app(w, monkeypatch)
    async with app.router.lifespan_context(app):
        assert (await job(w, live_id)).claim_id == live.claim_id
        assert (await job(w, live_id)).status == IndexingJobStatus.RUNNING
        row = await job(w, uncertain)
        assert row.status == IndexingJobStatus.FAILED and row.recovery_required
        assert (await post(app, w, USER_B)).status_code == 409
        assert (await w.client.count(w.settings.qdrant_collection, exact=True)).count == 0


@pytest.mark.parametrize("closure", ["shutdown", "classifier_failure"])
async def test_normal_shutdown_rejects_owner_lock_waiter_and_joins_cleanup(
    world, monkeypatch, closure
):
    from app.services.indexing_job_service import IndexingJobService

    w = world
    app, _, _ = await normal_app(w, monkeypatch)
    entered = asyncio.Event()
    auth = await headers(w)
    native = IndexingJobService.admit

    async def admit(service, *args, **kwargs):
        entered.set()
        return await native(service, *args, **kwargs)

    monkeypatch.setattr(IndexingJobService, "admit", admit)
    async with app.router.lifespan_context(app):
        sup = app.state.indexing_supervisor
        async with w.factory() as blocker:
            await blocker.scalar(select(User.id).where(User.id == USER_A).with_for_update())
            request = asyncio.create_task(post(app, w, auth=auth))
            await asyncio.wait_for(entered.wait(), 3)
            from .test_indexing_admission_closure import owner_wait

            await owner_wait(w)
            if closure == "classifier_failure":
                sup.tasks["classifier"].cancel()
                await asyncio.wait([sup.tasks["classifier"]], timeout=1)
            else:
                sup.begin_shutdown()  # Synchronous closure before final SQL authorization.
            await blocker.rollback()
            response = await asyncio.wait_for(request, 3)
            assert response.status_code == 503
            assert sup.admission_count == 0
            async with w.factory() as db:
                assert list((await db.scalars(select(IndexingJob))).all()) == []


async def test_two_normal_instances_do_not_duplicate_claim_or_stop_each_other(world, monkeypatch):
    w = world
    await document(w)
    queued = await enqueue(w, IndexingOperation.CHUNK)
    a, _, _ = await normal_app(w, monkeypatch)
    b, _, _ = await normal_app(w, monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()
    native = IndexingWorker.execute
    seen = []

    async def execute(worker, claim):
        seen.append(claim.job_id)
        entered.set()
        await release.wait()
        return await native(worker, claim)

    monkeypatch.setattr(IndexingWorker, "execute", execute)
    async with a.router.lifespan_context(a), b.router.lifespan_context(b):
        await asyncio.wait_for(entered.wait(), 5)
        assert seen == [queued]
        assert a.state.indexing_supervisor.healthy and b.state.indexing_supervisor.healthy
        release.set()
        a.state.indexing_supervisor.begin_shutdown()
        await asyncio.wait_for(a.state.indexing_supervisor.wait_closed(), 5)
        assert b.state.indexing_supervisor.healthy


async def test_startup_executor_failure_never_opens_admission(world, monkeypatch):
    from app.services.indexing_lifecycle import IndexingSupervisor

    app, _, _ = await normal_app(world, monkeypatch)

    async def fail_poll(_supervisor):
        raise RuntimeError("Synthetic polling failure")

    monkeypatch.setattr(IndexingSupervisor, "_poll", fail_poll)
    with pytest.raises(RuntimeError, match="handshake"):
        async with app.router.lifespan_context(app):
            pytest.fail("Broken executor became ready")
    assert not app.state.indexing_admission_ready
    assert all(task.done() for task in app.state.indexing_supervisor.tasks.values())
    assert (await post(app, world)).status_code == 503


async def test_normal_dependency_cleanup_defers_disposal_until_joined(world, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

    w = world
    app, _, r = await normal_app(w, monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()
    disposed = []
    close, dispose = AsyncSession.close, AsyncEngine.dispose
    context = app.router.lifespan_context(app)
    await context.__aenter__()

    async def blocked_close(db):
        task = asyncio.current_task()
        if task is not None and task.get_name() == "indexing-dependency-cleanup":
            entered.set()
            await release.wait()
        await close(db)

    async def record_dispose(engine, *args, **kwargs):
        if engine is r.engine:
            disposed.append(True)
        await dispose(engine, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "close", blocked_close)
    monkeypatch.setattr(AsyncEngine, "dispose", record_dispose)
    try:
        await asyncio.wait_for(entered.wait(), 3)
        await asyncio.wait_for(context.__aexit__(None, None, None), 3)
        assert not disposed
        assert not app.state.indexing_disposal_task.done()
        assert not app.state.indexing_supervisor.healthy
    finally:
        release.set()
        await asyncio.wait_for(app.state.indexing_disposal_task, 5)
    assert disposed == [True]
    assert all(task.done() for task in app.state.indexing_supervisor.tasks.values())


async def test_restart_claims_queued_and_classifies_expired_sql_without_replay(world, monkeypatch):
    w = world
    expired = await enqueue(w, IndexingOperation.CHUNK)
    claim = await w.worker.claim_next()
    async with w.factory() as db:
        await db.execute(
            update(IndexingJob)
            .where(IndexingJob.id == expired)
            .values(lease_expires_at=text("clock_timestamp() - interval '1 second'"))
        )
        await db.commit()
    queued = await enqueue(w, IndexingOperation.CHUNK, owner=USER_B)
    app, _, _ = await normal_app(w, monkeypatch)
    completed = asyncio.Event()
    native = IndexingWorker.finalize

    async def final(worker, active, *args, **kwargs):
        value = await native(worker, active, *args, **kwargs)
        if active.job_id == queued:
            completed.set()
        return value

    monkeypatch.setattr(IndexingWorker, "finalize", final)
    async with app.router.lifespan_context(app):
        await asyncio.wait_for(completed.wait(), 5)
        assert (await job(w, queued)).status == IndexingJobStatus.COMPLETED
        old = await job(w, expired)
        assert old.status == IndexingJobStatus.FAILED and not old.recovery_required
        assert old.claim_id == claim.claim_id


async def test_normal_issued_build_with_lost_acknowledgement_remains_blocked(world, monkeypatch):
    from qdrant_client import AsyncQdrantClient

    w = world
    await document(w)
    chunk = await enqueue(w, IndexingOperation.CHUNK)
    await w.worker.run_once()
    assert (await job(w, chunk)).status == IndexingJobStatus.COMPLETED
    app, _, _ = await normal_app(w, monkeypatch)
    native = AsyncQdrantClient.upsert
    written = asyncio.Event()

    async def lost_ack(client, *args, **kwargs):
        await native(client, *args, **kwargs)
        written.set()
        raise TimeoutError("Synthetic lost acknowledgement")

    monkeypatch.setattr(AsyncQdrantClient, "upsert", lost_ack)
    finalized = asyncio.Event()
    original_final = IndexingWorker.finalize

    async def final(worker, claim, *args, **kwargs):
        value = await original_final(worker, claim, *args, **kwargs)
        finalized.set()
        return value

    monkeypatch.setattr(IndexingWorker, "finalize", final)
    async with app.router.lifespan_context(app):
        response = await post(app, w, stage="build")
        assert response.status_code == 202
        jid = UUID(response.json()["job_id"])
        await asyncio.wait_for(written.wait(), 5)
        await asyncio.wait_for(finalized.wait(), 5)
        row = await job(w, jid)
        assert row.status == IndexingJobStatus.FAILED and row.recovery_required
        assert row.attempt_manifest is not None
        assert (await w.client.count(w.settings.qdrant_collection, exact=True)).count > 0
        assert (await post(app, w)).status_code == 409


async def test_cooperative_maintenance_closes_normal_runtime_without_releasing_jobs(
    world, monkeypatch
):
    from app.services.indexing_maintenance import LOCK_KEY

    w = world
    app, _, _ = await normal_app(w, monkeypatch)
    auth = await headers(w)
    async with app.router.lifespan_context(app):
        sup = app.state.indexing_supervisor
        async with w.engine.connect() as maintenance:
            await maintenance.execute(text("SELECT pg_advisory_lock(:key)"), {"key": LOCK_KEY})
            try:
                async with w.factory() as db:
                    queued = IndexingJob(user_id=USER_B, operation=IndexingOperation.BUILD)
                    db.add(queued)
                    await db.commit()
                await asyncio.wait([sup.tasks["dependencies"]], timeout=4)
                assert not sup.healthy and sup.failure_reason == "MAINTENANCE_ACTIVE"
                assert (await post(app, w, auth=auth)).status_code == 503
                row = await job(w, queued.id)
                assert row.status == IndexingJobStatus.QUEUED and row.claim_id is None
                assert (await w.client.count(w.settings.qdrant_collection, exact=True)).count == 0
            finally:
                await maintenance.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY}
                )


async def test_blocked_dependency_round_closes_health_before_cleanup_finishes(world, monkeypatch):
    from app.services.indexing_runtime import NormalIndexingRuntime

    app, _, _ = await normal_app(world, monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()

    async def stuck(_runtime):
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()  # Model an owned SQL close that must finish.

    async with app.router.lifespan_context(app):
        sup = app.state.indexing_supervisor
        monkeypatch.setattr(NormalIndexingRuntime, "check_dependencies", stuck)
        await asyncio.wait_for(entered.wait(), 3)
        await asyncio.wait_for(sup.stop.wait(), 3)
        assert not sup.healthy and sup.failure_reason == "DEPENDENCY_CHECK_TIMEOUT"
        assert not sup.tasks["dependencies"].done()
        assert (await post(app, world)).status_code == 503
        release.set()


async def test_normal_adapter_cannot_bypass_enablement_through_test_injection(world, monkeypatch):
    from typing import cast
    from app import main
    from app.services.indexing_lifecycle import DisposableIndexingRuntime
    from app.services.indexing_runtime import create_normal_runtime

    _, settings, r = await normal_app(world, monkeypatch)
    normal = await create_normal_runtime(r.worker.sessions, r.refresh, settings)
    settings.indexing_enabled = False
    try:
        with pytest.raises(ValueError, match="Only validated disposable"):
            main.create_app(indexing_test_runtime=cast(DisposableIndexingRuntime, normal))
    finally:
        await r.refresh.shutdown_and_dispose(r.engine.dispose)
