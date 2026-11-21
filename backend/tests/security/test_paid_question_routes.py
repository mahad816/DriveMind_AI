"""M0-SEC ticket 06: the paid-question quota on POST /chat, conversation turns and streaming.

Real PostgreSQL (disposable), real application sessions and the mounted routes. The model is a
counting fake that calls ``mark_paid_started()`` the way each provider chokepoint does, so a
question "counts" exactly when the fake provider was reached. No network, no key, no paid call.
"""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import Depends
from sqlalchemy import select, text

from app.api.chat import get_rag_service
from app.api.conversations import get_conversation_chat_service
from app.core.config import Settings, get_settings
from app.core.paid_execution import mark_paid_started
from app.llm.base import ChatError
from app.db.models.paid_question_attempt import PaidQuestionAttempt
from app.db.session import get_db
from app.services.conversation_chat_service import ConversationChatService
from app.services.paid_question_quota import PaidQuestionQuota, QuotaUnavailable, lock_key
from app.services.rag_service import RagResult
from .conftest import USER_A, USER_B
from .test_conversation_api import BASE, api, world
from .test_conversation_repository import create

__all__ = ["api", "world"]

CHAT = "/api/v1/chat"
ROUTES = ["chat", "turn", "stream"]


@pytest.fixture
async def meter(api):
    """A counting fake provider for every answering route, with controllable behavior."""
    control = SimpleNamespace(
        calls=[],
        started=asyncio.Event(),
        release=None,
        error=None,
        mark=True,  # False models a zero-call route (history recall, file not found)
        mark_twice=False,
        delay=0.0,
        in_child=False,  # the provider request happens in a child task, as parallel retrievers do
        timeout=120.0,
        lease=180,
        before_mark=None,  # an event awaited before the provider is reached
    )

    class FakeRag:
        persist_query_history = False

        def __init__(self, db=None, settings=None):
            self.db = db

        async def ask(self, question, user_id, **kwargs):
            if control.before_mark is not None:
                await control.before_mark.wait()
            if control.mark and control.in_child:

                async def child() -> None:
                    mark_paid_started()  # runs in a task created inside the attempt's context

                await asyncio.ensure_future(child())
            elif control.mark:
                mark_paid_started()
                if control.mark_twice:
                    mark_paid_started()  # the intent gate, rewrite, claim check, retries
            control.calls.append(question)
            control.started.set()
            if control.delay:
                await asyncio.sleep(control.delay)
            if control.release is not None:
                await control.release.wait()
            if control.error is not None:
                raise control.error
            return RagResult(
                query_id=uuid4(),
                user_id=user_id,
                question=question,
                answer="Canonical answer",
                citations=[],
                retrieval_count=0,
            )

    def chat_service(
        db=Depends(get_db),
        settings: Settings = Depends(get_settings),
    ):
        return ConversationChatService(
            db,
            settings,
            rag_factory=cast(Any, FakeRag),
            generation_timeout=control.timeout,
            execution_seconds=control.lease,
        )

    api.app.dependency_overrides[get_conversation_chat_service] = chat_service
    api.app.dependency_overrides[get_rag_service] = lambda: FakeRag()
    api.settings.chat_streaming_enabled = True
    api.settings.tool_rag_agent_enabled = True
    return control


async def ledger(api, owner=USER_A):
    async with api.world.sessions() as db:
        rows = (
            await db.scalars(
                select(PaidQuestionAttempt)
                .where(PaidQuestionAttempt.owner_id == owner)
                .order_by(PaidQuestionAttempt.started_at)
            )
        ).all()
    return rows


def turn_body(key=None, question="A question", version=0):
    return {
        "client_request_id": str(key or uuid4()),
        "question": question,
        "expected_content_version": version,
    }


async def ask(api, route, owner=USER_A, *, key=None, cid=None, question="A question"):
    headers = api.headers[owner]
    if route == "chat":
        return await api.client.post(CHAT, json={"question": question}, headers=headers)
    cid = cid or (await create(api.world, owner)).id
    suffix = "/turns" if route == "turn" else "/turns/stream"
    return await api.client.post(
        f"{BASE}/{cid}{suffix}", json=turn_body(key, question), headers=headers
    )


def stream_events(response) -> list[tuple[str, dict]]:
    events, name = [], None
    for line in response.text.splitlines():
        if line.startswith("event: "):
            name = line[7:]
        elif line.startswith("data: ") and name:
            events.append((name, json.loads(line[6:])))
    return events


def succeeded(route, response) -> bool:
    if route == "stream":
        return response.status_code == 200 and stream_events(response)[-1][0] == "complete"
    return response.status_code == 200


def set_limits(api, *, hour=20, day=50, concurrent=1):
    api.settings.paid_question_hour_limit = hour
    api.settings.paid_question_day_limit = day
    api.settings.paid_question_concurrent_limit = concurrent


# ---- refusal before any provider call -----------------------------------------------------


@pytest.mark.parametrize("tool_agent", [True, False])
@pytest.mark.parametrize("route", ROUTES)
async def test_hour_limit_refuses_before_the_provider_with_retry_after(
    api, meter, route, tool_agent
):
    if route == "stream" and not tool_agent:
        pytest.skip("Streaming is tool-agent only")
    api.settings.tool_rag_agent_enabled = tool_agent
    set_limits(api, hour=2)
    for _ in range(2):
        assert succeeded(route, await ask(api, route))
    refused = await ask(api, route)
    assert refused.status_code == 429, refused.text
    assert "hour" in refused.json()["detail"].lower()
    assert 1 <= int(refused.headers["retry-after"]) <= 3600
    assert len(meter.calls) == 2
    assert len(await ledger(api)) == 2


@pytest.mark.parametrize("route", ROUTES)
async def test_day_limit_refuses_before_the_provider_with_retry_after(api, meter, route):
    set_limits(api, hour=20, day=2)
    for _ in range(2):
        assert succeeded(route, await ask(api, route))
    refused = await ask(api, route)
    assert refused.status_code == 429, refused.text
    assert "day" in refused.json()["detail"].lower() or "daily" in refused.json()["detail"].lower()
    assert 1 <= int(refused.headers["retry-after"]) <= 86400
    assert len(meter.calls) == 2


@pytest.mark.parametrize("route", ROUTES)
async def test_concurrent_limit_refuses_a_second_question_then_admits_after_it_ends(
    api, meter, route
):
    meter.release = asyncio.Event()
    first = asyncio.create_task(ask(api, route))
    await asyncio.wait_for(meter.started.wait(), 5)
    refused = await ask(api, route)
    assert refused.status_code == 429, refused.text
    assert int(refused.headers["retry-after"]) >= 1
    assert "another question" in refused.json()["detail"].lower()
    assert len(meter.calls) == 1
    meter.release.set()
    assert succeeded(route, await first)
    assert succeeded(route, await ask(api, route))
    assert len(meter.calls) == 2


@pytest.mark.parametrize("route", ROUTES)
async def test_two_simultaneous_questions_run_exactly_one(api, meter, route):
    meter.delay = 0.3
    one, two = await asyncio.gather(ask(api, route), ask(api, route))
    codes = sorted([one.status_code, two.status_code])
    assert codes == [200, 429], (one.text, two.text)
    assert len(meter.calls) == 1
    assert len(await ledger(api)) == 1


async def test_refusal_leaves_no_turn_and_no_query_history(api, meter):
    set_limits(api, hour=1)
    assert succeeded("turn", await ask(api, "turn"))
    cid = (await create(api.world)).id
    refused = await ask(api, "turn", cid=cid)
    assert refused.status_code == 429
    async with api.world.sessions() as db:
        turns = await db.scalar(text("SELECT count(*) FROM conversation_turns"))
        history = await db.scalar(text("SELECT count(*) FROM query_history"))
    assert turns == 1 and history == 1


# ---- counting ------------------------------------------------------------------------------


@pytest.mark.parametrize("route", ROUTES)
async def test_one_question_is_one_finished_row_whatever_its_internal_calls(api, meter, route):
    meter.mark_twice = True
    assert succeeded(route, await ask(api, route))
    rows = await ledger(api)
    assert len(rows) == 1 and rows[0].finished_at is not None


@pytest.mark.parametrize("route", ROUTES)
async def test_a_zero_call_route_answers_and_counts_nothing(api, meter, route):
    meter.mark = False
    assert succeeded(route, await ask(api, route))
    assert await ledger(api) == []


@pytest.mark.parametrize("route", ROUTES)
async def test_provider_error_after_the_first_request_counts_and_frees_the_slot(api, meter, route):
    meter.error = ChatError("provider-private-body")
    failed = await ask(api, route)
    assert not succeeded(route, failed)
    assert "provider-private" not in failed.text
    rows = await ledger(api)
    assert len(rows) == 1 and rows[0].finished_at is not None
    meter.error = None
    assert succeeded(route, await ask(api, route))  # the slot is free again


@pytest.mark.parametrize("route", ROUTES)
async def test_failure_before_the_first_request_is_released_not_counted(api, meter, route):
    meter.mark = False
    meter.error = ChatError("fails before any provider request")
    assert not succeeded(route, await ask(api, route))
    assert await ledger(api) == []


@pytest.mark.parametrize("route", ["chat", "turn"])
@pytest.mark.parametrize("after_start", [True, False])
async def test_cancellation_settles_the_attempt(api, meter, route, after_start):
    meter.release = asyncio.Event()
    if not after_start:
        meter.before_mark = asyncio.Event()
    pending = asyncio.create_task(ask(api, route))
    if after_start:
        await asyncio.wait_for(meter.started.wait(), 5)
    else:
        async with asyncio.timeout(5):
            while not await ledger(api):
                await asyncio.sleep(0.01)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    async with asyncio.timeout(10):
        while True:
            rows = await ledger(api)
            if (after_start and rows and rows[0].finished_at) or (not after_start and not rows):
                break
            await asyncio.sleep(0.05)
    assert (len(rows) == 1) is after_start  # a started attempt still counts; an unstarted one not


async def test_a_client_that_leaves_before_the_stream_starts_holds_the_slot_until_the_lease(
    api, meter
):
    """Documented residual risk: the stream body never runs, so nothing settles the attempt."""
    cid = (await create(api.world)).id
    body = json.dumps(turn_body()).encode()
    sent = {"done": False}

    async def receive():
        if not sent["done"]:
            sent["done"] = True
            return {"type": "http.request", "body": body, "more_body": False}
        await asyncio.sleep(3600)
        return {"type": "http.disconnect"}

    async def send(message):
        raise OSError("client is gone")

    headers = [(k.lower().encode(), v.encode()) for k, v in api.headers[USER_A].items()]
    headers += [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
    ]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "POST",
        "path": f"{BASE}/{cid}/turns/stream",
        "raw_path": f"{BASE}/{cid}/turns/stream".encode(),
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("127.0.0.1", 1),
        "server": ("test", 80),
        "scheme": "http",
    }
    try:
        async with asyncio.timeout(5):
            await api.app(scope, receive, send)
    except Exception:  # the server sees the client vanish (ClientDisconnect or OSError)
        pass
    rows = await ledger(api)
    assert len(rows) == 1 and rows[0].finished_at is None and not meter.calls
    assert (await ask(api, "chat")).status_code == 429  # held until the lease ends
    lease = api.settings.paid_question_lease_seconds
    async with api.world.sessions.begin() as db:
        await db.execute(
            text("UPDATE paid_question_attempts SET started_at = :t"),
            {"t": datetime.now(UTC) - timedelta(seconds=lease + 5)},
        )
    assert succeeded("chat", await ask(api, "chat"))


@pytest.mark.parametrize("route", ROUTES)
async def test_a_provider_request_made_in_a_child_task_is_still_counted(api, meter, route):
    meter.in_child = True
    assert succeeded(route, await ask(api, route))
    rows = await ledger(api)
    assert len(rows) == 1 and rows[0].finished_at is not None


async def test_a_turn_that_times_out_still_counts_and_frees_the_slot(api, meter):
    meter.timeout, meter.lease = 0.2, 1
    meter.release = asyncio.Event()  # never set: the fake outlasts the generation budget
    assert (await ask(api, "turn")).status_code == 503
    rows = await ledger(api)
    assert len(rows) == 1 and rows[0].finished_at is not None
    meter.release = None
    meter.timeout, meter.lease = 120.0, 180
    assert succeeded("turn", await ask(api, "turn"))


async def test_a_disconnect_mid_stream_still_counts_and_frees_the_slot(api, meter):
    meter.release = asyncio.Event()
    cid = (await create(api.world)).id
    body = json.dumps(turn_body()).encode()
    sent, gone = {"done": False}, asyncio.Event()

    async def receive():
        if not sent["done"]:
            sent["done"] = True
            return {"type": "http.request", "body": body, "more_body": False}
        await gone.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        return None

    path = f"{BASE}/{cid}/turns/stream"
    headers = [(k.lower().encode(), v.encode()) for k, v in api.headers[USER_A].items()]
    headers += [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
    ]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("127.0.0.1", 1),
        "server": ("test", 80),
        "scheme": "http",
    }
    served = asyncio.create_task(api.app(scope, receive, send))
    await asyncio.wait_for(meter.started.wait(), 5)
    gone.set()
    await asyncio.wait_for(served, 10)
    rows = await ledger(api)
    assert len(rows) == 1 and rows[0].finished_at is not None
    meter.release = None
    assert succeeded("chat", await ask(api, "chat"))


# ---- idempotency, replay and pre-execution failures -------------------------------------------


@pytest.mark.parametrize("route", ["turn", "stream"])
async def test_replay_of_a_completed_turn_is_not_counted_and_not_refused(api, meter, route):
    set_limits(api, hour=1)
    cid = (await create(api.world)).id
    key = uuid4()
    assert succeeded(route, await ask(api, route, key=key, cid=cid))
    again = await ask(api, route, key=key, cid=cid)  # the hour limit is now reached
    assert again.status_code == 200, again.text
    assert len(meter.calls) == 1 and len(await ledger(api)) == 1
    assert (await ask(api, route)).status_code == 429  # a new question is still refused


async def test_replay_of_a_running_turn_while_the_slot_is_busy_is_not_refused(api, meter):
    meter.release = asyncio.Event()
    cid = (await create(api.world)).id
    key = uuid4()
    first = asyncio.create_task(ask(api, "turn", key=key, cid=cid))
    await asyncio.wait_for(meter.started.wait(), 5)
    replay = await ask(api, "turn", key=key, cid=cid)
    assert replay.status_code == 202 and replay.json()["replayed"]
    assert len(meter.calls) == 1 and len(await ledger(api)) == 1
    meter.release.set()
    assert (await first).status_code == 200


async def test_replay_of_a_failed_turn_never_executes_or_counts_again(api, meter):
    meter.error = ChatError("boom")
    cid = (await create(api.world)).id
    key = uuid4()
    assert (await ask(api, "turn", key=key, cid=cid)).status_code == 503
    set_limits(api, hour=1)  # the failed attempt used the whole hour allowance
    meter.error = None
    again = await ask(api, "turn", key=key, cid=cid)
    assert again.status_code != 429
    assert len(meter.calls) == 1 and len(await ledger(api)) == 1


async def test_payload_conflict_on_a_known_request_id_is_409_and_consumes_nothing(api, meter):
    cid = (await create(api.world)).id
    key = uuid4()
    assert succeeded("turn", await ask(api, "turn", key=key, cid=cid))
    set_limits(api, hour=1)
    conflict = await ask(api, "turn", key=key, cid=cid, question="A different question")
    assert conflict.status_code == 409
    assert len(await ledger(api)) == 1


async def test_pre_execution_failures_leave_no_row_and_the_same_id_is_then_counted_once(api, meter):
    set_limits(api, concurrent=2)
    cid = (await create(api.world)).id
    meter.release = asyncio.Event()
    running = asyncio.create_task(ask(api, "turn", cid=cid))
    await asyncio.wait_for(meter.started.wait(), 5)
    key = uuid4()
    busy = await ask(api, "turn", key=key, cid=cid)  # reserved after admission: 409 busy
    assert busy.status_code == 409
    rows = await ledger(api)
    assert len(rows) == 1 and rows[0].finished_at is None  # only the running question's row
    meter.release.set()
    assert (await running).status_code == 200
    # Version conflict is also raised at reservation.
    stale = await api.client.post(
        f"{BASE}/{cid}/turns", json=turn_body(key, version=0), headers=api.headers[USER_A]
    )
    assert stale.status_code == 409
    assert len(await ledger(api)) == 1
    async with api.world.sessions() as db:
        version = await db.scalar(text("SELECT content_version FROM conversations"))
    retry = await api.client.post(
        f"{BASE}/{cid}/turns", json=turn_body(key, version=version), headers=api.headers[USER_A]
    )
    assert retry.status_code == 200
    assert len(await ledger(api)) == 2  # the retried id counted exactly once


async def test_a_missing_or_foreign_conversation_is_404_and_never_masked_by_a_limit(api, meter):
    set_limits(api, hour=1)
    assert succeeded("chat", await ask(api, "chat"))  # the hour limit is reached
    foreign = (await create(api.world, USER_B)).id
    assert (await ask(api, "turn", cid=foreign)).status_code == 404
    assert (await ask(api, "turn", cid=uuid4())).status_code == 404
    assert len(await ledger(api)) == 1 and not meter.calls[1:]


async def test_simultaneous_duplicate_request_ids_execute_and_count_once(api, meter):
    set_limits(api, concurrent=2)
    meter.delay = 0.3
    cid = (await create(api.world)).id
    key = uuid4()
    one, two = await asyncio.gather(
        ask(api, "turn", key=key, cid=cid), ask(api, "turn", key=key, cid=cid)
    )
    assert {one.status_code, two.status_code} <= {200, 202, 429}
    assert 200 in (one.status_code, two.status_code)
    assert len(meter.calls) == 1
    rows = await ledger(api)
    assert len(rows) == 1 and rows[0].finished_at is not None


async def test_submit_without_an_attempt_that_would_create_a_turn_aborts_with_503(api, meter):
    """The replay pre-check hit, then the turn vanished: never execute without admission."""
    cid = (await create(api.world)).id
    original = ConversationChatService.has_turn_for_request

    async def lie(self, principal, conversation_id, body):
        return True

    ConversationChatService.has_turn_for_request = lie  # type: ignore[method-assign]
    try:
        response = await ask(api, "turn", cid=cid)
    finally:
        ConversationChatService.has_turn_for_request = original  # type: ignore[method-assign]
    assert response.status_code == 503
    assert int(response.headers["retry-after"]) >= 1
    assert not meter.calls and await ledger(api) == []
    async with api.world.sessions() as db:
        assert await db.scalar(text("SELECT count(*) FROM conversation_turns")) == 0


# ---- order of checks --------------------------------------------------------------------------


async def test_validation_and_stream_preconditions_are_not_masked_by_a_limit(api, meter):
    set_limits(api, hour=1)
    assert succeeded("chat", await ask(api, "chat"))
    cid = (await create(api.world)).id
    bad = await api.client.post(
        f"{BASE}/{cid}/turns", json={"question": "x"}, headers=api.headers[USER_A]
    )
    assert bad.status_code == 422
    api.settings.tool_rag_agent_enabled = False
    assert (await ask(api, "stream", cid=cid)).status_code == 409
    api.settings.chat_streaming_enabled = False
    assert (await ask(api, "stream", cid=cid)).status_code == 404
    assert len(await ledger(api)) == 1


async def test_authentication_is_checked_before_admission(api, meter):
    set_limits(api, hour=1)
    assert succeeded("chat", await ask(api, "chat"))
    anonymous = await api.client.post(CHAT, json={"question": "q"})
    assert anonymous.status_code == 401
    cid = (await create(api.world)).id
    no_csrf = {k: v for k, v in api.headers[USER_A].items() if k != "X-CSRF-Token"}
    response = await api.client.post(f"{BASE}/{cid}/turns", json=turn_body(), headers=no_csrf)
    assert response.status_code == 403


# ---- fail closed ---------------------------------------------------------------------------------


@pytest.mark.parametrize("route", ROUTES)
async def test_unavailable_ledger_answers_503_and_makes_no_provider_call(
    api, meter, monkeypatch, route
):
    async def broken(self, owner):
        raise QuotaUnavailable()

    monkeypatch.setattr(PaidQuestionQuota, "admit", broken)
    response = await ask(api, route)
    assert response.status_code == 503, response.text
    assert response.status_code != 429 and not meter.calls


async def test_a_lock_timeout_on_admission_is_503_within_about_two_seconds(api, meter):
    async with api.world.sessions() as holder:
        await holder.execute(
            text("SELECT pg_advisory_lock(hashtextextended(:key, 0))"),
            {"key": lock_key(USER_A)},
        )
        try:
            started = asyncio.get_running_loop().time()
            response = await ask(api, "chat")
            elapsed = asyncio.get_running_loop().time() - started
        finally:
            await holder.execute(
                text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"),
                {"key": lock_key(USER_A)},
            )
    assert response.status_code == 503 and elapsed < 6 and not meter.calls


@pytest.mark.parametrize("route", ROUTES)
async def test_a_failing_finish_does_not_change_the_response(api, meter, monkeypatch, route):
    baseline = await ask(api, route)
    assert succeeded(route, baseline)

    async def broken(self, attempt_id):
        raise RuntimeError("finish failed")

    monkeypatch.setattr(PaidQuestionQuota, "finish", broken)
    response = await ask(api, route)
    assert succeeded(route, response) and response.status_code == baseline.status_code


# ---- ownership, persistence, pruning ------------------------------------------------------------


async def test_owner_a_at_the_limit_does_not_change_owner_b_and_counts_persist(api, meter):
    set_limits(api, hour=1)
    assert succeeded("chat", await ask(api, "chat"))
    assert (await ask(api, "chat")).status_code == 429
    assert succeeded("chat", await ask(api, "chat", owner=USER_B))
    # A brand-new service instance on the same database sees the same counts.
    fresh = PaidQuestionQuota(api.world.engine, api.settings)
    from app.services.paid_question_quota import QuotaRefused

    with pytest.raises(QuotaRefused):
        await fresh.admit(USER_A)


async def test_admission_prunes_expired_rows_at_a_bounded_rate(api, meter, monkeypatch):
    import app.services.paid_question_quota as module

    monkeypatch.setattr(module, "_next_prune_at", 0.0)
    old = datetime.now(UTC) - timedelta(hours=40)
    async with api.world.sessions.begin() as db:
        db.add(PaidQuestionAttempt(id=uuid4(), owner_id=USER_B, started_at=old, finished_at=old))
    assert succeeded("chat", await ask(api, "chat"))
    assert await ledger(api, USER_B) == []  # pruned by the first admission
    async with api.world.sessions.begin() as db:
        db.add(PaidQuestionAttempt(id=uuid4(), owner_id=USER_B, started_at=old, finished_at=old))
    assert succeeded("chat", await ask(api, "chat"))
    assert len(await ledger(api, USER_B)) == 1  # the next admission did not prune again


# ---- input caps -----------------------------------------------------------------------------------


async def test_a_4001_character_question_on_chat_is_422_and_4000_is_accepted(api, meter):
    over = await api.client.post(CHAT, json={"question": "q" * 4001}, headers=api.headers[USER_A])
    assert over.status_code == 422 and "q" * 4001 not in over.text
    assert not meter.calls and await ledger(api) == []
    ok = await api.client.post(CHAT, json={"question": "q" * 4000}, headers=api.headers[USER_A])
    assert ok.status_code == 200


def chunked(payload: bytes, size=16 * 1024):
    async def generate():
        for start in range(0, len(payload), size):
            yield payload[start : start + size]

    return generate()


@pytest.mark.parametrize(
    "route,limit", [("chat", 512 * 1024), ("turn", 64 * 1024), ("stream", 64 * 1024)]
)
@pytest.mark.parametrize("mode", ["length", "chunked"])
async def test_an_over_cap_body_is_refused_before_parsing(api, meter, route, limit, mode):
    cid = (await create(api.world)).id
    url = (
        CHAT
        if route == "chat"
        else f"{BASE}/{cid}/turns" + ("/stream" if route == "stream" else "")
    )
    payload = b'{"question": "' + b"x" * (limit + 10) + b'"}'
    headers = {**api.headers[USER_A], "Content-Type": "application/json"}
    content = payload if mode == "length" else chunked(payload)
    response = await api.client.post(url, content=content, headers=headers)
    assert response.status_code == 413, response.text
    assert not meter.calls and await ledger(api) == []


async def test_an_over_cap_body_may_be_refused_before_authentication(api, meter):
    payload = b'{"question": "' + b"x" * (512 * 1024 + 10) + b'"}'
    response = await api.client.post(
        CHAT, content=payload, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413


async def test_the_largest_legal_chat_and_turn_requests_are_accepted(api, meter):
    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "text": "h" * 3000} for i in range(8)
    ]
    big = await api.client.post(
        CHAT,
        json={
            "question": "q" * 4000,
            "conversation_id": "c",
            "history": history,
            "history_window_complete": True,
        },
        headers=api.headers[USER_A],
    )
    assert big.status_code == 200, big.text
    assert succeeded("turn", await ask(api, "turn", question="q" * 4000))


async def test_other_turn_paths_are_not_given_the_body_cap(api, meter):
    """Only the turn creation and stream paths carry the 64 KiB cap."""
    cid = (await create(api.world)).id
    response = await api.client.post(
        f"{BASE}/{cid}/turns/{uuid4()}/interrupt",
        content=b'{"x": "' + b"y" * (70 * 1024) + b'"}',
        headers={**api.headers[USER_A], "Content-Type": "application/json"},
    )
    assert response.status_code != 413


async def test_settings_defaults_are_the_approved_limits():
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert (settings.paid_question_hour_limit, settings.paid_question_day_limit) == (20, 50)
    assert settings.paid_question_concurrent_limit == 1
    assert settings.chat_execution_seconds == 180


# ---- /chat execution timeout -----------------------------------------------------------------------


async def test_chat_execution_timeout_is_503_finishes_the_attempt_and_frees_the_slot(api, meter):
    api.settings.chat_execution_seconds = 1
    meter.release = asyncio.Event()  # never set: the fake sleeps past the bound
    response = await ask(api, "chat")
    assert response.status_code == 503, response.text
    assert (
        response.json()["detail"]
        == "The service is temporarily unavailable. Please try again later."
    )
    rows = await ledger(api)
    assert len(rows) == 1 and rows[0].finished_at is not None
    meter.release = None
    assert succeeded("chat", await ask(api, "chat"))
