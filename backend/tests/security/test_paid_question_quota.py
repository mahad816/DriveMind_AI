"""M0-SEC ticket 05: the persistent paid-question quota, against disposable PostgreSQL.

Needs ``SESSION_TEST_DATABASE_URL`` (skipped without it). No provider, Qdrant or network.
Time is an injected clock, never a sleep, except where a real lock timeout is the point.
"""

# ruff: noqa: F811  (fixtures are imported by name and then requested as arguments)
import asyncio
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.core.paid_execution import PaidExecutionMarker, install_marker, mark_paid_started
from app.db.models import PaidQuestionAttempt
from app.services.paid_question_quota import (
    PaidQuestionQuota,
    QuotaRefused,
    QuotaUnavailable,
    lock_key,
)
from tests.security.conftest import (
    BACKEND,
    PAID_QUESTION_REVISION,
    USER_A,
    USER_B,
    apply_revision,
    pg_engine,  # noqa: F401  # pyright: ignore[reportUnusedImport]  (pytest fixture, by name)
)

T0 = datetime(2026, 11, 21, 9, 0, tzinfo=UTC)
LEASE = 300


class Clock:
    def __init__(self, now: datetime = T0) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


def make_settings(**overrides) -> Settings:
    values = {"paid_question_lease_seconds": LEASE, **overrides}
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def make_quota(engine, clock: Clock | None = None, **overrides) -> PaidQuestionQuota:
    return PaidQuestionQuota(engine, make_settings(**overrides), clock=clock or Clock())


async def rows(engine, owner: UUID | None = None) -> list[tuple]:
    sql = "SELECT id, owner_id, started_at, finished_at FROM paid_question_attempts"
    params = {}
    if owner is not None:
        sql += " WHERE owner_id = :o"
        params = {"o": owner}
    sql += " ORDER BY started_at"
    async with async_sessionmaker(engine)() as db:
        return [tuple(r) for r in (await db.execute(text(sql), params))]


async def admit_and_finish(quota: PaidQuestionQuota, owner: UUID, n: int) -> None:
    for _ in range(n):
        await quota.finish(await quota.admit(owner))


async def refusal(quota: PaidQuestionQuota, owner: UUID) -> QuotaRefused:
    with pytest.raises(QuotaRefused) as caught:
        await quota.admit(owner)
    return caught.value


# --- limits and Retry-After ------------------------------------------------------------------


async def test_hour_limit_refuses_the_21st_and_admits_after_the_window(pg_engine):
    clock = Clock()
    quota = make_quota(pg_engine, clock)
    await admit_and_finish(quota, USER_A, 20)
    clock.advance(minutes=10)
    refused = await refusal(quota, USER_A)
    assert (refused.reason, refused.retry_after_seconds) == ("hour", 50 * 60)
    clock.advance(minutes=50, seconds=1)  # the oldest attempts have aged out of the hour
    await quota.admit(USER_A)


async def test_day_limit_refuses_the_51st_and_admits_after_the_window(pg_engine):
    clock = Clock()
    quota = make_quota(pg_engine, clock)
    for hours in (0, 2, 4):  # 20 + 20 + 10, never more than 20 inside one hour
        clock.now = T0 + timedelta(hours=hours)
        await admit_and_finish(quota, USER_A, 10 if hours == 4 else 20)
    clock.now = T0 + timedelta(hours=5)
    refused = await refusal(quota, USER_A)
    assert (refused.reason, refused.retry_after_seconds) == ("day", 19 * 3600)
    clock.now = T0 + timedelta(hours=24, seconds=1)
    await quota.admit(USER_A)


async def test_concurrent_limit_refuses_a_second_unfinished_attempt(pg_engine):
    clock = Clock()
    quota = make_quota(pg_engine, clock)
    first = await quota.admit(USER_A)
    clock.advance(seconds=100)
    refused = await refusal(quota, USER_A)
    assert (refused.reason, refused.retry_after_seconds) == ("concurrent", LEASE - 100)
    await quota.finish(first)
    await quota.admit(USER_A)


async def test_retry_after_is_at_least_one_second(pg_engine):
    clock = Clock()
    quota = make_quota(pg_engine, clock)
    await quota.admit(USER_A)
    clock.advance(seconds=LEASE - 1, milliseconds=900)
    assert (await refusal(quota, USER_A)).retry_after_seconds == 1


async def test_the_limit_that_takes_longest_to_clear_is_reported(pg_engine):
    clock = Clock()
    quota = make_quota(pg_engine, clock, paid_question_hour_limit=2, paid_question_day_limit=2)
    await admit_and_finish(quota, USER_A, 2)
    clock.advance(minutes=30)
    refused = await refusal(quota, USER_A)  # hour clears in 30 min, day in 23.5 h
    assert refused.reason == "day" and refused.retry_after_seconds == int(23.5 * 3600)


async def test_limits_are_configurable_and_the_concurrent_limit_can_be_raised(pg_engine):
    quota = make_quota(pg_engine, paid_question_hour_limit=3, paid_question_concurrent_limit=2)
    await quota.admit(USER_A)
    await quota.admit(USER_A)
    assert (await refusal(quota, USER_A)).reason == "concurrent"
    quota = make_quota(pg_engine, paid_question_hour_limit=2, paid_question_concurrent_limit=5)
    assert (await refusal(quota, USER_A)).reason == "hour"


async def test_owner_a_at_a_limit_does_not_change_owner_b(pg_engine):
    quota = make_quota(pg_engine, paid_question_hour_limit=1, paid_question_concurrent_limit=5)
    await quota.admit(USER_A)
    assert (await refusal(quota, USER_A)).reason == "hour"
    await quota.admit(USER_B)
    assert len(await rows(pg_engine, USER_A)) == 1 and len(await rows(pg_engine, USER_B)) == 1


# --- real concurrency ------------------------------------------------------------------------


async def test_simultaneous_admissions_at_concurrent_limit_one_admit_exactly_one(pg_engine):
    quota = make_quota(pg_engine, paid_question_hour_limit=100, paid_question_day_limit=100)
    results = await asyncio.gather(
        *(quota.admit(USER_A) for _ in range(12)), return_exceptions=True
    )
    admitted = [r for r in results if isinstance(r, UUID)]
    refused = [r for r in results if isinstance(r, QuotaRefused)]
    assert len(admitted) == 1 and len(refused) == 11
    assert {r.reason for r in refused} == {"concurrent"}
    # The reservation is visible to a fresh engine as soon as admit has returned.
    fresh = create_async_engine(
        pg_engine.url,
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": await search_path(pg_engine)}},
    )
    try:
        assert [r[0] for r in await rows(fresh, USER_A)] == admitted
    finally:
        await fresh.dispose()


async def test_simultaneous_admissions_never_exceed_the_hour_limit(pg_engine):
    quota = make_quota(
        pg_engine,
        paid_question_hour_limit=3,
        paid_question_day_limit=50,
        paid_question_concurrent_limit=50,
    )
    results = await asyncio.gather(
        *(quota.admit(USER_A) for _ in range(12)), return_exceptions=True
    )
    assert sum(isinstance(r, UUID) for r in results) == 3
    assert all(isinstance(r, (UUID, QuotaRefused)) for r in results)
    assert len(await rows(pg_engine, USER_A)) == 3


async def search_path(engine) -> str:
    async with engine.connect() as connection:
        return await connection.scalar(text("SHOW search_path"))


async def test_admission_works_while_a_request_session_holds_a_pooled_connection(pg_engine):
    """The quota takes its own connection beside the request's: the default pool must hold both."""
    pooled = create_async_engine(
        pg_engine.url,
        connect_args={"server_settings": {"search_path": await search_path(pg_engine)}},
    )
    try:
        quota = make_quota(pooled)
        async with async_sessionmaker(pooled)() as request_db:
            await request_db.execute(text("SELECT 1"))  # the request's connection is checked out
            await quota.finish(await quota.admit(USER_A))
    finally:
        await pooled.dispose()


# --- fail closed -----------------------------------------------------------------------------


async def test_a_held_owner_lock_makes_admit_unavailable_within_the_lock_timeout(pg_engine):
    quota = make_quota(pg_engine)
    async with async_sessionmaker(pg_engine).begin() as holder:
        await holder.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": lock_key(USER_A)}
        )
        started = time.monotonic()
        with pytest.raises(QuotaUnavailable):
            await quota.admit(USER_A)
        assert 1.5 < time.monotonic() - started < 6
        await quota.admit(USER_B)  # another Owner's lock is a different key
    assert [r for r in await rows(pg_engine, USER_A)] == []
    await quota.admit(USER_A)  # the lock was released with the holder's transaction


async def test_a_database_error_during_admit_is_unavailable_never_an_admit(pg_engine):
    quota = make_quota(pg_engine)
    async with pg_engine.begin() as connection:
        await connection.execute(text("ALTER TABLE paid_question_attempts RENAME TO moved_away"))
    try:
        with pytest.raises(QuotaUnavailable):
            await quota.admit(USER_A)
    finally:
        async with pg_engine.begin() as connection:
            await connection.execute(
                text("ALTER TABLE moved_away RENAME TO paid_question_attempts")
            )
    assert await rows(pg_engine) == []
    await quota.admit(USER_A)


# --- restart ---------------------------------------------------------------------------------


async def test_counts_survive_a_brand_new_engine_and_service(pg_engine):
    clock = Clock()
    await admit_and_finish(make_quota(pg_engine, clock, paid_question_hour_limit=2), USER_A, 2)
    new_engine = create_async_engine(
        pg_engine.url,
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": await search_path(pg_engine)}},
    )
    try:
        again = make_quota(new_engine, clock, paid_question_hour_limit=2)
        assert (await refusal(again, USER_A)).reason == "hour"
        await again.admit(USER_B)
    finally:
        await new_engine.dispose()


# --- finish, release, settle -----------------------------------------------------------------


async def test_release_deletes_the_row_and_frees_slot_and_counts(pg_engine):
    quota = make_quota(pg_engine, paid_question_hour_limit=1)
    attempt = await quota.admit(USER_A)
    await quota.release(attempt)
    assert await rows(pg_engine, USER_A) == []
    await quota.release(attempt)  # idempotent
    await quota.admit(USER_A)  # slot and hour count are both free again


async def test_finish_frees_only_the_slot_and_the_attempt_still_counts(pg_engine):
    clock = Clock()
    quota = make_quota(pg_engine, clock, paid_question_hour_limit=1)
    attempt = await quota.admit(USER_A)
    clock.advance(seconds=5)
    await quota.finish(attempt)
    first = (await rows(pg_engine, USER_A))[0]
    assert first[3] == clock.now
    clock.advance(seconds=5)
    await quota.finish(attempt)  # idempotent: the finish time does not move
    assert (await rows(pg_engine, USER_A))[0][3] == first[3]
    assert (await refusal(quota, USER_A)).reason == "hour"  # slot free, but it counts


async def test_finish_and_release_touch_only_their_own_row(pg_engine):
    quota = make_quota(pg_engine, paid_question_concurrent_limit=3)
    a, b, c = [await quota.admit(USER_A) for _ in range(3)]
    await quota.finish(a)
    await quota.release(b)
    state = {r[0]: r[3] for r in await rows(pg_engine, USER_A)}
    assert set(state) == {a, c} and state[a] is not None and state[c] is None
    await quota.finish(uuid4())  # unknown ids change nothing
    await quota.release(uuid4())
    assert len(await rows(pg_engine, USER_A)) == 2


async def test_settle_finishes_a_started_attempt_and_releases_an_unstarted_one(pg_engine):
    quota = make_quota(pg_engine, paid_question_concurrent_limit=2)
    started, unstarted = await quota.admit(USER_A), await quota.admit(USER_A)
    marker = PaidExecutionMarker()
    with install_marker(marker):
        mark_paid_started()
    await quota.settle(started, marker)
    await quota.settle(unstarted, PaidExecutionMarker())
    remaining = await rows(pg_engine, USER_A)
    assert [r[0] for r in remaining] == [started] and remaining[0][3] is not None


async def test_a_started_marker_from_a_child_task_makes_settle_count_the_attempt(pg_engine):
    quota = make_quota(pg_engine)
    attempt = await quota.admit(USER_A)
    marker = PaidExecutionMarker()

    async def provider_call() -> None:
        mark_paid_started()

    with install_marker(marker):
        await asyncio.ensure_future(provider_call())
    await quota.settle(attempt, marker)
    assert len(await rows(pg_engine, USER_A)) == 1


async def test_settle_swallows_a_database_failure(pg_engine, caplog):
    quota = make_quota(pg_engine)
    attempt = await quota.admit(USER_A)
    async with pg_engine.begin() as connection:
        await connection.execute(text("ALTER TABLE paid_question_attempts RENAME TO moved_away"))
    try:
        await quota.settle(attempt, PaidExecutionMarker())  # must not raise
    finally:
        async with pg_engine.begin() as connection:
            await connection.execute(
                text("ALTER TABLE moved_away RENAME TO paid_question_attempts")
            )
    assert "settle failed (ProgrammingError)" in caplog.text
    assert "paid_question_attempts" not in caplog.text  # category only, no SQL or table names


async def test_a_cancelled_caller_still_has_its_attempt_freed(pg_engine):
    quota = make_quota(pg_engine)
    attempt = await quota.admit(USER_A)
    task = asyncio.ensure_future(quota.settle(attempt, PaidExecutionMarker()))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await rows(pg_engine, USER_A) == []


# --- lease -----------------------------------------------------------------------------------


async def test_an_expired_lease_stops_blocking_and_a_late_finish_cannot_free_a_later_slot(
    pg_engine,
):
    clock = Clock()
    quota = make_quota(pg_engine, clock)
    old = await quota.admit(USER_A)
    clock.advance(seconds=LEASE - 1)
    assert (await refusal(quota, USER_A)).reason == "concurrent"  # younger than the lease
    clock.advance(seconds=2)
    newer = await quota.admit(USER_A)  # the old one no longer blocks
    await quota.finish(old)  # late finish of the expired attempt
    assert (await refusal(quota, USER_A)).reason == "concurrent"  # the newer slot is still held
    state = {r[0]: r[3] for r in await rows(pg_engine, USER_A)}
    assert state[newer] is None and state[old] is not None


# --- prune -----------------------------------------------------------------------------------


async def test_prune_removes_only_expired_rows_and_never_changes_the_24_hour_count(pg_engine):
    clock = Clock()
    quota = make_quota(pg_engine, clock, paid_question_retention_hours=25)
    finished_old = await quota.admit(USER_A)
    await quota.finish(finished_old)
    orphan_old = await quota.admit(USER_A)  # never finished: an orphan from a crash
    clock.advance(hours=25, minutes=1)
    live = await quota.admit(USER_A)  # unfinished and young
    finished_young = await quota.admit(USER_B)
    await quota.finish(finished_young)
    assert await quota.prune() == 2  # the old finished row and the old orphan
    assert {r[0] for r in await rows(pg_engine)} == {live, finished_young}
    assert finished_old not in {r[0] for r in await rows(pg_engine)}
    assert orphan_old not in {r[0] for r in await rows(pg_engine)}


async def test_prune_keeps_rows_inside_the_retention_and_inside_twice_the_lease(pg_engine):
    clock = Clock()
    quota = make_quota(pg_engine, clock)
    finished = await quota.admit(USER_A)
    await quota.finish(finished)
    await quota.admit(USER_B)
    clock.advance(seconds=2 * LEASE - 1)
    assert await quota.prune() == 0
    clock.advance(seconds=2)
    assert await quota.prune() == 1  # only the orphan is past twice the lease
    assert [r[0] for r in await rows(pg_engine)] == [finished]


# --- schema ----------------------------------------------------------------------------------


async def test_deleting_an_owner_with_ledger_rows_succeeds(pg_engine):
    quota = make_quota(pg_engine)
    await quota.admit(USER_A)
    await quota.admit(USER_B)
    async with async_sessionmaker(pg_engine).begin() as db:
        await db.execute(text("DELETE FROM users WHERE id = :u"), {"u": USER_A})
    assert await rows(pg_engine, USER_A) == [] and len(await rows(pg_engine, USER_B)) == 1


async def test_model_matches_the_migrated_table(pg_engine):
    quota = make_quota(pg_engine)
    attempt = await quota.admit(USER_A)
    async with async_sessionmaker(pg_engine)() as db:
        row = await db.scalar(select(PaidQuestionAttempt).where(PaidQuestionAttempt.id == attempt))
    assert row is not None and row.owner_id == USER_A and row.finished_at is None


def test_alembic_has_a_single_head_and_it_is_this_revision():
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("path_separator", "os")
    assert ScriptDirectory.from_config(config).get_heads() == [PAID_QUESTION_REVISION]


async def test_upgrade_and_downgrade_both_run(pg_engine):
    async with pg_engine.begin() as connection:
        await connection.run_sync(apply_revision, PAID_QUESTION_REVISION, downgrade=True)
        assert await connection.scalar(text("SELECT to_regclass('paid_question_attempts')")) is None
        await connection.run_sync(apply_revision, PAID_QUESTION_REVISION)
        assert await connection.scalar(text("SELECT to_regclass('paid_question_attempts')"))
        indexes = await connection.scalar(
            text(
                "SELECT count(*) FROM pg_indexes WHERE tablename = 'paid_question_attempts' "
                "AND indexname = 'ix_paid_question_attempts_owner_started' "
                "AND schemaname = current_schema()"
            )
        )
        assert indexes == 1


# --- cancellation during admission (follow-up to ticket 05 review) ----------------------------


@pytest.fixture
def slow_commit(monkeypatch):
    """Make the admission commit succeed, then stall before control returns to ``admit``'s caller."""
    from sqlalchemy.ext.asyncio import AsyncSession

    original = AsyncSession.__aexit__
    state = {"committed": asyncio.Event(), "go": asyncio.Event(), "active": True}

    async def aexit(self, *args):
        # Runs inside SQLAlchemy's shielded exit task, after the transaction has committed.
        if state["active"]:
            state["active"] = False  # only the admission's own session stalls
            state["committed"].set()
            await state["go"].wait()
        await original(self, *args)

    monkeypatch.setattr(AsyncSession, "__aexit__", aexit)
    return state


async def test_cancel_after_the_commit_succeeds_leaves_no_row_the_caller_cannot_settle(
    pg_engine, slow_commit
):
    quota = make_quota(pg_engine)
    task = asyncio.ensure_future(quota.admit(USER_A))
    await slow_commit["committed"].wait()  # the row is committed; the caller has no id yet
    assert len(await rows(pg_engine, USER_A)) == 1
    task.cancel()
    slow_commit["go"].set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await rows(pg_engine, USER_A) == []  # released: never counted, slot free
    await quota.admit(USER_A)


async def test_cancel_while_waiting_for_the_owner_lock_leaves_no_row(pg_engine):
    quota = make_quota(pg_engine)
    holder_sessions = async_sessionmaker(pg_engine)
    async with holder_sessions.begin() as holder:
        await holder.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": lock_key(USER_A)}
        )
        task = asyncio.ensure_future(quota.admit(USER_A))
        await asyncio.sleep(0.3)  # blocked on the lock
        task.cancel()
        await asyncio.sleep(0.3)
    # The holder committed inside the lock timeout, so the cancelled admission may have gone on to
    # insert; whatever it did, it must not leave a row behind.
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await rows(pg_engine, USER_A) == []


async def test_cancel_before_the_lock_timeout_expires_leaves_no_row(pg_engine):
    quota = make_quota(pg_engine)
    async with async_sessionmaker(pg_engine).begin() as holder:
        await holder.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": lock_key(USER_A)}
        )
        task = asyncio.ensure_future(quota.admit(USER_A))
        await asyncio.sleep(0.3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task  # waits out the lock timeout (the holder stays), then raises
    assert await rows(pg_engine, USER_A) == []


async def test_a_cancelled_admission_that_was_released_uses_no_hour_or_day_allowance(
    pg_engine, slow_commit
):
    quota = make_quota(pg_engine, paid_question_hour_limit=1, paid_question_day_limit=1)
    task = asyncio.ensure_future(quota.admit(USER_A))
    await slow_commit["committed"].wait()
    task.cancel()
    slow_commit["go"].set()
    with pytest.raises(asyncio.CancelledError):
        await task
    await quota.finish(await quota.admit(USER_A))  # the one hourly and daily question is intact
    assert (await refusal(quota, USER_A)).reason in {"hour", "day"}


async def test_a_refused_admission_that_is_cancelled_leaves_nothing(pg_engine):
    clock = Clock()
    quota = make_quota(pg_engine, clock)
    await quota.admit(USER_A)  # holds the only concurrent slot
    task = asyncio.ensure_future(quota.admit(USER_A))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises((asyncio.CancelledError, QuotaRefused)):
        await task
    assert len(await rows(pg_engine, USER_A)) == 1  # only the first attempt


async def test_an_orphaned_attempt_blocks_only_until_the_lease_but_counts_until_pruned(pg_engine):
    """A row whose id never reached the caller (a double cancellation or a crash)."""
    clock = Clock()
    quota = make_quota(pg_engine, clock, paid_question_hour_limit=2)
    await quota.admit(USER_A)  # orphan: never settled
    clock.advance(seconds=LEASE + 1)
    await quota.finish(await quota.admit(USER_A))  # no longer blocks the concurrent slot
    assert (await refusal(quota, USER_A)).reason == "hour"  # it still counts in the window
    clock.advance(seconds=2 * LEASE)
    assert await quota.prune() == 1  # pruned once past twice the lease


async def test_a_second_cancellation_cannot_leak_the_committed_attempt(pg_engine, slow_commit):
    quota = make_quota(pg_engine)
    task = asyncio.ensure_future(quota.admit(USER_A))
    await slow_commit["committed"].wait()
    task.cancel()
    await asyncio.sleep(0.05)  # now waiting for the admission to end
    task.cancel()  # a second cancellation interrupts that wait
    with pytest.raises(asyncio.CancelledError):
        await task
    slow_commit["go"].set()  # the admission finishes after the caller has gone
    for _ in range(50):
        if not await rows(pg_engine, USER_A):
            break
        await asyncio.sleep(0.1)
    assert await rows(pg_engine, USER_A) == []  # the done-callback released it
