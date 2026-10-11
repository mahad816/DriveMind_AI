"""Managed Google refresh, with independent short DB transactions and no silent retry."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Coroutine
from concurrent.futures import CancelledError as FutureCancelled
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from threading import Event, Lock, Thread, get_ident
from datetime import UTC, datetime
from typing import Any, TypeVar, cast
from uuid import UUID

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from pydantic import SecretStr
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.connectors.google_drive.client import DriveClientError, DriveTokens, GoogleDriveClient
from app.core.config import Settings
from app.core.credential_diagnostics import failure_category
from app.security.google_credential_crypto import CredentialCryptoError, GoogleCredentialCrypto
from app.services.google_credential_repository import (
    CredentialNotFound,
    CredentialRecordChanged,
    CredentialRecoveryRequired,
    CredentialReauthorizationRequired,
    CredentialRepositoryError,
    CredentialSnapshot,
    GoogleCredentialRepository,
    RefreshClaim,
)

T = TypeVar("T")
logger = logging.getLogger(__name__)


def utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class SingleRefreshRequest:
    """Only one token endpoint attempt. SDK retries must not reuse an uncertain token."""

    def __init__(self) -> None:
        self.request = Request()
        self.attempted = False

    def close(self) -> None:
        session = getattr(self.request, "session", None)
        if session is not None:
            session.close()

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if self.attempted:
            raise DriveClientError("Google refresh recovery is required.")
        self.attempted = True
        kwargs["timeout"] = (5, 10)
        response = self.request(*args, **kwargs)
        if response.status == 429 or 500 <= response.status <= 599:
            raise DriveClientError(
                "Google is temporarily unavailable; refresh recovery is pending.",
                category="temporary_provider_failure",
            )
        return response


@dataclass(eq=False, repr=False)
class _DatabaseCallback:
    coroutine: Coroutine[Any, Any, Any]
    future: Future[Any] | None = None
    task: asyncio.Task[Any] | None = None


class GoogleRefreshLifecycle:
    """Engine/session-factory-owned refresh work; FastAPI closes it before disposal.

    A caller's deadline never cancels the provider thread. Threads are bounded in
    number and tracked until exit; after shutdown they cannot submit DB work.
    """

    def __init__(
        self,
        *,
        waiting_budget: float = 20,
        shutdown_grace: float = 20,
        callback_timeout: float = 5,
        max_workers: int = 16,
    ) -> None:
        self.waiting_budget = waiting_budget
        self.shutdown_grace = shutdown_grace
        self.callback_timeout = callback_timeout
        self.max_workers = max_workers
        self._lock = Lock()
        self._database_closed = Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: int | None = None
        self._closing = False
        self._database_open = True
        self._workers: set[Future[Any]] = set()
        self._callbacks: set[_DatabaseCallback] = set()
        self._shutdown_lock = asyncio.Lock()
        self._disposal_task: asyncio.Task[None] | None = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        with self._lock:
            if self._closing or (self._loop is not None and self._loop is not loop):
                raise DriveClientError("Google refresh lifecycle is unavailable.")
            self._loop = loop
            self._loop_thread = get_ident()

    @property
    def active_workers(self) -> int:
        with self._lock:
            return len(self._workers)

    @property
    def active_callbacks(self) -> int:
        with self._lock:
            return len(self._callbacks)

    def run(self, work: Callable[[], T]) -> T:
        """Called by the SDK thread, never the application's event-loop thread."""
        deadline = time.monotonic() + self.waiting_budget
        result: Future[T] = Future()

        def worker() -> None:
            try:
                value = work()
            except Exception as exc:
                # The Future must not retain a raw provider exception/context.
                result.set_exception(
                    DriveClientError(
                        "Google refresh failed; try later or reconnect.",
                        category=failure_category(exc),
                    )
                )
            else:
                result.set_result(value)
            finally:
                with self._lock:
                    self._workers.discard(result)

        with self._lock:
            if self._loop_thread == get_ident():
                raise DriveClientError("Google refresh requires an SDK worker thread.")
            if self._closing or len(self._workers) >= self.max_workers:
                raise DriveClientError(
                    "Google refresh is unavailable; try later.",
                    category="temporary_provider_failure",
                )
            result.set_running_or_notify_cancel()
            self._workers.add(result)
            try:
                Thread(target=worker, name="google-credential-refresh", daemon=True).start()
            except Exception:
                self._workers.discard(result)
                raise DriveClientError("Google refresh could not start.") from None
        try:
            return result.result(timeout=max(0, deadline - time.monotonic()))
        except FutureTimeout:
            raise DriveClientError(
                "Google refresh timed out; its outcome is pending. Try later or reconnect.",
                category="temporary_provider_failure",
            ) from None

    def call(self, coroutine: Coroutine[Any, Any, T]) -> T:
        """Atomic callback admission and tracking, including queued callbacks."""
        ticket = _DatabaseCallback(coroutine)

        async def bounded() -> T:
            try:
                with self._lock:
                    ticket.task = asyncio.current_task()
                    allowed = self._database_open
                if not allowed:
                    coroutine.close()
                    raise DriveClientError("Google refresh persistence is closed.")
                task = ticket.task
                assert task is not None

                # Cancel once: a second cancellation could abandon SQLAlchemy's
                # shielded session-close task before rollback has completed.
                def cancel_once() -> None:
                    if not task.done() and not task.cancelling():
                        task.cancel()

                timer = asyncio.get_running_loop().call_later(self.callback_timeout, cancel_once)
                try:
                    return await coroutine
                finally:
                    timer.cancel()
            finally:
                with self._lock:
                    self._callbacks.discard(ticket)

        def completed(future: Future[Any]) -> None:
            with self._lock:
                if ticket.task is None:
                    # Cancellation before the wrapper ran must close its operand.
                    coroutine.close()
                    self._callbacks.discard(ticket)

        with self._lock:
            loop = self._loop
            if not self._database_open or loop is None or loop.is_closed():
                coroutine.close()
                raise DriveClientError("Google refresh persistence is closed.")
            if self._loop_thread == get_ident():
                coroutine.close()
                raise DriveClientError("Google refresh requires an SDK worker thread.")
            self._callbacks.add(ticket)
            wrapper = bounded()
            try:
                ticket.future = asyncio.run_coroutine_threadsafe(wrapper, loop)
            except RuntimeError:
                wrapper.close()
                coroutine.close()
                self._callbacks.discard(ticket)
                raise DriveClientError("Google refresh persistence is closed.") from None
        ticket.future.add_done_callback(completed)
        try:
            deadline = time.monotonic() + self.callback_timeout + 5
            while True:
                if self._database_closed.is_set():
                    raise DriveClientError("Google refresh persistence is closed.")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise FutureTimeout()
                try:
                    return cast(T, ticket.future.result(timeout=min(remaining, 0.05)))
                except FutureTimeout:
                    if ticket.future.done():
                        raise
        except (FutureTimeout, FutureCancelled):
            raise DriveClientError("Google refresh recovery is pending.") from None
        except (CredentialRepositoryError, CredentialCryptoError, SQLAlchemyError):
            raise DriveClientError(
                "Google refresh is unavailable; try later or reconnect."
            ) from None

    async def shutdown(self) -> None:
        """Bounded drain, seal DB admission, cancel/roll back callbacks, then dispose.

        Failure to drain DB cleanup raises: the caller MUST NOT dispose the engine.
        Synchronous provider work may remain, but its database boundary is closed.
        """
        async with self._shutdown_lock:
            with self._lock:
                self._closing = True
                workers = list(self._workers) if self._database_open else []
            try:
                if workers:
                    waiting = [asyncio.wrap_future(future) for future in workers]
                    for future in waiting:
                        future.add_done_callback(lambda f: None if f.cancelled() else f.exception())
                    await asyncio.wait(waiting, timeout=self.shutdown_grace)
            finally:
                with self._lock:
                    self._database_open = False
                    self._database_closed.set()
                    callbacks = list(self._callbacks)
                for ticket in callbacks:
                    if ticket.task is None and ticket.future is not None:
                        ticket.future.cancel()  # A queued wrapper has not acquired SQL resources.
                    elif ticket.task is not None and not ticket.task.cancelling():
                        ticket.task.cancel()
                tasks = [ticket.task for ticket in callbacks if ticket.task is not None]
                if tasks:
                    _, pending = await asyncio.wait(tasks, timeout=self.callback_timeout)
                    if pending:
                        raise DriveClientError("Google refresh shutdown cleanup is incomplete.")
            # Queued wrappers can run later, but their sealed admission check forbids SQL.

    async def shutdown_and_dispose(self, dispose: Callable[[], Awaitable[None]]) -> None:
        """Own final disposal even if bounded shutdown reports incomplete cleanup.

        One strongly retained task waits asynchronously for admitted SQL cleanup.
        It cannot guarantee disposal if its event loop is forcibly terminated.
        Failure/cancellation is observed and logged without exception details.
        """
        try:
            await self.shutdown()
        finally:
            with self._lock:
                sealed = not self._database_open
                tasks = [ticket.task for ticket in self._callbacks if ticket.task is not None]
            # No await between testing/storing the task: concurrent finalizers on
            # this application loop cannot create a second disposal attempt.
            if sealed and self._disposal_task is None:

                async def finish() -> None:
                    if tasks:
                        await asyncio.wait(tasks)  # Never cancel SQL cleanup a second time.
                        if any(
                            not task.cancelled() and task.exception() is not None for task in tasks
                        ):
                            logger.error(
                                "Google credential SQL callback failed during final cleanup."
                            )
                    failed = False
                    try:
                        await dispose()
                    except Exception:
                        failed = True
                    if failed:
                        raise DriveClientError("Google credential database disposal failed.")

                def observed(task: asyncio.Task[None]) -> None:
                    if task.cancelled():
                        logger.error("Google credential final disposal was cancelled.")
                    elif task.exception() is not None:
                        logger.error("Google credential final disposal failed.")

                self._disposal_task = asyncio.create_task(
                    finish(), name="google-credential-disposal"
                )
                self._disposal_task.add_done_callback(observed)
        # Reached only if bounded shutdown succeeded. A failure still propagates,
        # while its owned task finishes teardown when cleanup eventually returns.
        assert self._disposal_task is not None
        await asyncio.shield(self._disposal_task)


class GoogleCredentialService:
    """Tracked refresh threads own persistence even if the SDK caller stops waiting.

    SDK credentials contain no refresh token: explicit/implicit refresh uses its
    supported refresh_handler. DB callbacks use fresh sessions on the captured
    application loop. No request AsyncSession is used concurrently or committed.
    Loss of that loop/process leaves a persisted claim; it is never blindly stolen.
    """

    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        if settings.demo_mode or not isinstance(db.bind, AsyncEngine):
            raise DriveClientError(
                "Google credential configuration is unavailable.", category="configuration_error"
            )
        self.settings = settings
        self.loop = asyncio.get_running_loop()
        self.sessions = async_sessionmaker(db.bind, expire_on_commit=False)
        self.lifecycle = db.info.get("google_refresh_lifecycle") or GoogleRefreshLifecycle()
        self.lifecycle.bind(self.loop)

    async def load(self, user_id: UUID) -> CredentialSnapshot:
        try:
            GoogleCredentialCrypto.from_settings(self.settings)
            async with self.sessions() as db:
                snapshot = await GoogleCredentialRepository(db, self.settings).load_encrypted(
                    user_id
                )
            record = snapshot.record
            if record.grant_status == "REAUTH_REQUIRED":
                raise CredentialReauthorizationRequired()
            if record.grant_status == "RECOVERY_REQUIRED" or (
                record.refresh_claim_state == "SUBMITTED"
                and record.refresh_claim_expires_at is not None
                and record.refresh_claim_expires_at <= datetime.now(UTC)
            ):
                raise CredentialRecoveryRequired()
            return snapshot
        except CredentialCryptoError:
            raise DriveClientError(
                "Google credential encryption is unavailable.", category="configuration_error"
            ) from None
        except CredentialReauthorizationRequired:
            raise DriveClientError(
                "Reconnect Google Drive to authorize this operation.",
                category="reauthorization_required",
            ) from None
        except CredentialRecoveryRequired:
            raise DriveClientError(
                "Google refresh recovery is pending; try later or reconnect.",
                category="temporary_provider_failure",
            ) from None
        except CredentialRepositoryError:
            raise DriveClientError(
                "Google credentials are unavailable; try later or reconnect."
            ) from None

    def _on_loop(self, coroutine: Coroutine[Any, Any, T]) -> T:
        return self.lifecycle.call(coroutine)

    async def _claim(self, snapshot: CredentialSnapshot) -> RefreshClaim:
        async with self.sessions() as db:
            claim = await GoogleCredentialRepository(db, self.settings).claim_refresh(
                snapshot.record
            )
            await db.commit()
            return claim

    async def _submit(self, claim: RefreshClaim) -> None:
        async with self.sessions() as db:
            await GoogleCredentialRepository(db, self.settings).submit_refresh(claim)
            await db.commit()

    async def _complete(self, claim: RefreshClaim, credentials: Credentials) -> CredentialSnapshot:
        expiry = utc(credentials.expiry)
        if not credentials.token or expiry is None:
            raise DriveClientError("Google returned unusable refresh credentials.")
        async with self.sessions() as db:
            snapshot = await GoogleCredentialRepository(db, self.settings).complete_refresh(
                claim,
                access_token=SecretStr(credentials.token),
                refresh_token=SecretStr(credentials.refresh_token)
                if credentials.refresh_token
                else None,
                token_expiry=expiry,
                scopes=" ".join(
                    credentials.granted_scopes
                    or credentials.scopes
                    or claim.snapshot.record.scopes.split()
                ),
            )
            await db.commit()
            return snapshot

    async def _fail(
        self, claim: RefreshClaim, revoked: bool, before_submission: bool = False
    ) -> None:
        async with self.sessions() as db:
            try:
                await GoogleCredentialRepository(db, self.settings).fail_refresh(
                    claim, revoked=revoked, before_submission=before_submission
                )
                await db.commit()
            except (CredentialRecordChanged, CredentialNotFound):
                # Reconnect/deletion won: a stale failure cannot change the new grant.
                await db.rollback()

    def client(self, snapshot: CredentialSnapshot) -> GoogleDriveClient:
        payload = snapshot.payload
        if payload.access_token is None:
            raise DriveClientError("Google access credentials are unavailable.")
        if not self.settings.google_client_id or not self.settings.google_client_secret:
            raise DriveClientError(
                "Google credential configuration is unavailable.", category="configuration_error"
            )
        current = snapshot

        def perform_refresh() -> tuple[str, datetime]:
            nonlocal current
            deadline = time.monotonic() + 3
            while True:
                try:
                    claim = self._on_loop(self._claim(current))
                    break
                except DriveClientError:
                    # Reload is bounded; only a changed successful revision can
                    # supply a reusable result. Never retry an unknown refresh.
                    latest = self._on_loop(self.load(current.record.user_id))
                    if (
                        latest.record.id != current.record.id
                        or latest.record.grant_epoch != current.record.grant_epoch
                    ):
                        raise DriveClientError(
                            "Google connection changed; retry this operation."
                        ) from None
                    if latest.record.credential_revision != current.record.credential_revision:
                        current = latest
                        if latest.payload.access_token and latest.record.token_expiry:
                            return (
                                latest.payload.access_token.get_secret_value(),
                                latest.record.token_expiry.astimezone(UTC).replace(tzinfo=None),
                            )
                    if time.monotonic() >= deadline:
                        raise DriveClientError(
                            "Google credential refresh is busy; try later."
                        ) from None
                    time.sleep(0.05)
            native = Credentials(  # type: ignore[no-untyped-call]
                token=claim.snapshot.payload.access_token.get_secret_value()
                if claim.snapshot.payload.access_token
                else None,
                refresh_token=claim.snapshot.payload.refresh_token.get_secret_value()
                if claim.snapshot.payload.refresh_token
                else None,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=self.settings.google_client_id,
                client_secret=self.settings.google_client_secret,
                scopes=claim.snapshot.record.scopes.split(),
            )
            requester = SingleRefreshRequest()
            try:
                self._on_loop(self._submit(claim))  # committed BEFORE any Google refresh I/O
                native.refresh(requester)  # type: ignore[no-untyped-call]
                current = self._on_loop(self._complete(claim, native))
            except Exception as exc:
                category = failure_category(exc)
                try:
                    self._on_loop(
                        self._fail(
                            claim, category == "reauthorization_required", not requester.attempted
                        )
                    )
                except Exception:
                    pass  # persisted claim itself prevents unsafe reuse if recovery storage failed
                raise DriveClientError(
                    "Google refresh failed; try later or reconnect.", category=category
                ) from None
            finally:
                requester.close()
            assert (
                current.payload.access_token is not None and current.record.token_expiry is not None
            )
            return (
                current.payload.access_token.get_secret_value(),
                current.record.token_expiry.astimezone(UTC).replace(tzinfo=None),
            )

        return GoogleDriveClient(
            DriveTokens(
                payload.access_token.get_secret_value(),
                None,
                snapshot.record.token_expiry,
                snapshot.record.scopes,
            ),
            settings=self.settings,
            refresh_handler=lambda request, scopes=None: self.lifecycle.run(perform_refresh),
        )
