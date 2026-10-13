"""Disposable PostgreSQL constraints and caller-owned conversation transactions."""

import asyncio
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import func, insert, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.enums import ApplicationSessionKind
from app.db.models import ApplicationSession, Conversation, ConversationTurn, QueryHistory
from app.db.models.conversation_turn import TurnOperation, TurnStatus
from app.services.conversation_repository import (
    ConversationBusy,
    ConversationConflict,
    ConversationExecutionLost,
    ConversationNotFound,
    ConversationRepository,
    ConversationVersionConflict,
)
from .conftest import BACKEND, SESSION_REVISION, USER_A, USER_B, DEMO_USER, apply_revision

REVISION = "20261015_1200"
PREVIOUS = "20261014_1200"


@dataclass
class World:
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    principals: dict[UUID, UUID]


@pytest.fixture
async def world(pg_engine):
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("path_separator", "os")
    scripts = ScriptDirectory.from_config(config)
    async with pg_engine.begin() as connection:
        for revision in reversed(list(scripts.iterate_revisions(REVISION, SESSION_REVISION))):
            await connection.run_sync(apply_revision, revision.revision)
    sessions = async_sessionmaker(pg_engine, expire_on_commit=False)
    principals = {}
    async with sessions.begin() as db:
        for owner in (USER_A, USER_B):
            sid = uuid4()
            principals[owner] = sid
            db.add(
                ApplicationSession(
                    id=sid,
                    kind=ApplicationSessionKind.GOOGLE_ACCOUNT,
                    user_id=owner,
                    credential_hash=uuid4().bytes * 2,
                    csrf_secret=b"s" * 32,
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                )
            )
    return World(pg_engine, sessions, principals)


async def create(w, owner=USER_A, request_id=None, title="New chat"):
    async with w.sessions.begin() as db:
        return (
            await ConversationRepository(db).create(owner, request_id or uuid4(), title)
        ).conversation


async def reserve(w, cid, owner=USER_A, request_id=None, **kwargs):
    async with w.sessions.begin() as db:
        repo = ConversationRepository(db)
        row = await repo.get(owner, cid)
        return (
            await repo.reserve(
                owner,
                cid,
                request_id=request_id or uuid4(),
                question="Original question",
                session_id=w.principals[owner],
                expected_content_version=row.content_version,
                **kwargs,
            )
        ).turn


async def failure(w, turn):
    async with w.sessions.begin() as db:
        await ConversationRepository(db).fail(
            turn.owner_id,
            turn.conversation_id,
            turn.id,
            execution_id=turn.execution_id,
            error_code="MODEL_FAILED",
        )


async def result(w, owner=USER_A):
    async with w.sessions.begin() as db:
        row = QueryHistory(
            user_id=owner, question="retrieval question", answer="Saved answer", citations_json=[]
        )
        db.add(row)
        await db.flush()
        return row.id


def turn_values(w, cid, owner=USER_A, **overrides):
    now = datetime.now(timezone.utc)
    return (
        dict(
            id=uuid4(),
            owner_id=owner,
            conversation_id=cid,
            client_request_id=uuid4(),
            payload_hash=b"h" * 32,
            sequence=1,
            original_question="Question",
            operation="ASK",
            history_end_sequence=0,
            status="RUNNING",
            execution_id=uuid4(),
            initiating_session_id=w.principals[owner],
            created_at=now,
            execution_deadline=now + timedelta(minutes=3),
        )
        | overrides
    )


async def assert_insert_fails(w, values, constraint):
    with pytest.raises(IntegrityError) as exc:
        async with w.sessions.begin() as db:
            await db.execute(insert(ConversationTurn).values(values))
    assert exc.value.orig is not None
    assert getattr(exc.value.orig.__cause__, "constraint_name", None) == constraint


async def test_owner_reads_and_foreign_mutations(world):
    a = await create(world)
    b = await create(world, USER_B)
    async with world.sessions.begin() as db:
        repo = ConversationRepository(db)
        assert [c.id for c in await repo.list_owned(USER_A)] == [a.id]
        assert (await repo.get(USER_B, b.id)).id == b.id
    actions = [
        lambda r: r.get(USER_B, a.id),
        lambda r: r.rename(USER_B, a.id, expected_version=1, title="stolen"),
        lambda r: r.delete(USER_B, a.id, expected_version=1),
        lambda r: r.reserve(
            USER_B,
            a.id,
            request_id=uuid4(),
            question="foreign",
            session_id=world.principals[USER_B],
            expected_content_version=0,
        ),
        lambda r: r.turns(USER_B, a.id),
        lambda r: r.request(USER_B, a.id, uuid4()),
    ]
    for action in actions:
        with pytest.raises(ConversationNotFound):
            async with world.sessions.begin() as db:
                await action(ConversationRepository(db))
    async with world.sessions.begin() as db:
        assert (await db.get(Conversation, a.id)).title == "New chat"
        assert await db.scalar(select(func.count()).select_from(ConversationTurn)) == 0


async def test_create_idempotency_and_owner_scope(world):
    key = uuid4()
    a = await create(world, request_id=key, title="A")
    async with world.sessions.begin() as db:
        replay = await ConversationRepository(db).create(USER_A, key, " A ")
        assert replay.replayed and replay.conversation.id == a.id
    with pytest.raises(ConversationConflict):
        await create(world, request_id=key, title="changed")
    b = await create(world, USER_B, key, "B")
    assert b.id != a.id
    with pytest.raises(ConversationNotFound):
        await create(world, DEMO_USER)


async def test_repository_never_commits_caller_work(world):
    key = uuid4()
    async with world.sessions() as db:
        async with db.begin():
            await ConversationRepository(db).create(USER_A, key)
            async with world.sessions() as observer:
                assert (
                    await observer.scalar(
                        select(Conversation.id).where(Conversation.create_request_id == key)
                    )
                    is None
                )
        async with world.sessions() as observer:
            assert (
                await observer.scalar(
                    select(Conversation.id).where(Conversation.create_request_id == key)
                )
                is not None
            )
    with pytest.raises(RuntimeError):
        async with world.sessions() as db:
            await ConversationRepository(db).list_owned(USER_A)
    rollback_key = uuid4()
    with pytest.raises(RuntimeError, match="caller rollback"):
        async with world.sessions.begin() as db:
            await ConversationRepository(db).create(USER_A, rollback_key)
            raise RuntimeError("caller rollback")
    async with world.sessions() as db:
        assert (
            await db.scalar(
                select(Conversation.id).where(Conversation.create_request_id == rollback_key)
            )
            is None
        )


async def test_direct_owner_and_session_constraints(world):
    a = await create(world)
    await assert_insert_fails(
        world, turn_values(world, a.id, USER_B), "fk_turns_conversation_owner"
    )
    await assert_insert_fails(
        world,
        turn_values(world, a.id, initiating_session_id=world.principals[USER_B]),
        "fk_turns_session_owner",
    )


async def test_foreign_result_and_source_constraints(world):
    a = await create(world)
    b = await create(world, USER_B)
    other = await create(world)
    bt = await reserve(world, b.id, USER_B)
    at = await reserve(world, other.id)
    rid = await result(world, USER_B)
    await assert_insert_fails(
        world,
        turn_values(
            world,
            a.id,
            status="COMPLETED",
            query_history_id=rid,
            finished_at=datetime.now(timezone.utc),
        ),
        "fk_turns_result_owner",
    )
    for source in (bt.id, at.id):
        await assert_insert_fails(
            world,
            turn_values(world, a.id, operation="REGENERATE", source_turn_id=source),
            "fk_turns_source_owner",
        )
    with pytest.raises(ConversationNotFound):
        await reserve(world, a.id, operation=TurnOperation.RETRY, source_turn_id=bt.id)


@pytest.mark.parametrize(
    "status,result_present,error",
    [
        ("COMPLETED", False, None),
        ("FAILED", True, "MODEL_FAILED"),
        ("INTERRUPTED", True, "INTERRUPTED"),
    ],
)
async def test_result_status_consistency(world, status, result_present, error):
    a = await create(world)
    rid = await result(world) if result_present else None
    await assert_insert_fails(
        world,
        turn_values(
            world,
            a.id,
            status=status,
            query_history_id=rid,
            finished_at=datetime.now(timezone.utc),
            error_code=error,
        ),
        "ck_turns_result",
    )


@pytest.mark.parametrize(
    "field,value,constraint",
    [
        ("retrieval_count", -1, "ck_turns_retrieval_count"),
        ("sequence", 0, "ck_turns_sequence"),
        ("history_end_sequence", 1, "ck_turns_sequence"),
        ("original_question", "\t \n", "ck_turns_question"),
        ("payload_hash", b"x", "ck_turns_payload_hash"),
        ("status", "UNKNOWN", "ck_turns_status"),
    ],
)
async def test_invalid_turn_values(world, field, value, constraint):
    a = await create(world)
    # Unknown status also violates terminal state; isolate the explicit enum check by catalog assertion below.
    if field == "status":
        with pytest.raises(IntegrityError):
            async with world.sessions.begin() as db:
                await db.execute(
                    insert(ConversationTurn).values(turn_values(world, a.id, **{field: value}))
                )
    else:
        await assert_insert_fails(world, turn_values(world, a.id, **{field: value}), constraint)


async def test_lifecycle_result_and_request_replay(world):
    a = await create(world)
    key = uuid4()
    turn = await reserve(world, a.id, request_id=key)
    async with world.sessions.begin() as db:
        repo = ConversationRepository(db)
        replay = await repo.reserve(
            USER_A,
            a.id,
            request_id=key,
            question="Original question",
            session_id=world.principals[USER_A],
            expected_content_version=0,
        )
        assert replay.replayed and replay.turn.id == turn.id
    with pytest.raises(ConversationConflict):
        async with world.sessions.begin() as db:
            await ConversationRepository(db).reserve(
                USER_A,
                a.id,
                request_id=key,
                question="different",
                session_id=world.principals[USER_A],
                expected_content_version=0,
            )
    async with world.sessions.begin() as db:
        q = QueryHistory(
            id=uuid4(), user_id=USER_A, question="rewritten", answer="canonical", citations_json=[]
        )
        db.add(q)
        done = await ConversationRepository(db).complete(
            USER_A, a.id, turn.id, execution_id=turn.execution_id, result_id=q.id, retrieval_count=3
        )
        assert done.status == TurnStatus.COMPLETED and done.original_question == "Original question"
    async with world.sessions.begin() as db:
        repo = ConversationRepository(db)
        saved = await repo.request(USER_A, a.id, key)
        assert saved is not None
        assert saved.query_history_id == q.id and saved.retrieval_count == 3
        canonical = await repo.result(USER_A, a.id, key)
        assert canonical is not None and canonical.answer == "canonical"
        assert await db.scalar(select(func.count()).select_from(QueryHistory)) == 1
    with pytest.raises(ConversationExecutionLost):
        await failure(world, turn)
    retry = await reserve(world, a.id, operation=TurnOperation.REGENERATE, source_turn_id=turn.id)
    assert retry.sequence == 2 and retry.history_end_sequence == 0
    await failure(world, retry)


async def test_wrong_execution_and_foreign_result_no_publication(world):
    a = await create(world)
    turn = await reserve(world, a.id)
    rid = await result(world, USER_B)
    for claim, error in (
        (uuid4(), ConversationExecutionLost),
        (turn.execution_id, ConversationNotFound),
    ):
        with pytest.raises(error):
            async with world.sessions.begin() as db:
                await ConversationRepository(db).complete(
                    USER_A, a.id, turn.id, execution_id=claim, result_id=rid, retrieval_count=1
                )
    async with world.sessions() as db:
        assert (await db.get(ConversationTurn, turn.id)).status == TurnStatus.RUNNING


async def test_metadata_and_tombstone_fence(world):
    a = await create(world)
    turn = await reserve(world, a.id)
    async with world.sessions.begin() as db:
        renamed = await ConversationRepository(db).rename(
            USER_A, a.id, expected_version=1, title="Renamed"
        )
        assert renamed.title_is_manual and renamed.metadata_version == 2
    with pytest.raises(ConversationVersionConflict):
        async with world.sessions.begin() as db:
            await ConversationRepository(db).rename(USER_A, a.id, expected_version=1, title="stale")
    async with world.sessions.begin() as db:
        await ConversationRepository(db).delete(USER_A, a.id, expected_version=2)
    for action in (
        lambda r: r.get(USER_A, a.id),
        lambda r: r.turns(USER_A, a.id),
        lambda r: r.create(USER_A, a.create_request_id),
        lambda r: r.complete(
            USER_A,
            a.id,
            turn.id,
            execution_id=turn.execution_id,
            result_id=uuid4(),
            retrieval_count=0,
        ),
    ):
        with pytest.raises(ConversationNotFound):
            async with world.sessions.begin() as db:
                await action(ConversationRepository(db))
    with pytest.raises(ConversationNotFound):
        await reserve(world, a.id)
    async with world.sessions() as db:
        assert (await db.get(ConversationTurn, turn.id)).status == TurnStatus.INTERRUPTED
        assert (await db.get(Conversation, a.id)).deleted_at is not None
        assert await db.scalar(select(func.count()).select_from(QueryHistory)) == 0


async def test_turn_identity_is_immutable_in_postgresql(world):
    a = await create(world)
    turn = await reserve(world, a.id)
    with pytest.raises(IntegrityError, match="identity is immutable"):
        async with world.sessions.begin() as db:
            await db.execute(
                update(ConversationTurn)
                .where(ConversationTurn.id == turn.id)
                .values(original_question="replacement")
            )
    await failure(world, turn)  # Terminal state transitions remain valid.


async def test_ordered_pagination_and_content_conflict(world):
    a = await create(world)
    for _ in range(3):
        turn = await reserve(world, a.id)
        await failure(world, turn)
    async with world.sessions.begin() as db:
        repo = ConversationRepository(db)
        assert [t.sequence for t in await repo.turns(USER_A, a.id, limit=2)] == [2, 3]
        assert [t.sequence for t in await repo.turns(USER_A, a.id, before_sequence=2)] == [1]
    with pytest.raises(ConversationVersionConflict):
        async with world.sessions.begin() as db:
            await ConversationRepository(db).reserve(
                USER_A,
                a.id,
                request_id=uuid4(),
                question="stale",
                session_id=world.principals[USER_A],
                expected_content_version=0,
            )


async def wait_for_database_lock(w, pid):
    # Observe actual PostgreSQL lock wait, bounded by timeout, with no timing sleep.
    async with asyncio.timeout(5):
        async with w.sessions() as db:
            while True:
                await db.execute(text("SELECT pg_stat_clear_snapshot()"))
                waiting = await db.scalar(
                    text("SELECT wait_event_type = 'Lock' FROM pg_stat_activity WHERE pid=:pid"),
                    {"pid": pid},
                )
                if waiting:
                    return
                await asyncio.sleep(0)


async def test_concurrent_reservation_and_independent_owner(world):
    a = await create(world)
    b = await create(world, USER_B)
    started = asyncio.Event()
    release = asyncio.Event()
    blocked_pid = asyncio.Future()

    async def first():
        async with world.sessions.begin() as db:
            r = await ConversationRepository(db).reserve(
                USER_A,
                a.id,
                request_id=uuid4(),
                question="first",
                session_id=world.principals[USER_A],
                expected_content_version=0,
            )
            started.set()
            await release.wait()
            return r.turn

    async def second():
        await started.wait()
        async with world.sessions.begin() as db:
            blocked_pid.set_result(await db.scalar(select(func.pg_backend_pid())))
            return await ConversationRepository(db).reserve(
                USER_A,
                a.id,
                request_id=uuid4(),
                question="second",
                session_id=world.principals[USER_A],
                expected_content_version=0,
            )

    one = asyncio.create_task(first())
    two = asyncio.create_task(second())
    try:
        await wait_for_database_lock(world, await asyncio.wait_for(blocked_pid, 5))
        bt = await asyncio.wait_for(reserve(world, b.id, USER_B), 5)
        assert bt.sequence == 1
        release.set()
        at = await one
        with pytest.raises(ConversationBusy):
            await two
        await failure(world, at)
        later = await reserve(world, a.id)
        assert later.sequence == 2
        async with world.sessions() as db:
            assert list(
                (
                    await db.scalars(
                        select(ConversationTurn.sequence)
                        .where(ConversationTurn.conversation_id == a.id)
                        .order_by(ConversationTurn.sequence)
                    )
                ).all()
            ) == [1, 2]
    finally:
        release.set()
        await asyncio.gather(one, two, return_exceptions=True)


async def test_database_running_and_request_unique_indices(world):
    a = await create(world)
    turn = await reserve(world, a.id)
    await assert_insert_fails(
        world, turn_values(world, a.id, sequence=2), "uq_turns_running_conversation"
    )
    await failure(world, turn)
    await assert_insert_fails(
        world,
        turn_values(world, a.id, sequence=2, client_request_id=turn.client_request_id),
        "uq_turns_owner_request",
    )
    await assert_insert_fails(
        world, turn_values(world, a.id, sequence=1), "uq_turns_conversation_sequence"
    )


async def test_empty_downgrade_and_populated_refusal(world):
    async with world.engine.begin() as connection:
        await connection.run_sync(apply_revision, REVISION, downgrade=True)
        assert await connection.scalar(text("SELECT to_regclass('conversations')")) is None
        assert (
            await connection.scalar(
                text("SELECT to_regprocedure('conversation_owner_immutable()')")
            )
            is None
        )
        await connection.run_sync(apply_revision, REVISION)
        assert (
            await connection.scalar(
                text("SELECT to_regprocedure('conversation_owner_immutable()')")
            )
            is not None
        )
    a = await create(world)
    with pytest.raises(RuntimeError, match="Retain conversation"):
        async with world.engine.begin() as connection:
            await connection.run_sync(apply_revision, REVISION, downgrade=True)
    async with world.sessions() as db:
        assert (await db.get(Conversation, a.id)).id == a.id


async def test_actual_alembic_populated_upgrade_and_downgrade(pg_engine):
    # This new container's public schema is separate from per-test schemas.
    base_url = os.environ["SESSION_TEST_DATABASE_URL"]
    name = "drivemind_session_test_migration_" + uuid4().hex
    admin = create_async_engine(base_url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as db:
        await db.execute(text(f'CREATE DATABASE "{name}"'))
    raw = make_url(base_url).set(database=name).render_as_string(hide_password=False)
    env = os.environ | {"DATABASE_URL": raw}

    async def alembic(*args):
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "alembic",
            *args,
            cwd=BACKEND,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        return proc.returncode, (out + err).decode()

    code, output = await alembic("upgrade", PREVIOUS)
    assert code == 0, output
    engine = create_async_engine(raw)
    try:
        async with engine.begin() as db:
            await db.execute(
                text(
                    "INSERT INTO users(id,email,google_id) VALUES (:id,'old@example.invalid','old-subject')"
                ),
                {"id": USER_A},
            )
            await db.execute(
                text(
                    "INSERT INTO query_history(id,user_id,question,answer,citations_json) VALUES (:id,:owner,'old question','old answer','[]')"
                ),
                {"id": uuid4(), "owner": USER_A},
            )
            await db.execute(
                text(
                    "INSERT INTO google_oauth_tokens(id,user_id,encrypted_credentials,scopes) VALUES (:id,:owner,'synthetic-envelope','synthetic-scope')"
                ),
                {"id": uuid4(), "owner": USER_A},
            )
            await db.execute(
                text("INSERT INTO indexing_jobs(id,user_id,status) VALUES (:id,:owner,'FAILED')"),
                {"id": uuid4(), "owner": USER_A},
            )
            before = {
                table: list(
                    (
                        await db.execute(text(f"SELECT to_jsonb(t) FROM {table} t ORDER BY id"))
                    ).scalars()
                )
                for table in ("users", "query_history", "google_oauth_tokens", "indexing_jobs")
            }
        code, output = await alembic("upgrade", "head")
        assert code == 0, output
        async with engine.begin() as db:
            after = {
                table: list(
                    (
                        await db.execute(text(f"SELECT to_jsonb(t) FROM {table} t ORDER BY id"))
                    ).scalars()
                )
                for table in before
            }
            assert before == after
            assert await db.scalar(text("SELECT version_num FROM alembic_version")) == REVISION
            assert await db.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid='conversations'::regclass "
                    "AND tgname='trg_conversation_owner_immutable' AND tgenabled='O' AND NOT tgisinternal)"
                )
            )
            constraints = set(
                (
                    await db.execute(
                        text(
                            "SELECT conname FROM pg_constraint WHERE conrelid='conversation_turns'::regclass"
                        )
                    )
                ).scalars()
            )
            assert {
                "fk_turns_conversation_owner",
                "fk_turns_result_owner",
                "fk_turns_source_owner",
                "ck_turns_result",
                "ck_turns_status",
            } <= constraints
            await db.execute(
                text(
                    "INSERT INTO conversations(owner_id,create_request_id,create_payload_hash) VALUES (:owner,:key,:hash)"
                ),
                {"owner": USER_A, "key": uuid4(), "hash": b"h" * 32},
            )
        code, output = await alembic("downgrade", PREVIOUS)
        assert code != 0 and "Retain conversation" in output
        async with engine.connect() as db:
            assert await db.scalar(text("SELECT version_num FROM alembic_version")) == REVISION
            assert await db.scalar(text("SELECT count(*) FROM conversations")) == 1
    finally:
        await engine.dispose()
        async with admin.connect() as db:
            await db.execute(text(f'DROP DATABASE "{name}"'))
        await admin.dispose()


def test_turn_http_present_without_indexing_activation():
    from app.main import create_app
    from app.core.config import Settings

    paths = create_app().openapi()["paths"]
    assert "/api/v1/conversations/{conversation_id}/turns" in paths
    assert "indexing_runtime_enabled" not in Settings.model_fields


async def test_concurrent_sequence_allocation_after_prior_terminal(world):
    a = await create(world)
    first_reserved = asyncio.Event()
    release = asyncio.Event()
    pid = asyncio.Future()

    async def first():
        async with world.sessions.begin() as db:
            repo = ConversationRepository(db)
            turn = (
                await repo.reserve(
                    USER_A,
                    a.id,
                    request_id=uuid4(),
                    question="first",
                    session_id=world.principals[USER_A],
                    expected_content_version=0,
                )
            ).turn
            await repo.fail(
                USER_A, a.id, turn.id, execution_id=turn.execution_id, error_code="MODEL_FAILED"
            )
            first_reserved.set()
            await release.wait()
            return turn.sequence

    async def second():
        await first_reserved.wait()
        async with world.sessions.begin() as db:
            pid.set_result(await db.scalar(select(func.pg_backend_pid())))
            turn = (
                await ConversationRepository(db).reserve(
                    USER_A,
                    a.id,
                    request_id=uuid4(),
                    question="second",
                    session_id=world.principals[USER_A],
                    expected_content_version=2,
                )
            ).turn
            return turn.sequence

    one, two = asyncio.create_task(first()), asyncio.create_task(second())
    try:
        await wait_for_database_lock(world, await asyncio.wait_for(pid, 5))
        release.set()
        assert await asyncio.gather(one, two) == [1, 2]
    finally:
        release.set()
        await asyncio.gather(one, two, return_exceptions=True)


async def test_expiry_after_lock_wait_rejects_dirty_result_without_autoflush(world):
    a = await create(world)
    turn = await reserve(world, a.id, execution_seconds=1)
    pid = asyncio.Future()
    rid = uuid4()

    async def finalize():
        async with world.sessions.begin() as db:
            db.add(
                QueryHistory(
                    id=rid,
                    user_id=USER_A,
                    question="pending",
                    answer="not published",
                    citations_json=[],
                )
            )
            with db.no_autoflush:
                pid.set_result(await db.scalar(select(func.pg_backend_pid())))
            return await ConversationRepository(db).complete(
                USER_A,
                a.id,
                turn.id,
                execution_id=turn.execution_id,
                result_id=rid,
                retrieval_count=0,
            )

    async with world.sessions.begin() as lock:
        await lock.execute(select(Conversation.id).where(Conversation.id == a.id).with_for_update())
        task = asyncio.create_task(finalize())
        try:
            await wait_for_database_lock(world, await asyncio.wait_for(pid, 5))
            async with world.sessions() as observer:
                assert await observer.get(QueryHistory, rid) is None
            # Explicit database-clock passage to the captured deadline while holding
            # an unchanged row. This is not an arbitrary race-test sleep.
            await lock.execute(
                text(
                    "SELECT pg_sleep(GREATEST(0, EXTRACT(EPOCH FROM (:deadline - clock_timestamp())) + 0.05))"
                ),
                {"deadline": turn.execution_deadline},
            )
        except BaseException:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise
    with pytest.raises(ConversationExecutionLost):
        await task
    async with world.sessions() as db:
        assert await db.get(QueryHistory, rid) is None
        assert (await db.get(ConversationTurn, turn.id)).status == TurnStatus.RUNNING


async def test_turn_request_keys_are_owner_scoped(world):
    a = await create(world)
    b = await create(world, USER_B)
    key = uuid4()
    at = await reserve(world, a.id, request_id=key)
    bt = await reserve(world, b.id, USER_B, request_id=key)
    assert at.id != bt.id
    other_a = await create(world)
    with pytest.raises(ConversationConflict):
        await reserve(world, other_a.id, request_id=key)


async def test_concurrent_create_is_one_record(world):
    key = uuid4()
    ready, release = asyncio.Event(), asyncio.Event()
    pid = asyncio.Future()

    async def first():
        async with world.sessions.begin() as db:
            created = await ConversationRepository(db).create(USER_A, key)
            ready.set()
            await release.wait()
            return created

    async def second():
        await ready.wait()
        async with world.sessions.begin() as db:
            pid.set_result(await db.scalar(select(func.pg_backend_pid())))
            return await ConversationRepository(db).create(USER_A, key)

    one, two = asyncio.create_task(first()), asyncio.create_task(second())
    try:
        await wait_for_database_lock(world, await asyncio.wait_for(pid, 5))
        release.set()
        a, b = await asyncio.gather(one, two)
        assert a.conversation.id == b.conversation.id and not a.replayed and b.replayed
    finally:
        release.set()
        await asyncio.gather(one, two, return_exceptions=True)


@pytest.mark.parametrize("method", ["turns", "request", "result"])
async def test_tombstone_between_visibility_check_and_history_read(world, monkeypatch, method):
    a = await create(world)
    turn = await reserve(world, a.id)
    rid = await result(world)
    async with world.sessions.begin() as db:
        await ConversationRepository(db).complete(
            USER_A, a.id, turn.id, execution_id=turn.execution_id, result_id=rid, retrieval_count=0
        )
    checked, release = asyncio.Event(), asyncio.Event()

    async def read():
        async with world.sessions.begin() as db:
            repo = ConversationRepository(db)
            native = repo.get

            async def blocked(owner, cid):
                row = await native(owner, cid)
                checked.set()
                await release.wait()
                return row

            monkeypatch.setattr(repo, "get", blocked)
            if method == "turns":
                return await repo.turns(USER_A, a.id)
            return await getattr(repo, method)(USER_A, a.id, turn.client_request_id)

    task = asyncio.create_task(read())
    try:
        await asyncio.wait_for(checked.wait(), 5)
        async with world.sessions.begin() as db:
            await ConversationRepository(db).delete(USER_A, a.id, expected_version=1)
        release.set()
        assert await task == ([] if method == "turns" else None)
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


async def test_tombstone_between_request_and_result_lookup(world, monkeypatch):
    a = await create(world)
    turn = await reserve(world, a.id)
    rid = await result(world)
    async with world.sessions.begin() as db:
        await ConversationRepository(db).complete(
            USER_A, a.id, turn.id, execution_id=turn.execution_id, result_id=rid, retrieval_count=0
        )
    checked, release = asyncio.Event(), asyncio.Event()

    async def read():
        async with world.sessions.begin() as db:
            repo = ConversationRepository(db)
            native = repo.request

            async def blocked(owner, cid, key):
                row = await native(owner, cid, key)
                checked.set()
                await release.wait()
                return row

            monkeypatch.setattr(repo, "request", blocked)
            return await repo.result(USER_A, a.id, turn.client_request_id)

    task = asyncio.create_task(read())
    try:
        await asyncio.wait_for(checked.wait(), 5)
        async with world.sessions.begin() as db:
            await ConversationRepository(db).delete(USER_A, a.id, expected_version=1)
        release.set()
        assert await task is None
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("with_turn", [False, True], ids=["empty", "with-turn"])
@pytest.mark.parametrize("transport", ["sql", "orm"])
async def test_conversation_owner_is_immutable(world, with_turn, transport):
    conversation = await create(world)
    if with_turn:
        await reserve(world, conversation.id)
    async with world.sessions() as db:
        before = dict(
            (
                await db.execute(
                    select(Conversation.__table__).where(Conversation.id == conversation.id)
                )
            )
            .mappings()
            .one()
        )
    with pytest.raises(IntegrityError, match="Conversation owner is immutable") as error:
        async with world.sessions.begin() as db:
            if transport == "sql":
                await db.execute(
                    text("UPDATE conversations SET owner_id=:owner WHERE id=:id"),
                    {"owner": USER_B, "id": conversation.id},
                )
            else:
                row = await db.get(Conversation, conversation.id)
                assert row is not None
                row.owner_id = USER_B
                await db.flush()
    assert error.value.orig is not None
    assert getattr(error.value.orig, "sqlstate", None) == "23514"
    async with world.sessions.begin() as db:
        after = dict(
            (
                await db.execute(
                    select(Conversation.__table__).where(Conversation.id == conversation.id)
                )
            )
            .mappings()
            .one()
        )
        assert after == before  # Includes ownership, timestamps and all versions.
        assert (await ConversationRepository(db).get(USER_A, conversation.id)).owner_id == USER_A
    with pytest.raises(ConversationNotFound):
        async with world.sessions.begin() as db:
            await ConversationRepository(db).get(USER_B, conversation.id)


async def test_same_owner_updates_and_lifecycle_remain_valid(world):
    conversation = await create(world)
    async with world.sessions.begin() as db:
        await db.execute(
            text("""
            UPDATE conversations SET owner_id=:owner, title='Same owner',
                updated_at=clock_timestamp(), last_activity_at=clock_timestamp(),
                metadata_version=metadata_version+1, content_version=content_version+1
            WHERE id=:id
        """),
            {"owner": USER_A, "id": conversation.id},
        )
        row = await db.get(Conversation, conversation.id)
        assert row is not None
        row.owner_id = USER_A  # ORM no-op owner assignment is also permitted.
        row.title = "ORM title"
        await db.flush()
        renamed = await ConversationRepository(db).rename(
            USER_A, conversation.id, expected_version=2, title="Repository title"
        )
        assert renamed.metadata_version == 3 and renamed.content_version == 1
    turn = await reserve(world, conversation.id)
    await failure(world, turn)
    async with world.sessions.begin() as db:
        await ConversationRepository(db).delete(USER_A, conversation.id, expected_version=3)
    async with world.sessions() as db:
        row = await db.get(Conversation, conversation.id)
        assert row is not None and row.owner_id == USER_A
        assert row.deleted_at is not None and row.metadata_version == 4
        saved = await db.get(ConversationTurn, turn.id)
        assert saved is not None and saved.status == TurnStatus.FAILED


async def test_joined_turn_page_binds_owned_results(world):
    conversations = {}
    for owner in (USER_A, USER_B):
        conversations[owner] = await create(world, owner)
        turn = await reserve(world, conversations[owner].id, owner)
        rid = await result(world, owner)
        async with world.sessions.begin() as db:
            await ConversationRepository(db).complete(
                owner,
                turn.conversation_id,
                turn.id,
                execution_id=turn.execution_id,
                result_id=rid,
                retrieval_count=1,
            )
    async with world.sessions.begin() as db:
        page = await ConversationRepository(db).turns_with_results(
            USER_A, conversations[USER_A].id, limit=1
        )
        assert len(page) == 1
        turn, history = page[0]
        assert turn.owner_id == USER_A and history is not None and history.user_id == USER_A
    with pytest.raises(ConversationNotFound):
        async with world.sessions.begin() as db:
            await ConversationRepository(db).turns_with_results(USER_B, conversations[USER_A].id)
