"""Real lifespan/pooled PostgreSQL regressions. No real provider or credentials."""

import asyncio
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.connectors.google_drive.client import DriveClientError
from app.core.config import Settings
from app.main import create_app
from app.services.google_credential_repository import GoogleCredentialRepository
from app.services.google_credential_service import GoogleCredentialService, GoogleRefreshLifecycle
from .conftest import USER_A
from .test_encrypted_only_credentials import FakeResponse, final_engine, grant, keys

__all__ = ["final_engine", "keys"]


@dataclass
class Runtime:
    app: FastAPI
    engine: AsyncEngine
    factory: async_sessionmaker
    lifecycle: GoogleRefreshLifecycle
    settings: Settings
    observer_factory: async_sessionmaker

    async def client(self):
        async with self.factory() as db:
            service = GoogleCredentialService(db, self.settings)
            return service, service.client(await service.load(USER_A))

    async def record(self):
        async with self.factory() as db:
            return await GoogleCredentialRepository(db, self.settings).load_record(USER_A)


@pytest.fixture
async def runtime(final_engine, keys):
    async with final_engine.connect() as connection:
        schema = await connection.scalar(text("SELECT current_schema()"))
    engine = create_async_engine(
        final_engine.url,
        hide_parameters=True,
        connect_args={"server_settings": {"search_path": schema}},
    )
    lifecycle = GoogleRefreshLifecycle(waiting_budget=1, shutdown_grace=0.1, callback_timeout=1)
    factory = async_sessionmaker(
        engine, expire_on_commit=False, info={"google_refresh_lifecycle": lifecycle}
    )
    app = create_app()
    app.state.google_refresh_lifecycle = lifecycle
    resource = Runtime(
        app,
        engine,
        factory,
        lifecycle,
        keys,
        async_sessionmaker(final_engine, expire_on_commit=False),
    )
    with (
        patch("app.main.engine", engine),
        patch("app.main.SessionLocal", factory),
        patch("app.main.get_settings", return_value=keys),
    ):
        try:
            yield resource
        finally:
            await lifecycle.shutdown()
            await engine.dispose()


class Network:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        self.started.set()
        assert self.release.wait(5)
        return FakeResponse()


async def started(network):
    assert await asyncio.to_thread(network.started.wait, 5)


@pytest.mark.asyncio
async def test_real_lifespan_no_late_connection_after_disposal(runtime):
    await grant(runtime.factory, runtime.settings)
    network = Network()
    connections = []
    event.listen(runtime.engine.sync_engine, "connect", lambda *args: connections.append(1))
    with patch("app.services.google_credential_service.Request", return_value=network):
        async with runtime.app.router.lifespan_context(runtime.app):
            service, client = await runtime.client()
            task = asyncio.create_task(asyncio.to_thread(client._ensure_credentials))
            await started(network)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert runtime.lifecycle.active_workers == 1
            workers = list(runtime.lifecycle._workers)
        count = len(connections)
        try:
            # The provider thread survives grace; no callback may now touch SQL.
            network.release.set()
            with pytest.raises(DriveClientError):
                await asyncio.wrap_future(workers[0])
            assert len(connections) == count
            assert runtime.engine.pool.checkedin() == 0
            assert runtime.lifecycle.active_callbacks == 0
            assert runtime.lifecycle.active_workers == 0
            with pytest.raises(DriveClientError):
                await asyncio.to_thread(service._on_loop, service.load(USER_A))
            assert len(connections) == count
            await runtime.lifecycle.shutdown()
        finally:
            network.release.set()
    # Read through a separate fixture engine, not the disposed application engine.
    async with runtime.observer_factory() as db:
        record = await GoogleCredentialRepository(db, runtime.settings).load_record(USER_A)
        assert record.credential_revision == 1 and record.refresh_claim_state == "SUBMITTED"


@pytest.mark.asyncio
async def test_shutdown_drains_matching_result_and_removes_worker(runtime):
    await grant(runtime.factory, runtime.settings)
    network = Network()
    runtime.lifecycle.shutdown_grace = 2
    with patch("app.services.google_credential_service.Request", return_value=network):
        async with runtime.app.router.lifespan_context(runtime.app):
            _, client = await runtime.client()
            task = asyncio.create_task(asyncio.to_thread(client._ensure_credentials))
            await started(network)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            network.release.set()
        assert runtime.lifecycle.active_workers == 0
        assert runtime.lifecycle.active_callbacks == 0
    async with runtime.observer_factory() as db:
        record = await GoogleCredentialRepository(db, runtime.settings).load_record(USER_A)
        assert record.credential_revision == 2 and record.refresh_claim_id is None


@pytest.mark.asyncio
async def test_shutdown_cancels_and_rolls_back_admitted_database_callback(runtime):
    await grant(runtime.factory, runtime.settings)
    entered, release = asyncio.Event(), asyncio.Event()
    original = GoogleCredentialRepository._claimed
    rollbacks = []
    event.listen(runtime.engine.sync_engine, "rollback", lambda *args: rollbacks.append(1))

    async def blocked(repository, claim):
        row = await original(repository, claim)  # Real SQL row lock acquired.
        entered.set()
        await release.wait()
        return row

    # Only completion is blocked; submit uses the same helper beforehand.
    async with runtime.app.router.lifespan_context(runtime.app):
        service, client = await runtime.client()
        original_complete = service._complete

        async def completion(claim, credentials):
            with patch.object(GoogleCredentialRepository, "_claimed", blocked):
                return await original_complete(claim, credentials)

        with (
            patch.object(service, "_complete", completion),
            patch(
                "app.services.google_credential_service.Request",
                return_value=lambda **kw: FakeResponse(),
            ),
        ):
            task = asyncio.create_task(asyncio.to_thread(client._ensure_credentials))
            await asyncio.wait_for(entered.wait(), 5)
            before = len(rollbacks)
            await runtime.lifecycle.shutdown()
            assert len(rollbacks) > before
            assert runtime.lifecycle.active_callbacks == 0
            with pytest.raises(DriveClientError):
                await asyncio.wait_for(task, 3)
            release.set()
    assert runtime.engine.pool.checkedin() == 0


@pytest.mark.asyncio
async def test_shutdown_during_prepared_does_not_submit_provider(runtime):
    await grant(runtime.factory, runtime.settings)
    entered, release = asyncio.Event(), asyncio.Event()
    async with runtime.app.router.lifespan_context(runtime.app):
        service, client = await runtime.client()
        original_submit = service._submit

        async def paused(claim):
            entered.set()
            await release.wait()
            await original_submit(claim)

        with (
            patch.object(service, "_submit", paused),
            patch("app.services.google_credential_service.Request") as provider,
        ):
            task = asyncio.create_task(asyncio.to_thread(client._ensure_credentials))
            await asyncio.wait_for(entered.wait(), 5)
            await runtime.lifecycle.shutdown()
            with pytest.raises(DriveClientError):
                await asyncio.wait_for(task, 3)
            # Request object construction is permitted; submitting HTTP is not.
            provider.return_value.assert_not_called()
    async with runtime.observer_factory() as db:
        record = await GoogleCredentialRepository(db, runtime.settings).load_record(USER_A)
        assert record.refresh_claim_state == "PREPARED"


@pytest.mark.asyncio
async def test_empty_repeated_shutdown_and_reject_new_work(runtime):
    async with runtime.app.router.lifespan_context(runtime.app):
        await runtime.lifecycle.shutdown()
        await runtime.lifecycle.shutdown()
        invoked = threading.Event()
        with pytest.raises(DriveClientError):
            await asyncio.to_thread(runtime.lifecycle.run, invoked.set)
        assert not invoked.is_set()
    assert runtime.engine.pool.checkedin() == 0


@pytest.mark.asyncio
async def test_caller_budget_retains_worker_and_late_rotation(runtime):
    await grant(runtime.factory, runtime.settings)
    network = Network()
    runtime.lifecycle.waiting_budget = 0.1
    with patch("app.services.google_credential_service.Request", return_value=network):
        async with runtime.app.router.lifespan_context(runtime.app):
            _, client = await runtime.client()
            task = asyncio.create_task(asyncio.to_thread(client._ensure_credentials))
            await started(network)
            try:
                with pytest.raises(DriveClientError) as caught:
                    await asyncio.wait_for(task, 2)
                assert caught.value.category == "temporary_provider_failure"
                assert runtime.lifecycle.active_workers == 1
                _, second = await runtime.client()
                with pytest.raises(DriveClientError):
                    await asyncio.to_thread(second._ensure_credentials)
                assert network.calls == 1  # The uncertain token is not sent again.
                workers = list(runtime.lifecycle._workers)
                network.release.set()
                await asyncio.gather(*(asyncio.wrap_future(worker) for worker in workers))
                assert runtime.lifecycle.active_workers == 0
                assert (await runtime.record()).credential_revision == 2
                assert network.calls == 1
            finally:
                network.release.set()


@pytest.mark.asyncio
async def test_slow_trickling_real_requests_transport_exceeds_caller_budget(runtime):
    from google.auth.transport.requests import Request

    await grant(runtime.factory, runtime.settings)
    entered = threading.Event()
    release = threading.Event()
    payload = FakeResponse().data

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_POST(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload[:1])
            self.wfile.flush()
            entered.set()
            # Repeated bytes below the real ten-second read inactivity timeout.
            for offset in range(1, len(payload)):
                if release.wait(0.02):
                    self.wfile.write(payload[offset:])
                    self.wfile.flush()
                    return
                self.wfile.write(payload[offset : offset + 1])
                self.wfile.flush()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    transport = Request()

    def local_request(*args, **kwargs):
        kwargs["url"] = f"http://127.0.0.1:{server.server_port}/token"
        return transport(*args, **kwargs)

    runtime.lifecycle.waiting_budget = 0.3
    try:
        with patch("app.services.google_credential_service.Request", return_value=local_request):
            async with runtime.app.router.lifespan_context(runtime.app):
                _, client = await runtime.client()
                begin = time.monotonic()
                task = asyncio.create_task(asyncio.to_thread(client._ensure_credentials))
                assert await asyncio.to_thread(entered.wait, 5)
                with pytest.raises(DriveClientError) as caught:
                    await asyncio.wait_for(task, 2)
                assert time.monotonic() - begin < 2
                assert caught.value.category == "temporary_provider_failure"
                assert runtime.lifecycle.active_workers == 1
                worker = next(iter(runtime.lifecycle._workers))
                release.set()
                await asyncio.wrap_future(worker)
                assert (await runtime.record()).credential_revision == 2
    finally:
        release.set()
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        transport.session.close()


@pytest.mark.asyncio
async def test_closed_loop_rejects_callback_without_scheduling():
    lifecycle = GoogleRefreshLifecycle()
    loop = asyncio.new_event_loop()
    lifecycle.bind(loop)
    loop.close()

    async def must_not_run():
        raise AssertionError("closed loop callback ran")

    with pytest.raises(DriveClientError):
        await asyncio.to_thread(lifecycle.call, must_not_run())
    assert lifecycle.active_callbacks == 0
    await lifecycle.shutdown()


@pytest.mark.asyncio
async def test_event_loop_thread_cannot_deadlock_itself():
    lifecycle = GoogleRefreshLifecycle()
    lifecycle.bind(asyncio.get_running_loop())
    with pytest.raises(DriveClientError):
        lifecycle.run(lambda: None)

    async def noop():
        return None

    with pytest.raises(DriveClientError):
        lifecycle.call(noop())
    await lifecycle.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup_failure", [False, True])
async def test_late_sql_cleanup_automatically_disposes_original_pool(
    runtime, cleanup_failure, caplog
):
    await grant(runtime.factory, runtime.settings)
    entered, cleanup, finish_cleanup = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original = GoogleCredentialRepository._claimed

    async def delayed_cleanup(repository, claim):
        row = await original(repository, claim)
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cleanup.set()
            await finish_cleanup.wait()
            if cleanup_failure:
                raise RuntimeError("synthetic-secret-cleanup") from None
            raise
        return row

    context = runtime.app.router.lifespan_context(runtime.app)
    await context.__aenter__()
    service, client = await runtime.client()
    original_complete = service._complete

    async def completion(claim, credentials):
        with patch.object(GoogleCredentialRepository, "_claimed", delayed_cleanup):
            return await original_complete(claim, credentials)

    disposed = []
    original_pool = runtime.engine.pool
    original_dispose = AsyncEngine.dispose

    async def tracked_dispose(engine, *args, **kwargs):
        assert engine.pool.checkedout() == 0
        disposed.append(engine)
        await original_dispose(engine, *args, **kwargs)

    with (
        patch.object(service, "_complete", completion),
        patch(
            "app.services.google_credential_service.Request",
            return_value=lambda **kw: FakeResponse(),
        ),
        patch.object(AsyncEngine, "dispose", tracked_dispose),
    ):
        task = asyncio.create_task(asyncio.to_thread(client._ensure_credentials))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            with pytest.raises(DriveClientError, match="shutdown cleanup"):
                await context.__aexit__(None, None, None)
            assert cleanup.is_set()
            assert runtime.engine not in disposed
            assert runtime.lifecycle.active_callbacks == 1
        finally:
            callbacks = [
                ticket.task for ticket in runtime.lifecycle._callbacks if ticket.task is not None
            ]
            finish_cleanup.set()
            if callbacks:
                await asyncio.wait(callbacks)
        # Observe automatic finalization; never invoke a second shutdown to start it.
        finalizer = runtime.lifecycle._disposal_task
        assert finalizer is not None
        await asyncio.wait_for(asyncio.shield(finalizer), 3)
        assert disposed == [runtime.engine]
        assert original_pool.checkedin() == 0
        assert original_pool.checkedout() == 0
        with pytest.raises(DriveClientError):
            await asyncio.wait_for(task, 3)
        assert runtime.lifecycle.active_callbacks == 0
        # No callback may reopen SQL after automatic final disposal.
        with pytest.raises(DriveClientError):
            await asyncio.to_thread(service._on_loop, service.load(USER_A))
        await runtime.lifecycle.shutdown_and_dispose(runtime.engine.dispose)
        await runtime.lifecycle.shutdown_and_dispose(runtime.engine.dispose)
        assert disposed == [runtime.engine]
        assert "synthetic-secret-cleanup" not in caplog.text
        if cleanup_failure:
            assert "SQL callback failed during final cleanup" in caplog.text
    async with runtime.observer_factory() as db:
        record = await GoogleCredentialRepository(db, runtime.settings).load_record(USER_A)
        assert record.credential_revision == 1 and record.refresh_claim_state == "SUBMITTED"


@pytest.mark.asyncio
async def test_connection_timeout_is_safe_uncertain_single_attempt(runtime, caplog):
    from google.auth.transport.requests import Request
    from requests.exceptions import ConnectTimeout

    await grant(runtime.factory, runtime.settings)
    transport = Request()
    try:
        with (
            patch.object(
                transport.session,
                "request",
                side_effect=ConnectTimeout("synthetic-secret-provider"),
            ) as send,
            patch("app.services.google_credential_service.Request", return_value=transport),
        ):
            async with runtime.app.router.lifespan_context(runtime.app):
                _, client = await runtime.client()
                with pytest.raises(DriveClientError) as caught:
                    await asyncio.to_thread(client._ensure_credentials)
                assert "synthetic-secret-provider" not in str(caught.value)
                assert "synthetic-secret-provider" not in caplog.text
                assert caught.value.category == "temporary_provider_failure"
                assert (await runtime.record()).grant_status == "RECOVERY_REQUIRED"
                send.assert_called_once()
                assert send.call_args.kwargs["timeout"] == (5, 10)
    finally:
        transport.session.close()


@pytest.mark.asyncio
async def test_real_read_inactivity_timeout_keeps_submitted_claim(runtime):
    from google.auth.transport.requests import Request

    await grant(runtime.factory, runtime.settings)
    entered, release = threading.Event(), threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_POST(self):
            self.send_response(200)
            self.send_header("Content-Length", "100")
            self.end_headers()
            self.wfile.flush()
            entered.set()
            release.wait(5)  # Real inactivity, with no body delivered.

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    transport = Request()

    def local_request(*args, **kwargs):
        kwargs["url"] = f"http://127.0.0.1:{server.server_port}/token"
        kwargs["timeout"] = (
            0.2,
            0.1,
        )  # Accelerate the actual Requests inactivity timeout in tests.
        return transport(*args, **kwargs)

    try:
        with patch("app.services.google_credential_service.Request", return_value=local_request):
            async with runtime.app.router.lifespan_context(runtime.app):
                _, client = await runtime.client()
                with pytest.raises(DriveClientError) as caught:
                    await asyncio.wait_for(asyncio.to_thread(client._ensure_credentials), 3)
                assert entered.is_set()
                assert caught.value.category == "temporary_provider_failure"
                record = await runtime.record()
                assert record.grant_status == "RECOVERY_REQUIRED"
                assert record.refresh_claim_state == "SUBMITTED"
    finally:
        release.set()
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        transport.session.close()


@pytest.mark.asyncio
async def test_worker_capacity_rejects_untracked_work(runtime):
    runtime.lifecycle.max_workers = 1
    runtime.lifecycle.bind(asyncio.get_running_loop())
    entered, release = threading.Event(), threading.Event()

    def blocked():
        entered.set()
        assert release.wait(5)

    task = asyncio.create_task(asyncio.to_thread(runtime.lifecycle.run, blocked))
    assert await asyncio.to_thread(entered.wait, 5)
    try:
        with pytest.raises(DriveClientError):
            await asyncio.to_thread(runtime.lifecycle.run, lambda: None)
        assert runtime.lifecycle.active_workers == 1
    finally:
        release.set()
        await task
    await runtime.lifecycle.shutdown()
    assert runtime.lifecycle.active_workers == 0


@pytest.mark.asyncio
async def test_separate_runtime_loops_cannot_share_lifecycle():
    lifecycle = GoogleRefreshLifecycle()
    lifecycle.bind(asyncio.get_running_loop())
    other = asyncio.new_event_loop()
    try:
        with pytest.raises(DriveClientError):
            lifecycle.bind(other)
    finally:
        other.close()
        await lifecycle.shutdown()


@pytest.mark.asyncio
async def test_shutdown_rejects_new_refresh_during_grace(runtime):
    await grant(runtime.factory, runtime.settings)
    network = Network()
    runtime.lifecycle.shutdown_grace = 2
    with patch("app.services.google_credential_service.Request", return_value=network):
        async with runtime.app.router.lifespan_context(runtime.app):
            _, client = await runtime.client()
            task = asyncio.create_task(asyncio.to_thread(client._ensure_credentials))
            await started(network)
            shutdown = asyncio.create_task(runtime.lifecycle.shutdown())
            await asyncio.sleep(
                0
            )  # One loop turn: shutdown marks admission closed before its first wait.
            assert runtime.lifecycle._closing
            try:
                with pytest.raises(DriveClientError):
                    await asyncio.to_thread(runtime.lifecycle.run, lambda: None)
            finally:
                network.release.set()
            await shutdown
            await task
            assert runtime.lifecycle.active_workers == 0


@pytest.mark.asyncio
async def test_queued_callback_admission_race_is_sealed_before_disposal(runtime):
    runtime.lifecycle.bind(asyncio.get_running_loop())
    admitted, finished = threading.Event(), threading.Event()
    connections, outcomes = [], []
    event.listen(runtime.engine.sync_engine, "connect", lambda *args: connections.append(1))
    original = asyncio.run_coroutine_threadsafe

    def schedule(coroutine, loop):
        future = original(coroutine, loop)
        admitted.set()
        return future

    async def operation():
        async with runtime.factory() as db:
            await db.execute(text("SELECT 1"))

    def callback():
        try:
            runtime.lifecycle.call(operation())
        except DriveClientError:
            outcomes.append("rejected")
        finally:
            finished.set()

    async with runtime.app.router.lifespan_context(runtime.app):
        baseline = len(connections)  # Normal startup job cleanup legitimately opens SQL.
        with patch("asyncio.run_coroutine_threadsafe", schedule):
            thread = threading.Thread(target=callback, daemon=True)
            thread.start()
            # Briefly hold this loop so the admitted wrapper cannot begin SQL yet.
            assert admitted.wait(2)
            assert runtime.lifecycle.active_callbacks == 1
            await runtime.lifecycle.shutdown()
    assert await asyncio.to_thread(finished.wait, 2)
    assert outcomes == ["rejected"]
    assert len(connections) == baseline
    assert runtime.engine.pool.checkedin() == 0
    assert runtime.lifecycle.active_callbacks == 0


@pytest.mark.asyncio
async def test_submitted_refresh_cannot_resurrect_disconnected_row(runtime):
    from sqlalchemy import delete
    from app.db.models.google_oauth_token import GoogleOAuthToken

    await grant(runtime.factory, runtime.settings)
    network = Network()
    with patch("app.services.google_credential_service.Request", return_value=network):
        async with runtime.app.router.lifespan_context(runtime.app):
            _, client = await runtime.client()
            task = asyncio.create_task(asyncio.to_thread(client._ensure_credentials))
            await started(network)
            try:
                async with runtime.factory() as db:
                    await db.execute(
                        delete(GoogleOAuthToken).where(GoogleOAuthToken.user_id == USER_A)
                    )
                    await db.commit()
                network.release.set()
                with pytest.raises(DriveClientError):
                    await asyncio.wait_for(task, 3)
                async with runtime.factory() as db:
                    assert await db.scalar(text("SELECT count(*) FROM google_oauth_tokens")) == 0
            finally:
                network.release.set()


@pytest.mark.asyncio
async def test_concurrent_finalization_disposes_once_after_normal_lifespan(runtime):
    original_pool = runtime.engine.pool
    disposed = []
    original = AsyncEngine.dispose

    async def dispose(engine, *args, **kwargs):
        assert engine.pool.checkedout() == 0
        disposed.append(engine)
        await original(engine, *args, **kwargs)

    with patch.object(AsyncEngine, "dispose", dispose):
        async with runtime.app.router.lifespan_context(runtime.app):
            async with runtime.factory() as db:
                await db.execute(text("SELECT 1"))
        await asyncio.gather(
            runtime.lifecycle.shutdown_and_dispose(runtime.engine.dispose),
            runtime.lifecycle.shutdown_and_dispose(runtime.engine.dispose),
        )
        assert disposed == [runtime.engine]
        assert original_pool.checkedin() == original_pool.checkedout() == 0


@pytest.mark.asyncio
async def test_disposal_failure_is_observed_and_not_retried(runtime, caplog):
    attempts = []

    async def failing_dispose():
        attempts.append(1)
        raise RuntimeError("synthetic-secret-disposal")

    for _ in range(2):
        with pytest.raises(DriveClientError, match="database disposal failed") as caught:
            await runtime.lifecycle.shutdown_and_dispose(failing_dispose)
        assert "synthetic-secret-disposal" not in str(caught.value)
        assert caught.value.__context__ is None
    assert attempts == [1]
    assert "final disposal failed" in caplog.text
    assert "synthetic-secret-disposal" not in caplog.text


@pytest.mark.asyncio
async def test_cancelled_finalization_waiter_does_not_cancel_owned_disposal(runtime):
    entered, release = asyncio.Event(), asyncio.Event()
    original_pool = runtime.engine.pool
    attempts = []
    async with runtime.factory() as db:
        await db.execute(text("SELECT 1"))

    async def dispose():
        attempts.append(1)
        entered.set()
        await release.wait()
        assert runtime.engine.pool.checkedout() == 0
        await runtime.engine.dispose()

    waiter = asyncio.create_task(runtime.lifecycle.shutdown_and_dispose(dispose))
    await asyncio.wait_for(entered.wait(), 3)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    finalizer = runtime.lifecycle._disposal_task
    assert finalizer is not None and not finalizer.done()
    release.set()
    await asyncio.wait_for(asyncio.shield(finalizer), 3)
    await runtime.lifecycle.shutdown_and_dispose(dispose)
    assert attempts == [1]
    assert original_pool.checkedin() == original_pool.checkedout() == 0
