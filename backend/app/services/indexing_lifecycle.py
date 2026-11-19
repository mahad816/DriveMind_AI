"""Owned indexing loops for disposable tests and explicitly bound normal runtimes."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from typing import Literal

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db.enums import IndexingJobStatus
from app.db.models.indexing_job import IndexingJob
from app.db.models.user import User
from app.services.google_credential_service import GoogleRefreshLifecycle
from app.services.indexing_classifier import IndexingClassifier
from app.services.indexing_job_service import IndexingAdmissionUnavailable
from app.services.indexing_runtime import (
    NormalIndexingRuntime,
    IndexingActivationError,
    check_collection,
    is_transient,
)
from app.services.indexing_worker import IndexingWorker, StageProgress

logger = logging.getLogger(__name__)
Health = Literal["INACTIVE", "STARTING", "READY", "FAILED", "STOPPING", "STOPPED"]


@dataclass(frozen=True)
class DisposableIndexingRuntime:
    """Code-only test injection; never selected by environment or HTTP input.

    Only explicitly disposable loopback PostgreSQL and Qdrant targets are accepted.
    The injected worker owns its sessions; the application owns their engine teardown.
    """

    worker: IndexingWorker
    refresh: GoogleRefreshLifecycle
    poll_seconds: float = 1.0
    classifier_seconds: float = 5.0
    database_timeout: float = 10.0
    startup_timeout: float = 15.0
    drain_seconds: float = 20.0
    cleanup_seconds: float = 5.0
    classification_batch: int = 50
    outage_tolerance_seconds: float = 30.0

    def __post_init__(self) -> None:
        from urllib.parse import urlsplit

        engine = self.engine
        url = engine.url
        qdrant = urlsplit(self.worker.settings.qdrant_url)
        if (
            self.worker.settings.demo_mode
            or url.drivername != "postgresql+asyncpg"
            or url.host not in {"localhost", "127.0.0.1", "::1"}
            or not (url.database or "").startswith("drivemind_session_test")
            or url.port is None
            or url.query
            or qdrant.scheme != "http"
            or qdrant.hostname not in {"localhost", "127.0.0.1", "::1"}
            or qdrant.port in {None, 6333, 6334}
            or qdrant.username is not None
            or qdrant.path not in {"", "/"}
            or qdrant.query
            or qdrant.fragment
            or not self.worker.settings.qdrant_collection.startswith("drivemind_4e")
        ):
            raise ValueError("Indexing test activation requires explicit disposable targets")
        if (
            self.worker.sessions.kw.get("info", {}).get("google_refresh_lifecycle")
            is not self.refresh
        ):
            raise ValueError("Indexing sessions must use the owned credential lifecycle")
        for value in (
            self.poll_seconds,
            self.classifier_seconds,
            self.database_timeout,
            self.startup_timeout,
            self.drain_seconds,
            self.cleanup_seconds,
        ):
            if not math.isfinite(value) or not 0.01 <= value <= 60:
                raise ValueError("Indexing lifecycle intervals must be bounded")
        if (
            not math.isfinite(self.outage_tolerance_seconds)
            or not 0.01 <= self.outage_tolerance_seconds <= 300
        ):
            raise ValueError("Indexing recovery window must be bounded")
        if not 1 <= self.classification_batch <= 100:
            raise ValueError("Indexing classification batch must be bounded")

    @property
    def engine(self) -> AsyncEngine:
        engine = self.worker.sessions.kw.get("bind")
        if not isinstance(engine, AsyncEngine):
            raise ValueError("Indexing lifecycle requires an owned asynchronous engine")
        return engine


class AdmissionPermit:
    """One request-owned grant, atomically ordered with local lifecycle closure."""

    def __init__(self, supervisor: IndexingSupervisor, task: asyncio.Task[object]) -> None:
        self.supervisor = supervisor
        self.task = task
        self.authorized = False
        self.cleanup: asyncio.Task[None] | None = None
        self.cancel_requested = False

    def authorize(self) -> None:
        # These synchronous operations contain no await: failure/shutdown and
        # permit authorization are totally ordered on the application event loop.
        # Task.done observes death even before its supervision callback runs.
        if (
            self not in self.supervisor._admissions
            or asyncio.current_task() is not self.task
            or self.task.cancelling()
            or self.authorized
            or not self.supervisor.healthy
        ):
            raise IndexingAdmissionUnavailable()
        self.authorized = True


class IndexingSupervisor:
    def __init__(self, runtime: DisposableIndexingRuntime | NormalIndexingRuntime) -> None:
        self.runtime = runtime
        self.worker = runtime.worker
        self.classifier = IndexingClassifier(self.worker)
        self.state: Health = "INACTIVE"
        self.failure_reason: str | None = None
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.stop = asyncio.Event()
        self._go = asyncio.Event()
        self._worker_ready = asyncio.Event()
        self._classifier_ready = asyncio.Event()
        self._shutdown_task: asyncio.Task[None] | None = None
        self._admissions: set[AdmissionPermit] = set()
        self._admissions_idle = asyncio.Event()
        self._admissions_idle.set()
        # source -> (monotonic time of first failure, consecutive failures, fixed nonsecret code)
        self._outages: dict[str, tuple[float, int, str]] = {}
        self._clock: Callable[[], float] = time.monotonic

    @property
    def degraded(self) -> str | None:
        """Fixed nonsecret code while a dependency is failing but still inside its recovery window."""
        return next((code for _, _, code in self._outages.values()), None)

    def _tolerate(self, source: str, error: BaseException, *, code: str | None = None) -> bool:
        """Decide whether ``error`` may be retried. False means: close the door as before.

        Only momentary outages (timeouts, dropped connections, brief Qdrant loss) are retried,
        and only until ``outage_tolerance_seconds`` have passed since this source *started* failing
        continuously. Real damage, unknown errors and shutdown never retry. No error text is
        stored or logged: only a fixed code.
        """
        if self.stop.is_set() or not is_transient(error):
            return False
        now = self._clock()
        since, attempts, _ = self._outages.get(source, (now, 0, ""))
        fixed = error.code if isinstance(error, IndexingActivationError) else "DATABASE_UNAVAILABLE"
        if now - since >= self.runtime.outage_tolerance_seconds:
            self._outages.pop(source, None)
            self.failure_reason = code or fixed
            return False
        self._outages[source] = (since, attempts + 1, fixed)
        if attempts == 0:
            logger.warning(
                "Indexing %s is degraded (%s); retrying within its recovery window.", source, fixed
            )
        return True

    def _recovered(self, source: str) -> None:
        if self._outages.pop(source, None) is not None:
            logger.info("Indexing %s recovered.", source)

    def _backoff(self, source: str) -> float:
        attempts = self._outages[source][1]
        return min(self.runtime.poll_seconds * float(2 ** (attempts - 1)), 10.0)

    @property
    def healthy(self) -> bool:
        # Task.done is checked synchronously: no callback scheduling window can
        # leave an already-dead executor eligible for a new admission.
        return (
            self.state == "READY"
            and not self.stop.is_set()
            and len(self.tasks) == (3 if isinstance(self.runtime, NormalIndexingRuntime) else 2)
            and all(not task.done() for task in self.tasks.values())
        )

    @property
    def health(self) -> Health:
        return "FAILED" if self.state == "READY" and not self.healthy else self.state

    def _fail(self) -> None:
        if self.state not in {"STOPPING", "STOPPED"}:
            self.state = "FAILED"
            self.stop.set()
            self._go.set()
            logger.error("Indexing executor is unavailable; local admission is closed.")

    def _observed(self, task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            error = task.exception()  # Observe without logging sensitive exception details.
            if isinstance(error, IndexingActivationError):
                self.failure_reason = error.code
            elif error is not None and self.failure_reason is None:
                # Always leave a fixed diagnostic (never error text). A specific activation code
                # from a sibling task still replaces it, so the answer does not depend on which
                # loop notices the same outage first.
                self.failure_reason = "EXECUTOR_TASK_FAILED"
        if not self.stop.is_set():
            self._fail()

    async def _probe(self, *, schema: bool = False, db: AsyncSession | None = None) -> None:
        async with asyncio.timeout(self.runtime.database_timeout):
            if db is not None:
                if schema:
                    raise ValueError("Startup schema checks require their own session")
                # HTTP probes share the permit-owned session. Repeated request
                # cancellation cannot detach a second untracked session-close task.
                await db.execute(select(IndexingJob.id).limit(1))
                return
            async with self.worker.sessions() as db:
                if schema:
                    # Explicitly select every accepted job field. A missing column
                    # must fail before either loop is allowed to execute stages.
                    await db.execute(select(IndexingJob).limit(0))
                    valid = await db.scalar(
                        text(
                            "SELECT EXISTS (SELECT 1 FROM pg_indexes p "
                            "JOIN pg_class c ON c.relname=p.indexname "
                            "JOIN pg_namespace n ON n.oid=c.relnamespace AND n.nspname=p.schemaname "
                            "JOIN pg_index i ON i.indexrelid=c.oid "
                            "WHERE p.schemaname=current_schema() AND p.tablename='indexing_jobs' "
                            "AND p.indexname='uq_indexing_jobs_unresolved_owner' "
                            "AND i.indisvalid AND i.indisunique "
                            "AND p.indexdef LIKE '%recovery_required%' "
                            "AND p.indexdef LIKE '%QUEUED%' AND p.indexdef LIKE '%RUNNING%')"
                        )
                    )
                    evidence_bound = await db.scalar(
                        text(
                            "SELECT EXISTS (SELECT 1 FROM pg_constraint c "
                            "JOIN pg_class t ON t.oid=c.conrelid "
                            "JOIN pg_namespace n ON n.oid=t.relnamespace "
                            "WHERE n.nspname=current_schema() AND t.relname='indexing_jobs' "
                            "AND c.conname='ck_indexing_jobs_manifest_size' AND c.convalidated)"
                        )
                    )
                    if not valid or not evidence_bound:
                        raise ValueError("Indexing owner exclusion schema is unavailable")
                else:
                    await db.execute(select(IndexingJob.id).limit(1))

    async def start(self) -> None:
        if self.state != "INACTIVE":
            raise RuntimeError("Indexing supervisor cannot be started twice")
        self.state = "STARTING"
        try:
            async with asyncio.timeout(self.runtime.startup_timeout):
                await self._probe(schema=True)
                self.tasks = {
                    "worker": asyncio.create_task(self._poll(), name="indexing-polling"),
                    "classifier": asyncio.create_task(
                        self._classify(), name="indexing-classification"
                    ),
                }
                if isinstance(self.runtime, NormalIndexingRuntime):
                    self.tasks["dependencies"] = asyncio.create_task(
                        self._dependencies(), name="indexing-dependencies"
                    )
                for task in self.tasks.values():
                    task.add_done_callback(self._observed)

                async def handshake() -> None:
                    await asyncio.gather(self._worker_ready.wait(), self._classifier_ready.wait())

                handshakes = asyncio.create_task(handshake(), name="indexing-startup-handshake")
                try:
                    done, _ = await asyncio.wait(
                        [handshakes, *self.tasks.values()], return_when=asyncio.FIRST_COMPLETED
                    )
                    if handshakes not in done or any(t.done() for t in self.tasks.values()):
                        raise RuntimeError("Indexing startup handshake failed")
                finally:
                    handshakes.cancel()
                    await asyncio.gather(handshakes, return_exceptions=True)
                if self.stop.is_set():
                    raise RuntimeError("Indexing startup interrupted")
                self.state = "READY"
                self._go.set()
        except BaseException:
            self._fail()
            # Keep startup's original exception, but all task cleanup stays owned.
            self.begin_shutdown()
            raise

    async def authorize_admission(self, db: AsyncSession | None = None) -> bool:
        if not self.healthy:
            return False
        try:
            await self._probe(db=db)
            if isinstance(self.runtime, NormalIndexingRuntime):
                await check_collection(self.worker.settings)
        except Exception as exc:
            if is_transient(exc):
                # Refuse this one request (the caller answers 503, try again). The polling and
                # dependency loops own the decision to close for good, after the recovery window.
                logger.warning(
                    "Indexing admission refused: dependency momentarily unavailable (%s).",
                    exc.code if isinstance(exc, IndexingActivationError) else type(exc).__name__,
                )
                return False
            self.failure_reason = (
                exc.code if isinstance(exc, IndexingActivationError) else "DATABASE_UNAVAILABLE"
            )
            self._fail()
            return False
        return self.healthy

    @property
    def admission_count(self) -> int:
        return len(self._admissions)

    @asynccontextmanager
    async def admission(self, db: AsyncSession) -> AsyncIterator[AdmissionPermit]:
        """Own request SQL cleanup even after timeout or repeated cancellation.

        Registration precedes preliminary SQL/probe waits. The permit is only
        granted by the service after its final SQL wait, before publication.
        No process-local lock is held across database work.
        """
        task = asyncio.current_task()
        if task is None or task.cancelling() or not self.healthy:
            raise IndexingAdmissionUnavailable()
        permit = AdmissionPermit(self, task)
        self._admissions.add(permit)
        self._admissions_idle.clear()
        try:
            async with asyncio.timeout(self.runtime.database_timeout):
                yield permit
        except TimeoutError:
            raise IndexingAdmissionUnavailable() from None
        finally:

            async def cleanup() -> None:
                try:
                    if db.in_transaction():
                        await db.rollback()
                finally:
                    # Close before unregistering: FastAPI dependency teardown may
                    # run later, but this owned session can no longer require SQL.
                    await db.close()

            permit.cleanup = asyncio.create_task(cleanup(), name="indexing-admission-cleanup")
            interrupted = False
            try:
                while True:
                    try:
                        await asyncio.shield(permit.cleanup)
                        break
                    except asyncio.CancelledError:
                        if permit.cleanup.cancelled():
                            raise
                        interrupted = True
            except BaseException:
                # Cleanup cannot be proven complete. Retain the registration and
                # fail closed; never dispose the engine through an unsafe shortcut.
                self._fail()
                logger.error("Indexing admission SQL cleanup is incomplete; disposal is blocked.")
                raise
            self._admissions.remove(permit)
            if not self._admissions:
                self._admissions_idle.set()
            if interrupted:
                raise asyncio.CancelledError

    async def _pause(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self.stop.wait(), seconds)
        except TimeoutError:
            pass

    async def _poll(self) -> None:
        await self._probe()
        self._worker_ready.set()
        await self._go.wait()
        while not self.stop.is_set():
            if not self.healthy:
                self._fail()
                break
            # Bound idle connection/claim stalls without putting a deadline around
            # a legitimate long stage (its independent heartbeat supervises it).
            try:
                async with asyncio.timeout(self.runtime.database_timeout):
                    claim = await self.worker.claim_next()
            except Exception as exc:
                # Idle claiming holds no job, so retrying is safe. A claim that committed while its
                # reply was lost expires and is classified exactly as after a restart. A failure
                # while *executing* a stage (below) is never retried: its state is uncertain.
                if not self._tolerate("worker", exc):
                    raise
                await self._pause(self._backoff("worker"))
                continue
            self._recovered("worker")
            if claim is not None:
                if self.stop.is_set() or not self.healthy:
                    if not self.stop.is_set():
                        self._fail()
                    # A claim transaction may already have committed while a
                    # sibling failed. Do not begin a new stage after known loss
                    # of local executor health; no remote work was issued here.
                    await self.worker.finalize(
                        claim, StageProgress(), error="Indexing executor stopped before execution."
                    )
                else:
                    await self.worker.execute(claim)
            await self._pause(self.runtime.poll_seconds)

    async def _dependencies(self) -> None:
        assert isinstance(self.runtime, NormalIndexingRuntime)
        await self._go.wait()
        while not self.stop.is_set():
            await self._pause(self.worker.settings.indexing_dependency_seconds)
            if self.stop.is_set():
                break
            probe = asyncio.create_task(
                self.runtime.check_dependencies(), name="indexing-dependency-round"
            )
            try:
                done, _ = await asyncio.wait([probe], timeout=2 * self.runtime.database_timeout)
                if not done:
                    # A round that outlives twice its own bounded timeouts is not a hiccup: its
                    # cleanup may be stuck. Close health first, before awaiting that cleanup.
                    self.failure_reason = "DEPENDENCY_CHECK_TIMEOUT"
                    self._fail()
                    probe.cancel()
                try:
                    await asyncio.shield(probe)
                except Exception as exc:
                    if not self._tolerate("dependencies", exc):
                        raise
                else:
                    self._recovered("dependencies")
            finally:
                if not probe.done() and not probe.cancelling():
                    probe.cancel()
                # Own the round/its cleanup through repeated caller cancellation.
                while not probe.done():
                    try:
                        await asyncio.shield(probe)
                    except asyncio.CancelledError:
                        if probe.cancelled():
                            break
                    except Exception:
                        break
                if not probe.cancelled():
                    probe.exception()

    async def _classification_round(self) -> None:
        async with asyncio.timeout(self.runtime.database_timeout):
            async with self.worker.sessions() as db:
                ids = list(
                    (
                        await db.scalars(
                            select(IndexingJob.id)
                            .join(User, User.id == IndexingJob.user_id)
                            .where(
                                User.id != self.worker.demo_user_id,
                                ~User.google_id.startswith("demo:"),
                                IndexingJob.operation.is_not(None),
                                IndexingJob.status == IndexingJobStatus.RUNNING,
                                IndexingJob.claim_id.is_not(None),
                                IndexingJob.worker_id.is_not(None),
                                IndexingJob.lease_expires_at <= func.clock_timestamp(),
                            )
                            .order_by(IndexingJob.lease_expires_at, IndexingJob.id)
                            .limit(self.runtime.classification_batch)
                        )
                    ).all()
                )
            for job_id in ids:
                if self.stop.is_set():
                    break
                await self.classifier.classify(job_id)  # Lock-first fresh DB time.

    async def _classify(self) -> None:
        await self._classification_round()
        self._classifier_ready.set()
        await self._go.wait()
        while not self.stop.is_set():
            await self._pause(self.runtime.classifier_seconds)
            if not self.stop.is_set():
                try:
                    await self._classification_round()
                except Exception as exc:
                    if not self._tolerate("classifier", exc):
                        raise
                else:
                    self._recovered("classifier")

    def begin_shutdown(self) -> None:
        """Synchronous close, once-only cancellation, strongly retained final join."""
        if self._shutdown_task is not None:
            return
        self.state = "STOPPING"
        self.stop.set()
        self._go.set()

        async def finish() -> None:
            tasks = list(self.tasks.values())
            admissions = asyncio.create_task(
                self._admissions_idle.wait(), name="indexing-admission-drain"
            )
            try:
                _, pending = await asyncio.wait(
                    [admissions, *tasks], timeout=self.runtime.drain_seconds
                )
                for permit in tuple(self._admissions):
                    if (
                        permit.cleanup is None
                        and not permit.task.done()
                        and not permit.task.cancelling()
                        and not permit.cancel_requested
                    ):
                        permit.cancel_requested = True
                        permit.task.cancel()
                for task in tasks:
                    if task in pending and not task.cancelling():
                        task.cancel()
                # Retained cleanup can exceed bounded lifespan grace. Never send
                # a second cancellation into a rollback or dispose while it runs.
                await asyncio.gather(*tasks, return_exceptions=True)
                await admissions
                self.state = "STOPPED"
            finally:
                if not admissions.done():
                    admissions.cancel()
                await asyncio.gather(admissions, return_exceptions=True)

        self._shutdown_task = asyncio.create_task(finish(), name="indexing-shutdown")
        self._shutdown_task.add_done_callback(self._observe_shutdown)

    @staticmethod
    def _observe_shutdown(task: asyncio.Task[None]) -> None:
        if task.cancelled() or task.exception() is not None:
            logger.error("Indexing shutdown did not complete; preserve unresolved work.")

    async def wait_closed(self) -> None:
        self.begin_shutdown()
        assert self._shutdown_task is not None
        await asyncio.shield(self._shutdown_task)
