"""Authenticated HTTP admission and real PostgreSQL lock/closure ordering."""

import asyncio
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text

from app.db.enums import IndexingJobStatus
from app.db.models.indexing_job import IndexingJob
from app.db.models.user import User
from app.main import create_app
from .conftest import USER_A
from .test_indexing_worker import final_engine, keys, owner_engine, qdrant_client, world, job
from .test_indexing_lifecycle import headers, runtime

__all__ = ["final_engine", "keys", "owner_engine", "qdrant_client", "world"]


async def owner_wait(w):
    async with w.factory() as observer, asyncio.timeout(3):
        while not await observer.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE wait_event_type='Lock' "
                "AND query LIKE '%users.id%' AND query LIKE '%FOR UPDATE%' AND pid<>pg_backend_pid())"
            )
        ):
            await observer.scalar(select(func.pg_stat_clear_snapshot()))


async def job_count(w):
    async with w.factory() as db:
        return await db.scalar(select(func.count()).select_from(IndexingJob))


@pytest.mark.parametrize("boundary", ["classifier_failure", "shutdown"])
async def test_owner_lock_wait_rejects_when_lifecycle_closure_wins(world, boundary, monkeypatch):
    w = world
    r = await runtime(w)
    app = create_app(indexing_test_runtime=r)
    auth = await headers(w)
    context = app.router.lifespan_context(app)
    await context.__aenter__()
    sup = app.state.indexing_supervisor
    closed = False
    closing_task = None
    shutdown_entered = asyncio.Event()
    native_shutdown = sup.begin_shutdown

    def shutdown():
        native_shutdown()
        shutdown_entered.set()

    monkeypatch.setattr(sup, "begin_shutdown", shutdown)
    async with w.factory() as blocker:
        await blocker.scalar(select(User.id).where(User.id == USER_A).with_for_update())
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url=w.settings.frontend_url
        ) as client:
            task = asyncio.create_task(client.post("/api/v1/index/chunk", headers=auth))
            try:
                await owner_wait(w)
                assert not task.done() and sup.healthy
                if boundary == "shutdown":
                    closing_task = asyncio.create_task(context.__aexit__(None, None, None))
                    closed = True
                    await asyncio.wait_for(shutdown_entered.wait(), 3)
                    # Release before the SQL deadline, forcing the coordinated
                    # post-lock guard (rather than timeout) to reject publication.
                    assert not app.state.indexing_disposal_task.done()
                else:
                    sup.tasks["classifier"].cancel()
                    await asyncio.wait(list(sup.tasks.values()), timeout=2)
                    assert all(t.done() for t in sup.tasks.values())
                assert not sup.healthy
                await blocker.rollback()
                response = await asyncio.wait_for(task, 3)
                assert response.status_code == 503
                assert await job_count(w) == 0
            finally:
                await blocker.rollback()
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                if closing_task is not None:
                    await asyncio.wait_for(closing_task, 3)
                elif not closed:
                    await context.__aexit__(None, None, None)


async def test_authorization_wins_before_fatal_failure_and_durable_commit_remains_valid(
    world, monkeypatch
):
    from sqlalchemy.ext.asyncio import AsyncSession

    w = world
    r = await runtime(w)
    app = create_app(indexing_test_runtime=r)
    auth = await headers(w)
    entered, release = asyncio.Event(), asyncio.Event()
    native = AsyncSession.commit

    async def hold_commit(db):
        if any(isinstance(row, IndexingJob) for row in db.new):
            permit = next(iter(app.state.indexing_supervisor._admissions))
            assert permit.authorized
            entered.set()
            await release.wait()
        await native(db)

    monkeypatch.setattr(AsyncSession, "commit", hold_commit)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url=w.settings.frontend_url
        ) as client:
            task = asyncio.create_task(client.post("/api/v1/index/chunk", headers=auth))
            try:
                await asyncio.wait_for(entered.wait(), 3)
                sup = app.state.indexing_supervisor
                sup.tasks["classifier"].cancel()
                await asyncio.wait(list(sup.tasks.values()), timeout=2)
                assert not sup.healthy
                release.set()
                response = await asyncio.wait_for(task, 3)
                assert response.status_code == 202
                row = await job(w, UUID(response.json()["job_id"]))
                assert row.user_id == USER_A and row.status == IndexingJobStatus.QUEUED
                assert sup.admission_count == 0
            finally:
                release.set()
                if not task.done():
                    await asyncio.gather(task, return_exceptions=True)


async def test_http_cancellation_during_owner_wait_joins_sql_cleanup_and_registration(world):
    w = world
    r = await runtime(w)
    app = create_app(indexing_test_runtime=r)
    auth = await headers(w)
    async with app.router.lifespan_context(app):
        async with w.factory() as blocker:
            await blocker.scalar(select(User.id).where(User.id == USER_A).with_for_update())
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url=w.settings.frontend_url
            ) as client:
                task = asyncio.create_task(client.post("/api/v1/index/chunk", headers=auth))
                await owner_wait(w)
                assert app.state.indexing_supervisor.admission_count == 1
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert app.state.indexing_supervisor.admission_count == 0
                assert await job_count(w) == 0
            await blocker.rollback()
    from sqlalchemy.pool import AsyncAdaptedQueuePool

    assert isinstance(r.engine.pool, AsyncAdaptedQueuePool)
    assert r.engine.pool.checkedout() == 0


async def test_blocked_admission_rollback_defers_disposal_and_ignores_repeated_cancellation(
    world, monkeypatch
):
    from sqlalchemy.ext.asyncio import AsyncSession

    w = world
    r = await runtime(w)
    app = create_app(indexing_test_runtime=r)
    auth = await headers(w)
    rollback_entered, release, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    native_rollback, native_close = AsyncSession.rollback, AsyncSession.close
    captured = []

    async def rollback(db):
        current = asyncio.current_task()
        if (
            current is not None
            and current.get_name() == "indexing-admission-cleanup"
            and not captured
        ):
            captured.append(db)
            rollback_entered.set()
            await release.wait()
        await native_rollback(db)

    async def close(db):
        await native_close(db)
        if captured and db is captured[0]:
            closed.set()

    monkeypatch.setattr(AsyncSession, "rollback", rollback)
    monkeypatch.setattr(AsyncSession, "close", close)
    disposals = []
    native_dispose = type(r.engine).dispose

    async def dispose(engine, *args, **kwargs):
        if engine is r.engine:
            assert closed.is_set()
            assert app.state.indexing_supervisor.admission_count == 0
            disposals.append(True)
        await native_dispose(engine, *args, **kwargs)

    monkeypatch.setattr(type(r.engine), "dispose", dispose)
    context = app.router.lifespan_context(app)
    await context.__aenter__()
    async with w.factory() as blocker:
        await blocker.scalar(select(User.id).where(User.id == USER_A).with_for_update())
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url=w.settings.frontend_url
        ) as client:
            task = asyncio.create_task(client.post("/api/v1/index/chunk", headers=auth))
            try:
                await owner_wait(w)
                closing = asyncio.create_task(context.__aexit__(None, None, None))
                await asyncio.wait_for(rollback_entered.wait(), 3)
                await asyncio.wait_for(closing, 3)  # Bounded lifespan returns, disposal deferred.
                sup = app.state.indexing_supervisor
                assert sup.admission_count == 1 and not disposals
                assert not app.state.indexing_disposal_task.done()
                sup.begin_shutdown()
                task.cancel()
                task.cancel()  # Cleanup task itself must not be cancelled again.
                assert not next(iter(sup._admissions)).cleanup.cancelled()
            finally:
                release.set()
                await blocker.rollback()
                await asyncio.gather(task, return_exceptions=True)
                await asyncio.wait_for(asyncio.shield(app.state.indexing_disposal_task), 3)
            assert disposals == [True]
            assert await job_count(w) == 0


async def test_ungranted_admission_timeout_rolls_back_without_insertion(world):
    w = world
    r = await runtime(w)
    app = create_app(indexing_test_runtime=r)
    auth = await headers(w)
    async with app.router.lifespan_context(app):
        async with w.factory() as blocker:
            await blocker.scalar(select(User.id).where(User.id == USER_A).with_for_update())
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url=w.settings.frontend_url
            ) as client:
                task = asyncio.create_task(client.post("/api/v1/index/chunk", headers=auth))
                await owner_wait(w)
                response = await asyncio.wait_for(task, 3)
                assert response.status_code == 503
                assert await job_count(w) == 0
                assert app.state.indexing_supervisor.admission_count == 0
                assert app.state.indexing_supervisor.healthy
            await blocker.rollback()


async def test_different_owner_admission_is_not_serialized_behind_a_local_wait(world):
    from .conftest import USER_B

    w = world
    r = await runtime(w)
    app = create_app(indexing_test_runtime=r)
    a, b = await headers(w), await headers(w, USER_B)
    async with app.router.lifespan_context(app):
        async with w.factory() as blocker:
            await blocker.scalar(select(User.id).where(User.id == USER_A).with_for_update())
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url=w.settings.frontend_url
            ) as client:
                task = asyncio.create_task(client.post("/api/v1/index/chunk", headers=a))
                try:
                    await owner_wait(w)
                    response = await client.post("/api/v1/index/chunk", headers=b)
                    assert response.status_code == 202 and not task.done()
                    assert (await job(w, UUID(response.json()["job_id"]))).user_id == USER_B
                    await blocker.rollback()
                    assert (await task).status_code == 202
                finally:
                    await blocker.rollback()
                    if not task.done():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("two_instances", [False, True])
async def test_same_owner_concurrency_keeps_database_exclusion(world, monkeypatch, two_instances):
    from dataclasses import replace

    w = world
    first = replace(await runtime(w), database_timeout=3)
    second = replace(await runtime(w), database_timeout=3) if two_instances else None
    a = create_app(indexing_test_runtime=first)
    b = create_app(indexing_test_runtime=second) if second else a
    auth = await headers(w)

    async def no_claim():
        await asyncio.Event().wait()

    monkeypatch.setattr(first.worker, "claim_next", no_claim)
    if second:
        monkeypatch.setattr(second.worker, "claim_next", no_claim)
    ca = a.router.lifespan_context(a)
    cb = b.router.lifespan_context(b) if second else None
    await ca.__aenter__()
    if cb:
        await cb.__aenter__()
    try:
        async with (
            AsyncClient(transport=ASGITransport(app=a), base_url=w.settings.frontend_url) as c1,
            AsyncClient(transport=ASGITransport(app=b), base_url=w.settings.frontend_url) as c2,
        ):
            responses = await asyncio.gather(
                c1.post("/api/v1/index/chunk", headers=auth),
                c2.post("/api/v1/index/chunk", headers=auth),
            )
            assert sorted(r.status_code for r in responses) == [202, 409]
            assert await job_count(w) == 1
            assert a.state.indexing_supervisor.admission_count == 0
            assert b.state.indexing_supervisor.admission_count == 0
    finally:
        await ca.__aexit__(None, None, None)
        if cb:
            assert b.state.indexing_supervisor.healthy
            await cb.__aexit__(None, None, None)


async def test_service_authorization_is_required_and_rejects_before_insert(world):
    from app.services.indexing_job_service import IndexingJobService, IndexingAdmissionUnavailable
    from app.db.enums import IndexingOperation

    w = world
    async with w.factory() as db:
        with pytest.raises(TypeError):
            await getattr(IndexingJobService(db), "admit")(USER_A, IndexingOperation.CHUNK)

        def reject():
            raise IndexingAdmissionUnavailable()

        with pytest.raises(IndexingAdmissionUnavailable):
            await IndexingJobService(db).admit(USER_A, IndexingOperation.CHUNK, authorize=reject)
        assert not db.in_transaction()
    assert await job_count(w) == 0


async def test_cancelled_preliminary_probe_uses_registered_request_session(world, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession

    w = world
    r = await runtime(w)
    app = create_app(indexing_test_runtime=r)
    auth = await headers(w)
    entered, closed = asyncio.Event(), asyncio.Event()
    captured = []
    native_close = AsyncSession.close

    async def close(db):
        await native_close(db)
        if captured and db is captured[0]:
            closed.set()

    monkeypatch.setattr(AsyncSession, "close", close)
    async with app.router.lifespan_context(app):
        sup = app.state.indexing_supervisor
        native = sup._probe

        async def probe(**kwargs):
            await native(**kwargs)
            db = kwargs.get("db")
            if db is not None:
                assert sup.admission_count == 1
                assert db.in_transaction()
                captured.append(db)
                entered.set()
                await asyncio.Event().wait()

        monkeypatch.setattr(sup, "_probe", probe)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url=w.settings.frontend_url
        ) as client:
            task = asyncio.create_task(client.post("/api/v1/index/chunk", headers=auth))
            await asyncio.wait_for(entered.wait(), 3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert closed.is_set() and len(captured) == 1
            assert sup.admission_count == 0 and not captured[0].in_transaction()
            assert await job_count(w) == 0
