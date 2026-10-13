"""Mounted HTTP routes with real application sessions and disposable PostgreSQL."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db
from app.db.models import ApplicationSession, Conversation, ConversationTurn, QueryHistory
from app.main import create_app
from app.security.principal import VerifiedGoogleIdentity
from app.security.session_helpers import session_cookie_policy
from app.services.application_session_service import ApplicationSessionService
from app.services.conversation_repository import ConversationRepository
from .conftest import USER_A, USER_B
from .test_conversation_repository import world, create, reserve, result, wait_for_database_lock

__all__ = ["world"]
BASE = "/api/v1/conversations"


@pytest.fixture
async def api(world, settings, monkeypatch):
    settings.google_application_sessions_enabled = True
    settings.google_client_id = "synthetic-client"
    settings.google_client_secret = "synthetic-secret"
    settings.google_session_redirect_uri = (
        settings.frontend_url + "/api/v1/auth/session/google/callback"
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    app = create_app()
    headers, issued, pids = {}, {}, {}
    async with world.sessions.begin() as db:
        for owner, subject in ((USER_A, "verified-subject-a"), (USER_B, "verified-subject-b")):
            session = await ApplicationSessionService(db, settings).issue_google(
                VerifiedGoogleIdentity(subject)
            )
            issued[owner] = session
            headers[owner] = {
                "Origin": settings.frontend_url,
                "X-CSRF-Token": session.csrf_token.get_secret_value(),
                "Cookie": session_cookie_policy(settings).name
                + "="
                + session.credential.get_secret_value(),
            }

    async def database(request):
        async with world.sessions() as db:
            tag = request.headers.get("x-test-barrier")
            if tag:
                pids[tag].set_result(await db.scalar(select(func.pg_backend_pid())))
            yield db

    # FastAPI needs an explicit Request annotation on this test-only dependency.
    from fastapi import Request

    database.__annotations__["request"] = Request
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_settings] = lambda: settings
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=settings.frontend_url
    ) as client:
        yield SimpleNamespace(
            app=app,
            client=client,
            world=world,
            headers=headers,
            issued=issued,
            settings=settings,
            pids=pids,
        )


def payload(method, title="Title", key=None, version=1):
    if method == "POST":
        return {"create_request_id": str(key or uuid4()), "title": title}
    if method == "PATCH":
        return {"title": title, "expected_metadata_version": version}
    if method == "DELETE":
        return {"expected_metadata_version": version}
    return None


async def request(a, method, cid=None, owner=USER_A, *, body=None, headers=None, params=None):
    path = BASE + ("/" + str(cid) if cid is not None else "")
    return await a.client.request(
        method,
        path,
        headers=a.headers[owner] if headers is None else headers,
        json=body,
        params=params,
    )


def private(response):
    assert response.headers["cache-control"] == "private, no-store, max-age=0"
    assert "Cookie" in response.headers["vary"]


@pytest.mark.parametrize(
    "method,detail",
    [("POST", False), ("GET", False), ("GET", True), ("PATCH", True), ("DELETE", True)],
)
@pytest.mark.parametrize("identity", ["missing", "revoked", "expired", "invalid", "wrong-kind"])
async def test_all_routes_verify_real_sessions(api, method, detail, identity):
    cid = (await create(api.world)).id
    headers = dict(api.headers[USER_A])
    if identity == "missing":
        headers.pop("Cookie")
    elif identity == "invalid":
        headers["Cookie"] = session_cookie_policy(api.settings).name + "=not-a-valid-session"
    else:
        async with api.world.sessions.begin() as db:
            values = (
                {"revoked_at": func.clock_timestamp()}
                if identity == "revoked"
                else {
                    "created_at": datetime.now(UTC) - timedelta(days=2),
                    "expires_at": datetime.now(UTC) - timedelta(days=1),
                }
                if identity == "expired"
                else {"kind": "DEMO_VISITOR", "user_id": None}
            )
            await db.execute(
                update(ApplicationSession)
                .where(ApplicationSession.id == api.issued[USER_A].session_id)
                .values(**values)
            )
    response = await request(
        api, method, cid if detail else None, body=payload(method), headers=headers
    )
    assert response.status_code == 401, response.text
    private(response)
    async with api.world.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Conversation)) == 1
        row = await db.get(Conversation, cid)
        assert row is not None and row.title == "New chat" and row.deleted_at is None


@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
@pytest.mark.parametrize("fault", ["no-csrf", "wrong-csrf", "no-origin", "foreign-origin"])
async def test_mutation_csrf_origin_policy(api, method, fault):
    cid = (await create(api.world)).id
    headers = dict(api.headers[USER_A])
    if fault == "no-csrf":
        headers.pop("X-CSRF-Token")
    elif fault == "wrong-csrf":
        headers["X-CSRF-Token"] = "invalid"
    elif fault == "no-origin":
        headers.pop("Origin")
    else:
        headers["Origin"] = "https://foreign.example.invalid"
    response = await request(
        api, method, cid if method != "POST" else None, body=payload(method), headers=headers
    )
    assert response.status_code == 403
    private(response)
    async with api.world.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Conversation)) == 1
        assert (await db.get(Conversation, cid)).metadata_version == 1


async def test_get_uses_session_without_mutation_headers(api):
    response = await request(api, "GET", headers={"Cookie": api.headers[USER_A]["Cookie"]})
    assert response.status_code == 200 and response.json()["conversations"] == []
    private(response)


async def test_create_commit_replay_conflict_and_owner_keys(api):
    key = uuid4()
    body = payload("POST", title="A title", key=key)
    assert body is not None
    one = await request(api, "POST", body=body)
    assert one.status_code == 201
    private(one)
    cid = one.json()["id"]
    async with api.world.sessions() as db:
        row = await db.get(Conversation, cid)
        assert row is not None and row.owner_id == USER_A
    two = await request(api, "POST", body=body | {"title": " A title "})
    assert two.status_code == 200 and two.json() == one.json()
    conflict = await request(api, "POST", body=body | {"title": "changed"})
    assert conflict.status_code == 409
    other = await request(api, "POST", owner=USER_B, body=body)
    assert other.status_code == 201 and other.json()["id"] != cid
    for owner, expected in ((USER_A, cid), (USER_B, other.json()["id"])):
        page = await request(api, "GET", owner=owner)
        assert [row["id"] for row in page.json()["conversations"]] == [expected]


@pytest.mark.parametrize("method", ["GET", "PATCH", "DELETE"])
async def test_foreign_missing_deleted_indistinguishable(api, method):
    foreign = await create(api.world)
    deleted = await create(api.world, USER_B)
    async with api.world.sessions.begin() as db:
        await ConversationRepository(db).delete(USER_B, deleted.id, expected_version=1)
    responses = [
        await request(api, method, cid, owner=USER_B, body=payload(method))
        for cid in (foreign.id, uuid4(), deleted.id)
    ]
    assert all(r.status_code == 404 for r in responses)
    assert all(r.json() == {"detail": "Conversation not found."} for r in responses)
    for r in responses:
        private(r)
    async with api.world.sessions() as db:
        assert (await db.get(Conversation, foreign.id)).metadata_version == 1


@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
@pytest.mark.parametrize(
    "field", ["owner_id", "user_id", "deleted_at", "content_version", "next_sequence"]
)
async def test_forged_writable_fields_rejected(api, method, field):
    cid = (await create(api.world)).id
    body = payload(method)
    assert body is not None
    response = await request(
        api, method, cid if method != "POST" else None, body=body | {field: str(USER_B)}
    )
    assert response.status_code == 422
    private(response)
    assert str(USER_B) not in response.text
    async with api.world.sessions() as db:
        row = await db.get(Conversation, cid)
        assert row is not None and row.owner_id == USER_A and row.metadata_version == 1
        assert await db.scalar(select(func.count()).select_from(Conversation)) == 1


async def test_rename_delete_versions_and_retention(api):
    cid = (await create(api.world)).id
    turn = await reserve(api.world, cid)
    rid = await result(api.world)
    async with api.world.sessions.begin() as db:
        await ConversationRepository(db).complete(
            USER_A, cid, turn.id, execution_id=turn.execution_id, result_id=rid, retrieval_count=1
        )
    rename = await request(api, "PATCH", cid, body=payload("PATCH", title="Renamed"))
    assert rename.status_code == 200 and rename.json()["metadata_version"] == 2
    assert rename.json()["title_is_manual"]
    stale = await request(api, "PATCH", cid, body=payload("PATCH"))
    assert stale.status_code == 409
    assert (await request(api, "DELETE", cid, body=payload("DELETE"))).status_code == 409
    deleted = await request(api, "DELETE", cid, body=payload("DELETE", version=2))
    assert deleted.status_code == 204
    private(deleted)
    assert (await request(api, "DELETE", cid, body=payload("DELETE", version=2))).status_code == 404
    assert (await request(api, "GET", cid)).status_code == 404
    assert (await request(api, "GET")).json()["conversations"] == []
    async with api.world.sessions() as db:
        assert await db.get(QueryHistory, rid) is not None
        assert (await db.get(ConversationTurn, turn.id)).status == "COMPLETED"


async def test_keyset_pagination_ties_and_owner_cursor(api):
    rows = [await create(api.world, title=str(i)) for i in range(5)]
    await create(api.world, USER_B, title="B private")
    async with api.world.sessions.begin() as db:
        await db.execute(
            update(Conversation)
            .where(Conversation.owner_id == USER_A)
            .values(last_activity_at=datetime(2026, 1, 1, tzinfo=UTC))
        )
    seen, cursor = [], None
    for _ in range(3):
        page = await request(
            api, "GET", params={"limit": 2} | ({"cursor": cursor} if cursor else {})
        )
        assert page.status_code == 200
        body = page.json()
        seen.extend(row["id"] for row in body["conversations"])
        cursor = body["next_cursor"]
    assert seen == [str(row.id) for row in sorted(rows, key=lambda row: row.id, reverse=True)]
    first = await request(api, "GET", params={"limit": 1})
    foreign_cursor = await request(
        api, "GET", owner=USER_B, params={"cursor": first.json()["next_cursor"]}
    )
    assert foreign_cursor.status_code == 422
    for params in ({"limit": 0}, {"limit": 101}, {"cursor": "not-valid"}, {"cursor": "x" * 513}):
        bad = await request(api, "GET", params=params)
        assert bad.status_code == 422
        private(bad)


async def test_turn_statuses_original_questions_citations_and_pages(api):
    cid = (await create(api.world)).id
    ids = []
    citation = {
        "chunk_id": str(uuid4()),
        "drive_file_id": str(uuid4()),
        "filename": "saved.txt",
        "snippet": "Saved evidence",
        "score": 0.8,
    }
    for status in ("COMPLETED", "FAILED", "INTERRUPTED", "RUNNING"):
        turn = await reserve(api.world, cid)
        ids.append(turn.id)
        async with api.world.sessions.begin() as db:
            repo = ConversationRepository(db)
            if status == "COMPLETED":
                history = QueryHistory(
                    id=uuid4(),
                    user_id=USER_A,
                    question="Rewritten graph question",
                    answer="Canonical answer",
                    citations_json=[citation],
                )
                db.add(history)
                await repo.complete(
                    USER_A,
                    cid,
                    turn.id,
                    execution_id=turn.execution_id,
                    result_id=history.id,
                    retrieval_count=2,
                )
            elif status != "RUNNING":
                await repo.fail(
                    USER_A,
                    cid,
                    turn.id,
                    execution_id=turn.execution_id,
                    error_code="PRIVATE_PROVIDER_DETAIL",
                    interrupted=status == "INTERRUPTED",
                )
    first = await request(api, "GET", cid, params={"limit": 2})
    assert first.status_code == 200
    assert [t["sequence"] for t in first.json()["turns"]] == [3, 4]
    second = await request(
        api,
        "GET",
        cid,
        params={"limit": 2, "before_sequence": first.json()["next_before_sequence"]},
    )
    turns = second.json()["turns"] + first.json()["turns"]
    assert [t["id"] for t in turns] == [str(i) for i in ids]
    assert [t["status"] for t in turns] == ["COMPLETED", "FAILED", "INTERRUPTED", "RUNNING"]
    assert all(t["question"] == "Original question" for t in turns)
    assert turns[0]["answer"] == "Canonical answer" and turns[0]["citations"] == [citation]
    assert all(t["answer"] is None and t["citations"] == [] for t in turns[1:])
    assert turns[1]["error_code"] == "TURN_FAILED" and turns[2]["error_code"] == "TURN_INTERRUPTED"
    text_body = str(turns)
    assert (
        "PRIVATE_PROVIDER_DETAIL" not in text_body and "Rewritten graph question" not in text_body
    )
    assert (
        not {"execution_id", "initiating_session_id", "payload_hash", "execution_deadline"}
        & turns[0].keys()
    )
    for params in ({"limit": 101}, {"before_sequence": 0}):
        assert (await request(api, "GET", cid, params=params)).status_code == 422


@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
async def test_commit_failure_never_acknowledges_success_or_partial_changes(
    api, monkeypatch, method
):
    cid = (await create(api.world)).id

    async def broken_commit(self):
        raise OperationalError("synthetic commit", {}, RuntimeError("private database detail"))

    monkeypatch.setattr(AsyncSession, "commit", broken_commit)
    response = await request(api, method, cid if method != "POST" else None, body=payload(method))
    assert response.status_code == 503 and "private database detail" not in response.text
    private(response)
    async with api.world.sessions() as db:
        row = await db.get(Conversation, cid)
        assert (
            row is not None
            and row.title == "New chat"
            and row.deleted_at is None
            and row.metadata_version == 1
        )
        assert await db.scalar(select(func.count()).select_from(Conversation)) == 1


async def test_duplicate_post_concurrency_and_independent_owner(api, monkeypatch):
    key = uuid4()
    made, release = asyncio.Event(), asyncio.Event()
    native = ConversationRepository.create

    async def blocked(repo, owner, request_id, title="New chat"):
        result = await native(repo, owner, request_id, title)
        if owner == USER_A and not result.replayed:
            made.set()
            await release.wait()
        return result

    monkeypatch.setattr(ConversationRepository, "create", blocked)
    one = asyncio.create_task(request(api, "POST", body=payload("POST", key=key)))
    two = None
    try:
        await asyncio.wait_for(made.wait(), 5)
        api.pids["duplicate"] = asyncio.Future()
        two = asyncio.create_task(
            request(
                api,
                "POST",
                body=payload("POST", key=key),
                headers=api.headers[USER_A] | {"X-Test-Barrier": "duplicate"},
            )
        )
        await wait_for_database_lock(api.world, await asyncio.wait_for(api.pids["duplicate"], 5))
        other = await asyncio.wait_for(
            request(api, "POST", owner=USER_B, body=payload("POST", key=key)), 5
        )
        assert other.status_code == 201
        release.set()
        first, second = await asyncio.gather(one, two)
        assert [first.status_code, second.status_code] == [201, 200]
        assert first.json()["id"] == second.json()["id"]
        async with api.world.sessions() as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(Conversation)
                    .where(Conversation.owner_id == USER_A)
                )
                == 1
            )
    finally:
        release.set()
        await asyncio.gather(one, *([two] if two else []), return_exceptions=True)


async def test_delete_wins_rename_race_without_resurrection(api, monkeypatch):
    cid = (await create(api.world)).id
    deleted, release = asyncio.Event(), asyncio.Event()
    native = ConversationRepository.delete

    async def blocked(repo, *args, **kwargs):
        await native(repo, *args, **kwargs)
        deleted.set()
        await release.wait()

    monkeypatch.setattr(ConversationRepository, "delete", blocked)
    one = asyncio.create_task(request(api, "DELETE", cid, body=payload("DELETE")))
    two = None
    try:
        await asyncio.wait_for(deleted.wait(), 5)
        api.pids["rename"] = asyncio.Future()
        two = asyncio.create_task(
            request(
                api,
                "PATCH",
                cid,
                body=payload("PATCH"),
                headers=api.headers[USER_A] | {"X-Test-Barrier": "rename"},
            )
        )
        await wait_for_database_lock(api.world, await asyncio.wait_for(api.pids["rename"], 5))
        release.set()
        first, second = await asyncio.gather(one, two)
        assert first.status_code == 204 and second.status_code == 404
        async with api.world.sessions() as db:
            row = await db.get(Conversation, cid)
            assert row is not None and row.deleted_at is not None and row.title == "New chat"
    finally:
        release.set()
        await asyncio.gather(one, *([two] if two else []), return_exceptions=True)


async def test_demo_routes_closed_and_existing_routes_preserved(api):
    paths = api.app.openapi()["paths"]
    assert set(paths[BASE]) == {"get", "post"}
    assert set(paths[BASE + "/{conversation_id}"]) == {"get", "patch", "delete"}
    for path in (
        "/api/v1/auth/session",
        "/api/v1/auth/session/google",
        "/api/v1/auth/session/logout",
        "/api/v1/files",
        "/api/v1/sources/{chunk_id}",
        "/api/v1/index/sync",
        "/api/v1/chat",
    ):
        assert path in paths
    assert not any("turns" in path for path in paths)
    assert not api.app.state.indexing_admission_ready and api.app.state.indexing_supervisor is None
    assert (await api.client.get("/api/v1/files", headers=api.headers[USER_A])).status_code == 200
    assert (
        await api.client.get("/api/v1/sources/" + str(uuid4()), headers=api.headers[USER_A])
    ).status_code == 404
    assert (
        await api.client.post("/api/v1/index/sync", headers=api.headers[USER_A])
    ).status_code == 503
    api.settings.demo_mode = True
    for method, detail in (
        ("POST", False),
        ("GET", False),
        ("GET", True),
        ("PATCH", True),
        ("DELETE", True),
    ):
        response = await request(
            api, method, uuid4() if detail else None, body=payload(method), headers={}
        )
        assert response.status_code == 403
        private(response)
    async with api.world.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Conversation)) == 0


async def test_large_history_is_bounded_and_cursor_complete(api):
    from sqlalchemy import insert
    from .test_conversation_repository import turn_values

    cid = (await create(api.world)).id
    async with api.world.sessions.begin() as db:
        await db.execute(
            insert(ConversationTurn),
            [
                turn_values(
                    api.world,
                    cid,
                    sequence=i,
                    history_end_sequence=i - 1,
                    status="FAILED",
                    finished_at=datetime.now(UTC),
                    error_code="MODEL_FAILED",
                )
                for i in range(1, 121)
            ],
        )
    seen, before = [], None
    for expected_size in (50, 50, 20):
        page = await request(api, "GET", cid, params={"before_sequence": before} if before else {})
        assert page.status_code == 200
        assert len(page.json()["turns"]) == expected_size
        seen = [t["sequence"] for t in page.json()["turns"]] + seen
        before = page.json()["next_before_sequence"]
    assert seen == list(range(1, 121)) and before is None
    async with api.world.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ConversationTurn)) == 120


async def test_session_expires_before_mutation_authority(api, monkeypatch):
    from app.services.conversation_service import ConversationService

    checked, release = asyncio.Event(), asyncio.Event()
    native = ConversationService._live_session

    async def blocked(service, principal, *, lock):
        if lock:
            checked.set()
            await release.wait()
        return await native(service, principal, lock=lock)

    monkeypatch.setattr(ConversationService, "_live_session", blocked)
    task = asyncio.create_task(request(api, "POST", body=payload("POST")))
    try:
        await asyncio.wait_for(checked.wait(), 5)
        async with api.world.sessions.begin() as db:
            await db.execute(
                update(ApplicationSession)
                .where(ApplicationSession.id == api.issued[USER_A].session_id)
                .values(
                    created_at=datetime.now(UTC) - timedelta(days=2),
                    expires_at=datetime.now(UTC) - timedelta(days=1),
                )
            )
        release.set()
        response = await task
        assert response.status_code == 401
        private(response)
        async with api.world.sessions() as db:
            assert await db.scalar(select(func.count()).select_from(Conversation)) == 0
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


async def test_malformed_stored_citations_fail_without_private_error_data(api):
    cid = (await create(api.world)).id
    turn = await reserve(api.world, cid)
    async with api.world.sessions.begin() as db:
        history = QueryHistory(
            id=uuid4(),
            user_id=USER_A,
            question="question",
            answer="private answer",
            citations_json=[{"snippet": "private malformed evidence"}],
        )
        db.add(history)
        await ConversationRepository(db).complete(
            USER_A,
            cid,
            turn.id,
            execution_id=turn.execution_id,
            result_id=history.id,
            retrieval_count=1,
        )
    response = await request(api, "GET", cid)
    assert response.status_code == 503
    assert "private" not in response.text
    private(response)


async def test_invalid_identifiers_titles_and_versions(api):
    cid = (await create(api.world)).id
    cases = [
        ("GET", "invalid", None),
        ("POST", None, {"create_request_id": "invalid"}),
        ("POST", None, payload("POST", title=" ")),
        ("POST", None, payload("POST", title="x" * 257)),
        ("PATCH", cid, {"title": " ", "expected_metadata_version": 1}),
        ("PATCH", cid, {"title": "okay", "expected_metadata_version": True}),
        ("DELETE", cid, {"expected_metadata_version": 0}),
    ]
    for method, target, body in cases:
        response = await request(api, method, target, body=body)
        assert response.status_code == 422
        private(response)
    async with api.world.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Conversation)) == 1


async def test_detail_content_version_and_turn_state_share_one_publication_boundary(
    api, monkeypatch
):
    cid = (await create(api.world)).id
    turn = await reserve(api.world, cid)
    rid = await result(api.world)
    read_locked, release = asyncio.Event(), asyncio.Event()
    native = ConversationRepository.turns_with_results

    async def blocked(repo, *args, **kwargs):
        read_locked.set()
        await release.wait()
        return await native(repo, *args, **kwargs)

    monkeypatch.setattr(ConversationRepository, "turns_with_results", blocked)
    read_task = asyncio.create_task(request(api, "GET", cid))
    pid = asyncio.Future()
    publisher = None

    async def publish():
        async with api.world.sessions.begin() as db:
            pid.set_result(await db.scalar(select(func.pg_backend_pid())))
            await ConversationRepository(db).complete(
                USER_A,
                cid,
                turn.id,
                execution_id=turn.execution_id,
                result_id=rid,
                retrieval_count=1,
            )

    try:
        await asyncio.wait_for(read_locked.wait(), 5)
        publisher = asyncio.create_task(publish())
        await wait_for_database_lock(api.world, await asyncio.wait_for(pid, 5))
        release.set()
        response = await read_task
        assert response.status_code == 200
        assert response.json()["conversation"]["content_version"] == 1
        assert response.json()["turns"][0]["status"] == "RUNNING"
        await publisher
        fresh = await request(api, "GET", cid)
        assert fresh.json()["conversation"]["content_version"] == 2
        assert fresh.json()["turns"][0]["status"] == "COMPLETED"
    finally:
        release.set()
        await asyncio.gather(read_task, *([publisher] if publisher else []), return_exceptions=True)
