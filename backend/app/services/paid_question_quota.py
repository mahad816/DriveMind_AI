"""Persistent paid-question allowance per Owner (M0-SEC ticket 05).

Each admitted question is one row (an attempt) in ``paid_question_attempts``; the limits are
counted from those rows, so they survive restarts and are correct across processes (PostgreSQL
decides, under a per-Owner advisory lock). The values are provisional, see ``Settings``.

A row is a reservation, not proof that anything ran. It ends in exactly one of two ways:
``finish`` (paid provider execution began, so the attempt keeps counting in the hour and day
windows and only frees the concurrent slot) or ``release`` (it never began, the row is deleted).
Callers use only ``admit`` and ``settle``; ``settle`` picks the right end from the
``PaidExecutionMarker`` so a started attempt can never be released and an unstarted one can never
stay counted. Routes are wired to this in ticket 06.

Every operation opens its own short session from the engine, never the request's session.
"""

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import CursorResult, delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.paid_execution import PaidExecutionMarker
from app.db.models.paid_question_attempt import PaidQuestionAttempt as Attempt

logger = logging.getLogger(__name__)

Reason = Literal["hour", "day", "concurrent"]
HOUR = timedelta(hours=1)
DAY = timedelta(hours=24)
CLEANUP_TIMEOUT_SECONDS = 10
CANCEL_WAIT_SECONDS = 15


class QuotaRefused(Exception):
    """The Owner is at a limit. ``retry_after_seconds`` is at least 1."""

    def __init__(self, reason: Reason, retry_after_seconds: int) -> None:
        super().__init__(f"Paid-question limit reached: {reason}")
        self.reason = reason
        self.retry_after_seconds = retry_after_seconds


class QuotaUnavailable(Exception):
    """The ledger could not be used (lock or statement timeout, database error). Fail closed."""


def lock_key(owner: UUID) -> str:
    """The advisory-lock key text that serializes admissions for one Owner."""
    return f"paid-question:{owner}"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _seconds_until(moment: datetime, now: datetime) -> int:
    return max(1, math.ceil((moment - now).total_seconds()))


class PaidQuestionQuota:
    def __init__(
        self,
        engine: AsyncEngine,
        settings: Settings,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)
        self._hour_limit = settings.paid_question_hour_limit
        self._day_limit = settings.paid_question_day_limit
        self._concurrent_limit = settings.paid_question_concurrent_limit
        self._lease = timedelta(seconds=settings.paid_question_lease_seconds)
        self._retention = timedelta(hours=settings.paid_question_retention_hours)
        self._clock = clock
        self._background: set[asyncio.Future[Any]] = set()

    async def admit(self, owner: UUID) -> UUID:
        """Reserve one attempt and commit it before returning, or refuse.

        Raises ``QuotaRefused`` at a limit and ``QuotaUnavailable`` when the ledger cannot be used;
        neither ever admits.

        Cancellation: the transaction runs as its own task, so a cancelled caller cannot interrupt
        it half-way, and the caller never receives an id it cannot settle. On cancellation the
        task gets a done-callback that releases the attempt if one was committed (a deleted row
        never counts), and ``admit`` also waits briefly for it so the row is normally gone before
        the cancellation propagates. A second cancellation, or a stalled database, therefore
        cannot leak the row: the callback still releases it when the transaction ends. Only a
        process kill in that window leaves a row, which stops blocking after the lease, counts in
        the hour and day windows until ``prune`` removes it, like any crash orphan.
        """
        admission = asyncio.ensure_future(self._admit(owner))
        try:
            return await asyncio.shield(admission)
        except asyncio.CancelledError:
            self._background.add(admission)  # a strong reference: the loop only holds weak ones
            admission.add_done_callback(self._release_if_admitted)
            await asyncio.wait({admission}, timeout=CANCEL_WAIT_SECONDS)
            if admission.done() and not admission.cancelled() and admission.exception() is None:
                await self.settle(admission.result(), PaidExecutionMarker())  # idempotent
            raise

    def _release_if_admitted(self, admission: "asyncio.Future[UUID]") -> None:
        self._background.discard(admission)
        if admission.cancelled() or admission.exception() is not None:
            return
        cleanup = asyncio.ensure_future(self.settle(admission.result(), PaidExecutionMarker()))
        self._background.add(cleanup)
        cleanup.add_done_callback(self._background.discard)

    async def _admit(self, owner: UUID) -> UUID:
        attempt_id = uuid4()
        try:
            async with self._sessions.begin() as db:
                await db.execute(text("SET LOCAL lock_timeout = '2s'"))
                await db.execute(text("SET LOCAL statement_timeout = '10s'"))
                # Read committed: "lock, then count, then insert" is correct under this lock.
                await db.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                    {"key": lock_key(owner)},
                )
                now = self._clock()
                refusals = [
                    refusal
                    for refusal in (
                        await self._unfinished_refusal(db, owner, now),
                        await self._window_refusal(db, owner, now, "hour", HOUR, self._hour_limit),
                        await self._window_refusal(db, owner, now, "day", DAY, self._day_limit),
                    )
                    if refusal is not None
                ]
                if refusals:
                    # Report the limit that takes longest to clear: waiting less cannot help.
                    raise max(refusals, key=lambda refusal: refusal.retry_after_seconds)
                db.add(Attempt(id=attempt_id, owner_id=owner, started_at=now))
        except QuotaRefused:
            raise
        except Exception as exc:
            logger.warning("Paid-question admission unavailable (%s)", type(exc).__name__)
            raise QuotaUnavailable from None
        return attempt_id

    async def _unfinished_refusal(
        self, db: AsyncSession, owner: UUID, now: datetime
    ) -> QuotaRefused | None:
        # The limit-th newest live attempt: once its lease ends, fewer than the limit remain.
        started = await db.scalars(
            select(Attempt.started_at)
            .where(
                Attempt.owner_id == owner,
                Attempt.finished_at.is_(None),
                Attempt.started_at > now - self._lease,
            )
            .order_by(Attempt.started_at.desc())
            .limit(self._concurrent_limit)
        )
        rows = list(started)
        if len(rows) < self._concurrent_limit:
            return None
        return QuotaRefused("concurrent", _seconds_until(rows[-1] + self._lease, now))

    async def _window_refusal(
        self,
        db: AsyncSession,
        owner: UUID,
        now: datetime,
        reason: Reason,
        window: timedelta,
        limit: int,
    ) -> QuotaRefused | None:
        started = await db.scalars(
            select(Attempt.started_at)
            .where(Attempt.owner_id == owner, Attempt.started_at > now - window)
            .order_by(Attempt.started_at.desc())
            .limit(limit)
        )
        rows = list(started)
        if len(rows) < limit:
            return None
        return QuotaRefused(reason, _seconds_until(rows[-1] + window, now))

    async def finish(self, attempt_id: UUID) -> None:
        """Free the concurrent slot; the attempt keeps counting. Idempotent, touches only its row."""
        async with self._sessions.begin() as db:
            await db.execute(
                update(Attempt)
                .where(Attempt.id == attempt_id, Attempt.finished_at.is_(None))
                .values(finished_at=self._clock())
            )

    async def release(self, attempt_id: UUID) -> None:
        """Delete the attempt: it never began paid execution. Idempotent, touches only its row."""
        async with self._sessions.begin() as db:
            await db.execute(delete(Attempt).where(Attempt.id == attempt_id))

    async def settle(self, attempt_id: UUID, marker: PaidExecutionMarker) -> None:
        """End an attempt: ``finish`` if a provider request began, otherwise ``release``.

        Runs in a fresh session under a 10-second timeout and survives cancellation of the caller
        (the row is still freed before the cancellation propagates). A failure is logged by
        category and swallowed, so it never changes a response; the lease covers it.
        """
        operation = self.finish if marker.started else self.release
        cleanup = asyncio.ensure_future(self._bounded(operation, attempt_id))
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            await asyncio.wait({cleanup})
            raise

    @staticmethod
    async def _bounded(operation: Callable[[UUID], Awaitable[None]], attempt_id: UUID) -> None:
        try:
            await asyncio.wait_for(operation(attempt_id), CLEANUP_TIMEOUT_SECONDS)
        except Exception as exc:
            logger.warning("Paid-question settle failed (%s)", type(exc).__name__)

    async def prune(self) -> int:
        """Delete finished attempts past the retention and unfinished ones past twice the lease.

        Retention is never below 25 hours (a settings rule), so pruning cannot shorten the
        24-hour window. Returns the number of rows removed.
        """
        now = self._clock()
        async with self._sessions.begin() as db:
            result = await db.execute(
                delete(Attempt).where(
                    (
                        Attempt.finished_at.is_not(None)
                        & (Attempt.started_at < now - self._retention)
                    )
                    | (Attempt.finished_at.is_(None) & (Attempt.started_at < now - 2 * self._lease))
                )
            )
            return cast(CursorResult[Any], result).rowcount
