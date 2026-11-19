"""KI-020: momentary outages are retried inside a bounded window; real damage still closes at once.

Real FastAPI lifespan, real supervisor tasks, real PostgreSQL. Failures are injected at the
exact call sites the supervisor protects, and the recovery clock is a fake so no test sleeps
through a window. Fixed-code diagnostics only: no error text may ever reach logs or health.
"""

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import (
    DBAPIError,
    IntegrityError,
    InterfaceError,
    OperationalError,
    ProgrammingError,
)

from app.db.enums import IndexingJobStatus, IndexingOperation
from app.main import create_app
from app.services.indexing_lifecycle import IndexingSupervisor
from app.services.indexing_runtime import IndexingActivationError, check_database, is_transient
from .test_indexing_lifecycle import request, runtime, settled
from .test_indexing_worker import (
    enqueue,
    job,
    document,
    final_engine,
    keys,
    owner_engine,
    qdrant_client,
    world,
)

__all__ = ["final_engine", "keys", "owner_engine", "qdrant_client", "world"]

SECRET = "synthetic-secret-provider-body"


def hiccup() -> OperationalError:
    return OperationalError("SELECT 1", {}, Exception(SECRET))


class Clock:
    """Fake monotonic clock; tests move time instead of waiting for it."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def until(predicate, seconds=5.0):
    async with asyncio.timeout(seconds):
        while not predicate():
            await asyncio.sleep(0.01)


async def health(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return (await client.get("/api/v1/health/indexing")).json()


# --- classification: what counts as a hiccup ---------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError(),
        ConnectionRefusedError(),
        OSError("network unreachable"),
        hiccup(),
        InterfaceError("SELECT 1", {}, Exception("closed")),
        DBAPIError("SELECT 1", {}, Exception("dropped"), connection_invalidated=True),
        IndexingActivationError("QDRANT_UNAVAILABLE"),
        IndexingActivationError("DATABASE_UNAVAILABLE"),
        IndexingActivationError("SCHEMA_OR_DATABASE_UNAVAILABLE"),
    ],
)
def test_momentary_outages_are_transient(error):
    assert is_transient(error)


@pytest.mark.parametrize(
    "error",
    [
        ProgrammingError("SELECT 1", {}, Exception("relation does not exist")),
        IntegrityError("INSERT", {}, Exception("duplicate")),
        RuntimeError("bug"),
        ValueError("bug"),
        KeyError("bug"),
        AssertionError(),
        IndexingActivationError("SCHEMA_INCOMPATIBLE"),
        IndexingActivationError("CONCRETE_COLLECTION_REQUIRED"),
        IndexingActivationError("VECTOR_CONFIGURATION_INCOMPATIBLE"),
        IndexingActivationError("PAYLOAD_INDEXES_REQUIRED"),
        IndexingActivationError("DATABASE_TARGET_MISMATCH"),
        IndexingActivationError("MAINTENANCE_ACTIVE"),
    ],
)
def test_real_damage_and_unknown_errors_are_never_transient(error):
    assert not is_transient(error)  # unknown must fail closed, never retry


class FailingDb:
    def __init__(self, error):
        self.error = error

    async def execute(self, *_a, **_k):
        raise self.error

    async def close(self):
        return None


@pytest.mark.parametrize(
    "error,code",
    [
        (hiccup(), "SCHEMA_OR_DATABASE_UNAVAILABLE"),
        (TimeoutError(), "SCHEMA_OR_DATABASE_UNAVAILABLE"),
        (
            ProgrammingError("SELECT", {}, Exception("relation does not exist")),
            "SCHEMA_INCOMPATIBLE",
        ),
    ],
)
async def test_dependency_check_separates_an_outage_from_a_broken_schema(error, code):
    from app.core.config import get_settings

    with pytest.raises(IndexingActivationError) as raised:
        await check_database(lambda: FailingDb(error), get_settings(), schema=True)  # type: ignore[arg-type]
    assert raised.value.code == code
    assert SECRET not in str(raised.value) and raised.value.__cause__ is None


# --- worker loop ------------------------------------------------------------------------------


def break_claims(r, monkeypatch, errors):
    """claim_next raises each queued error in turn, then behaves normally."""
    native = r.worker.claim_next
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if errors:
            raise errors.pop(0)
        return await native()

    monkeypatch.setattr(r.worker, "claim_next", flaky)
    return calls


async def test_a_database_hiccup_recovers_and_the_queued_job_still_runs(world, monkeypatch, caplog):
    w = world
    await document(w)
    r = await runtime(w)
    app = create_app(indexing_test_runtime=r)
    calls = break_claims(r, monkeypatch, [hiccup(), hiccup(), hiccup()])
    async with app.router.lifespan_context(app):
        sup = app.state.indexing_supervisor
        jid = await enqueue(w, IndexingOperation.CHUNK)
        await until(lambda: calls["n"] >= 4)  # three failures, then a real claim
        await until(lambda: sup.degraded is None)
        assert sup.healthy and sup.health == "READY"  # never closed
        async with asyncio.timeout(5):
            while (await job(w, jid)).status != IndexingJobStatus.COMPLETED:
                await asyncio.sleep(0.02)  # the job queued during the outage ran
        assert (await health(app)) == {"status": "ready", "admission": "available"}
        assert (await request(app, w)).status_code in (202, 409)  # admission works again
    assert SECRET not in caplog.text  # fixed codes only


async def test_degraded_state_is_visible_while_retrying_and_still_admits_nothing_extra(
    world, monkeypatch
):
    r = await runtime(world)
    app = create_app(indexing_test_runtime=r)
    release = asyncio.Event()
    native = r.worker.claim_next

    async def down():
        if not release.is_set():
            raise hiccup()
        return await native()

    monkeypatch.setattr(r.worker, "claim_next", down)
    async with app.router.lifespan_context(app):
        sup = app.state.indexing_supervisor
        await until(lambda: sup.degraded is not None)
        body = await health(app)
        assert body["status"] == "ready" and body["degraded"] == "DATABASE_UNAVAILABLE"
        assert "reason" not in body  # not failed
        assert SECRET not in str(body)
        release.set()
        await until(lambda: sup.degraded is None)
        assert "degraded" not in await health(app)


async def test_a_persistent_outage_closes_admission_only_after_the_window(world, monkeypatch):
    w = world
    r = await runtime(w)
    app = create_app(indexing_test_runtime=r)
    clock = Clock()
    break_claims(r, monkeypatch, [hiccup() for _ in range(10_000)])
    async with app.router.lifespan_context(app):
        sup = app.state.indexing_supervisor
        sup._clock = clock
        await until(lambda: sup.degraded is not None)
        clock.now += r.outage_tolerance_seconds - 1  # still inside the window
        await asyncio.sleep(0.3)
        assert sup.healthy and sup.failure_reason is None
        clock.now += 2  # window exceeded
        await until(lambda: not sup.healthy)
        assert sup.failure_reason == "DATABASE_UNAVAILABLE" and sup.health == "FAILED"
        assert sup.tasks["worker"].done()
        assert (await request(app, w)).status_code == 503  # the original fail-closed contract


async def test_one_success_resets_the_window(world, monkeypatch):
    r = await runtime(world)
    app = create_app(indexing_test_runtime=r)
    clock = Clock()
    gate = {"fail": True}
    native = r.worker.claim_next
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if gate["fail"]:
            raise hiccup()
        return await native()

    monkeypatch.setattr(r.worker, "claim_next", flaky)
    async with app.router.lifespan_context(app):
        sup = app.state.indexing_supervisor
        sup._clock = clock
        await until(lambda: sup.degraded is not None)
        clock.now += r.outage_tolerance_seconds - 1
        gate["fail"] = False
        await until(lambda: sup.degraded is None)  # success: window forgotten
        gate["fail"] = True
        await until(lambda: sup.degraded is not None)
        clock.now += r.outage_tolerance_seconds - 1  # 2x the window since the first failure
        await asyncio.sleep(0.3)
        assert (
            sup.healthy and sup.failure_reason is None
        )  # but only < window since the latest streak
        gate["fail"] = False


@pytest.mark.parametrize(
    "error",
    [
        ProgrammingError("SELECT", {}, Exception(SECRET)),
        IntegrityError("INSERT", {}, Exception(SECRET)),
        RuntimeError(SECRET),
        ValueError(SECRET),
    ],
)
async def test_real_damage_in_the_worker_loop_still_closes_immediately(
    world, monkeypatch, caplog, error
):
    w = world
    r = await runtime(w)
    app = create_app(indexing_test_runtime=r)
    calls = break_claims(r, monkeypatch, [error])
    async with app.router.lifespan_context(app):
        sup = app.state.indexing_supervisor
        await until(lambda: not sup.healthy)
        assert calls["n"] == 1  # no retry
        assert sup.degraded is None and sup.tasks["worker"].done()
        assert sup.failure_reason == "EXECUTOR_TASK_FAILED"  # fixed code; never the error text
        assert (await health(app))["reason"] == "EXECUTOR_TASK_FAILED"
        assert (await request(app, w)).status_code == 503
    assert SECRET not in caplog.text


async def test_a_failure_while_executing_a_stage_is_never_retried(world, monkeypatch):
    w = world
    await document(w)
    r = await runtime(w)
    app = create_app(indexing_test_runtime=r)
    executed = {"n": 0}

    async def broken(_claim):
        executed["n"] += 1
        raise hiccup()  # looks transient, but a stage is in flight

    monkeypatch.setattr(r.worker, "execute", broken)
    async with app.router.lifespan_context(app):
        sup = app.state.indexing_supervisor
        await enqueue(w, IndexingOperation.CHUNK)
        await until(lambda: not sup.healthy)
        assert executed["n"] == 1 and sup.degraded is None
        assert sup.tasks["worker"].done()


# --- classifier loop --------------------------------------------------------------------------


async def test_the_classifier_survives_a_hiccup_and_closes_on_real_damage(world, monkeypatch):
    r = await runtime(world)
    app = create_app(indexing_test_runtime=r)
    original = IndexingSupervisor._classification_round
    state = {"n": 0, "mode": "hiccup"}

    async def round_(self):
        state["n"] += 1
        if state["n"] > 1 and state["mode"] == "hiccup" and state["n"] <= 4:
            raise hiccup()
        if state["mode"] == "damage" and state["n"] > 1:
            raise RuntimeError(SECRET)
        await original(self)

    monkeypatch.setattr(IndexingSupervisor, "_classification_round", round_)
    async with app.router.lifespan_context(app):
        sup = app.state.indexing_supervisor
        await until(lambda: state["n"] >= 6)  # three failures then clean rounds
        assert sup.healthy and sup.degraded is None
        state["mode"] = "damage"
        await until(lambda: not sup.healthy)
        assert sup.tasks["classifier"].done()


# --- admission --------------------------------------------------------------------------------


async def test_a_momentary_admission_probe_failure_refuses_one_request_without_closing(
    world, monkeypatch
):
    w = world
    r = await runtime(w)
    app = create_app(indexing_test_runtime=r)
    async with app.router.lifespan_context(app):
        sup = app.state.indexing_supervisor
        native = sup._probe
        fail = {"on": True}

        async def probe(*a, **k):
            if fail["on"]:
                raise hiccup()
            return await native(*a, **k)

        monkeypatch.setattr(sup, "_probe", probe)
        assert (await request(app, w)).status_code == 503  # this request is refused...
        assert sup.healthy and sup.failure_reason is None  # ...but the door stays open
        fail["on"] = False
        assert (await request(app, w)).status_code == 202  # and the next one is accepted


async def test_a_broken_schema_at_admission_still_closes_immediately(world, monkeypatch):
    w = world
    r = await runtime(w)
    app = create_app(indexing_test_runtime=r)
    async with app.router.lifespan_context(app):
        sup = app.state.indexing_supervisor

        async def probe(*_a, **_k):
            raise ProgrammingError("SELECT", {}, Exception("relation does not exist"))

        monkeypatch.setattr(sup, "_probe", probe)
        assert not await sup.authorize_admission()
        assert not sup.healthy and sup.failure_reason == "DATABASE_UNAVAILABLE"


# --- shutdown ---------------------------------------------------------------------------------


async def test_shutdown_during_a_retry_is_prompt_and_clean(world, monkeypatch):
    r = await runtime(world)
    app = create_app(indexing_test_runtime=r)
    calls = break_claims(r, monkeypatch, [hiccup() for _ in range(10_000)])
    context = app.router.lifespan_context(app)
    await context.__aenter__()
    sup = app.state.indexing_supervisor
    await until(lambda: sup.degraded is not None and calls["n"] >= 2)
    await settled(asyncio.create_task(context.__aexit__(None, None, None)))
    assert sup.health == "STOPPED" and all(t.done() for t in sup.tasks.values())
    assert sup.failure_reason is None  # a clean stop, not a failure
    assert app.state.indexing_disposal_task.done()


def test_recovery_window_is_bounded():
    from app.core.config import Settings

    with pytest.raises(ValueError):
        Settings(indexing_outage_tolerance_seconds=0)
    with pytest.raises(ValueError):
        Settings(indexing_outage_tolerance_seconds=10_000)
    assert Settings().indexing_outage_tolerance_seconds == 30.0
