"""Mounted durable chat with real PostgreSQL, sessions and controlled generation."""

import asyncio
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import Depends
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.conversations import get_conversation_chat_service
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.db.models import ApplicationSession, Conversation, ConversationTurn, QueryHistory
from app.services.conversation_chat_service import ConversationChatService
from app.services.conversation_repository import ConversationRepository
from app.services.rag_service import RagResult, RagService
from app.retrieval.owned import gather_owned
from .conftest import USER_A, USER_B
from .test_conversation_api import api, world, request, payload, BASE, private
from .test_conversation_repository import create, reserve, failure, result

__all__ = ["api", "world"]


@pytest.fixture
async def chat(api):
    control = SimpleNamespace(
        started=asyncio.Event(),
        release=None,
        calls=[],
        error=None,
        timeout=120.0,
        lease=180,
        internal_question=None,
        citations=[],
        answer="Canonical answer",
        resistant=False,
        cancelled=asyncio.Event(),
    )

    class FakeRag(RagService):
        def __init__(self, db, settings):
            self.db = db
            self.persist_query_history = False

        async def ask(self, question, user_id, **kwargs):
            assert await self.db.scalar(text("SHOW transaction_read_only")) == "on"
            async with api.world.sessions() as observer:
                turns = (
                    await observer.scalars(
                        select(ConversationTurn).where(
                            ConversationTurn.owner_id == user_id,
                            ConversationTurn.conversation_id == UUID(kwargs["conversation_id"]),
                            ConversationTurn.status == "RUNNING",
                        )
                    )
                ).all()
                assert len(turns) == 1  # Reservation is visible before model invocation.
            from app.retrieval.scope import scoped_session

            async with scoped_session(self.db) as child:
                assert await child.scalar(text("SHOW transaction_read_only")) == "on"
            control.calls.append((question, user_id, kwargs))
            control.started.set()
            if control.release is not None:
                try:
                    await control.release.wait()
                except asyncio.CancelledError:
                    control.cancelled.set()
                    if not control.resistant:
                        raise
                    await control.release.wait()
            if control.error:
                raise control.error
            return RagResult(
                query_id=uuid4(),
                user_id=user_id,
                question=control.internal_question or question,
                answer=control.answer,
                citations=control.citations,
                retrieval_count=0,
            )

    def service(db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)):
        return ConversationChatService(
            db,
            settings,
            rag_factory=FakeRag,
            generation_timeout=control.timeout,
            execution_seconds=control.lease,
        )

    api.app.dependency_overrides[get_conversation_chat_service] = service
    return control


def body(key=None, question="Original submitted question", version=0):
    return {
        "client_request_id": str(key or uuid4()),
        "question": question,
        "expected_content_version": version,
    }


async def submit(api, cid, value=None, owner=USER_A, headers=None):
    return await api.client.post(
        f"{BASE}/{cid}/turns", json=value or body(), headers=headers or api.headers[owner]
    )


async def rows(api):
    async with api.world.sessions() as db:
        return (
            (await db.scalars(select(ConversationTurn))).all(),
            (await db.scalars(select(QueryHistory))).all(),
        )


async def test_success_atomic_original_question_replay_detail_and_private(api, chat):
    cid = (await create(api.world)).id
    chat.internal_question = "Internal graph retrieval rewrite"
    key = body()
    response = await submit(api, cid, key)
    assert response.status_code == 200, response.text
    private(response)
    receipt = response.json()["turn"]
    assert receipt["status"] == "COMPLETED"
    assert receipt["question"] == key["question"]
    assert receipt["answer"] == "Canonical answer"
    turns, results = await rows(api)
    assert len(turns) == len(results) == 1
    assert turns[0].query_history_id == results[0].id
    assert results[0].question == chat.internal_question
    replay = await submit(api, cid, key)
    assert replay.status_code == 200 and replay.json()["replayed"]
    assert replay.json()["turn"] == receipt and len(chat.calls) == 1
    detail = await request(api, "GET", cid)
    assert detail.json()["turns"][0]["answer"] == receipt["answer"]
    status = await api.client.get(
        f"{BASE}/{cid}/turns/{receipt['id']}", headers=api.headers[USER_A]
    )
    assert status.json() == receipt
    assert "execution_id" not in receipt and "session_id" not in receipt
    # Read-only generation settings cannot contaminate regular pooled transactions.
    async with api.world.sessions() as db:
        assert await db.scalar(text("SHOW transaction_read_only")) == "off"


async def test_concurrent_replay_conflict_busy_and_foreign_reads(api, chat):
    cid = (await create(api.world)).id
    chat.release = asyncio.Event()
    key = body()
    running = asyncio.create_task(submit(api, cid, key))
    await asyncio.wait_for(chat.started.wait(), 5)
    replay = await submit(api, cid, key)
    assert replay.status_code == 202 and replay.json()["replayed"]
    tid = replay.json()["turn"]["id"]
    assert replay.headers["location"].endswith(tid)
    assert (await submit(api, cid, key | {"question": "Changed"})).status_code == 409
    assert (await submit(api, cid)).status_code == 409
    assert (await submit(api, cid, owner=USER_B)).status_code == 404
    foreign = await api.client.get(f"{BASE}/{cid}/turns/{tid}", headers=api.headers[USER_B])
    assert foreign.status_code == 404
    assert len(chat.calls) == 1
    chat.release.set()
    assert (await running).status_code == 200
    turns, results = await rows(api)
    assert len(turns) == len(results) == 1 and turns[0].sequence == 1


@pytest.mark.parametrize("fault", ["model", "timeout", "commit", "foreign-result"])
async def test_failure_never_publishes_orphaned_success(api, chat, monkeypatch, fault):
    cid = (await create(api.world)).id
    if fault == "model":
        chat.error = RuntimeError("provider-private-body-must-not-escape")
    elif fault == "timeout":
        chat.timeout, chat.lease = 0.05, 1
        chat.release = asyncio.Event()
    elif fault == "commit":
        original = ConversationRepository.complete
        commit = AsyncSession.commit

        async def complete(self, *args, **kwargs):
            await original(self, *args, **kwargs)
            self.db.info["reject_publication"] = True

        async def reject(self):
            if self.info.get("reject_publication"):
                raise RuntimeError("injected commit failure")
            await commit(self)

        monkeypatch.setattr(ConversationRepository, "complete", complete)
        monkeypatch.setattr(AsyncSession, "commit", reject)
    else:
        original = ConversationChatService._citations

        async def foreign(self, db, owner, generated):
            generated.user_id = USER_B
            await original(self, db, owner, generated)

        monkeypatch.setattr(ConversationChatService, "_citations", foreign)
    response = await submit(api, cid)
    assert response.status_code == 503, response.text
    private(response)
    assert "provider-private" not in response.text
    turns, results = await rows(api)
    assert len(turns) == 1 and not results and turns[0].query_history_id is None
    assert turns[0].status == ("INTERRUPTED" if fault == "timeout" else "FAILED")


@pytest.mark.parametrize("fault", ["revoke", "delete", "cancel", "suppressed-cancel"])
async def test_authority_loss_during_generation(api, chat, fault):
    cid = (await create(api.world)).id
    chat.release = asyncio.Event()
    chat.resistant = fault == "suppressed-cancel"
    value = body()
    pending = asyncio.create_task(submit(api, cid, value))
    await asyncio.wait_for(chat.started.wait(), 5)
    if fault == "revoke":
        async with api.world.sessions.begin() as db:
            await db.execute(
                update(ApplicationSession)
                .where(ApplicationSession.id == api.issued[USER_A].session_id)
                .values(revoked_at=func.clock_timestamp())
            )
    elif fault == "delete":
        assert (await request(api, "DELETE", cid, body=payload("DELETE"))).status_code == 204
    else:
        pending.cancel()
        if chat.resistant:
            await chat.cancelled.wait()
    chat.release.set()
    if fault in ("cancel", "suppressed-cancel"):
        with pytest.raises(asyncio.CancelledError):
            await pending
    else:
        response = await pending
        assert response.status_code == (401 if fault == "revoke" else 404), response.text
    turns, results = await rows(api)
    assert not results and turns[0].status == "INTERRUPTED"
    assert turns[0].query_history_id is None


async def test_restart_expired_observation_fenced_interruption_and_new_identity(api, chat):
    cid = (await create(api.world)).id
    turn = await reserve(api.world, cid, execution_seconds=1)
    # Advance only the disposable database clock to the actual deadline.
    async with api.world.sessions() as db:
        await db.execute(
            text(
                "SELECT pg_sleep(GREATEST(0, EXTRACT(EPOCH FROM (:deadline - clock_timestamp()))) + 0.01)"
            ),
            {"deadline": turn.execution_deadline},
        )
    url = f"{BASE}/{cid}/turns/{turn.id}"
    status = await api.client.get(url, headers=api.headers[USER_A])
    assert status.status_code == 200 and status.json()["execution_expired"]
    assert status.json()["status"] == "RUNNING" and not chat.calls
    for _ in range(2):
        interrupted = await api.client.post(
            url + "/interrupt", json={}, headers=api.headers[USER_A]
        )
        assert interrupted.status_code == 200 and interrupted.json()["status"] == "INTERRUPTED"
    async with api.world.sessions() as db:
        version = (await db.get(Conversation, cid)).content_version
    completed = await submit(api, cid, body(version=version))
    assert completed.status_code == 200 and len(chat.calls) == 1
    turns, results = await rows(api)
    assert len(turns) == 2 and len(results) == 1


async def test_history_is_sql_owned_completed_and_bounded(api, chat):
    cid = (await create(api.world)).id
    first = await reserve(api.world, cid)
    rid = await result(api.world)
    async with api.world.sessions.begin() as db:
        await ConversationRepository(db).complete(
            USER_A, cid, first.id, execution_id=first.execution_id, result_id=rid, retrieval_count=0
        )
    failed = await reserve(api.world, cid)
    await failure(api.world, failed)
    async with api.world.sessions() as db:
        version = (await db.get(Conversation, cid)).content_version
    response = await submit(api, cid, body(version=version))
    assert response.status_code == 200, response.text
    kwargs = chat.calls[0][2]
    assert kwargs["history"] == [
        {"role": "user", "text": "Original question"},
        {"role": "assistant", "text": "Saved answer"},
    ]
    assert kwargs["history_window_complete"] is False
    assert len(kwargs["history"]) <= 8


@pytest.mark.parametrize("field", ["owner_id", "history", "execution_id", "result_id"])
async def test_privileged_input_rejected(api, chat, field):
    cid = (await create(api.world)).id
    response = await submit(api, cid, body() | {field: str(USER_B)})
    assert response.status_code == 422 and not chat.calls
    assert await rows(api) == ([], [])


async def test_cursor_bigint_boundary(api, chat):
    cid = (await create(api.world)).id
    for value, code in ((9223372036854775807, 200), (9223372036854775808, 422)):
        response = await request(api, "GET", cid, params={"before_sequence": value})
        assert response.status_code == code
        private(response)
    assert await rows(api) == ([], [])


async def test_parallel_failure_joins_owned_sibling():
    started, cleaned = asyncio.Event(), asyncio.Event()

    async def waiting():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    async def fail():
        await started.wait()
        raise ValueError("controlled")

    with pytest.raises(ValueError, match="controlled"):
        await gather_owned(waiting(), fail())
    assert cleaned.is_set()


@pytest.mark.parametrize("authority", ["deadline", "session"])
async def test_publication_rejects_expiry_after_real_row_lock_wait(
    api, chat, monkeypatch, authority
):
    from datetime import timedelta
    from .test_conversation_repository import wait_for_database_lock

    cid = (await create(api.world)).id
    chat.release = asyncio.Event()
    if authority == "deadline":
        chat.timeout, chat.lease = 0.2, 1
    pending = asyncio.create_task(submit(api, cid))
    await asyncio.wait_for(chat.started.wait(), 5)
    async with api.world.sessions() as observer:
        turn = await observer.scalar(select(ConversationTurn))
        if authority == "deadline":
            deadline = turn.execution_deadline
        else:
            now = await observer.scalar(select(func.clock_timestamp()))
            deadline = now + timedelta(seconds=1)
    if authority == "session":
        async with api.world.sessions.begin() as db:
            await db.execute(
                update(ApplicationSession)
                .where(ApplicationSession.id == api.issued[USER_A].session_id)
                .values(expires_at=deadline)
            )
    entered = asyncio.get_running_loop().create_future()
    execution = ConversationRepository._execution

    async def marked(self, *args, **kwargs):
        if not entered.done():
            entered.set_result(await self.db.scalar(select(func.pg_backend_pid())))
        return await execution(self, *args, **kwargs)

    monkeypatch.setattr(ConversationRepository, "_execution", marked)
    async with api.world.sessions() as blocker:
        await blocker.scalar(select(Conversation).where(Conversation.id == cid).with_for_update())
        chat.release.set()
        await wait_for_database_lock(api.world, await asyncio.wait_for(entered, 5))
        async with api.world.sessions() as clock:
            await clock.execute(
                text(
                    "SELECT pg_sleep(GREATEST(0, EXTRACT(EPOCH FROM (:deadline - clock_timestamp()))) + 0.01)"
                ),
                {"deadline": deadline},
            )
        await blocker.rollback()
    response = await pending
    assert response.status_code == (401 if authority == "session" else 503), response.text
    turns, results = await rows(api)
    assert turns[0].status == "INTERRUPTED" and not results


async def test_commit_acknowledgement_lost_returns_verified_durable_result(api, chat, monkeypatch):
    cid = (await create(api.world)).id
    original_complete, original_commit = ConversationRepository.complete, AsyncSession.commit

    async def complete(self, *args, **kwargs):
        await original_complete(self, *args, **kwargs)
        self.db.info["lose_ack"] = True

    async def commit(self):
        await original_commit(self)
        if self.info.pop("lose_ack", False):
            raise RuntimeError("synthetic lost SQL acknowledgement")

    monkeypatch.setattr(ConversationRepository, "complete", complete)
    monkeypatch.setattr(AsyncSession, "commit", commit)
    value = body()
    response = await submit(api, cid, value)
    assert response.status_code == 200 and response.json()["turn"]["status"] == "COMPLETED"
    replay = await submit(api, cid, value)
    assert replay.status_code == 200 and len(chat.calls) == 1
    turns, results = await rows(api)
    assert len(turns) == len(results) == 1


@pytest.mark.parametrize("second_owner", [USER_A, USER_B])
async def test_independent_owners_and_conversations(api, chat, second_owner):
    a = (await create(api.world)).id
    b = (await create(api.world, second_owner)).id
    chat.release = asyncio.Event()
    key = body()
    first = asyncio.create_task(submit(api, a, key))
    await asyncio.wait_for(chat.started.wait(), 5)
    second = asyncio.create_task(
        submit(api, b, key if second_owner == USER_B else body(), second_owner)
    )
    # Observe durable reservation of both independent owners without timing sleeps.
    async with asyncio.timeout(5):
        while len(chat.calls) < 2:
            await asyncio.sleep(0)
    chat.release.set()
    assert [r.status_code for r in await asyncio.gather(first, second)] == [200, 200]
    turns, results = await rows(api)
    assert {t.owner_id for t in turns} == {USER_A, second_owner}
    assert len(results) == 2


@pytest.mark.parametrize("fault", ["no-session", "csrf", "origin"])
async def test_turn_mutation_reuses_session_and_csrf(api, chat, fault):
    cid = (await create(api.world)).id
    headers = dict(api.headers[USER_A])
    if fault == "no-session":
        headers.pop("Cookie")
    elif fault == "csrf":
        headers.pop("X-CSRF-Token")
    else:
        headers["Origin"] = "https://foreign.invalid"
    response = await submit(api, cid, headers=headers)
    assert response.status_code == (401 if fault == "no-session" else 403)
    assert not chat.calls and await rows(api) == ([], [])


@pytest.mark.parametrize("mode", ["linear", "graph", "tool"])
async def test_real_rag_modes_owner_filtered_qdrant_and_citation_publication(
    api, monkeypatch, mode
):
    import os
    from datetime import UTC, datetime
    from qdrant_client import AsyncQdrantClient
    from app.db.enums import DriveFileStatus
    from app.db.models import Chunk, Document, DriveFile
    from app.embeddings.vector_store import QdrantVectorStore, VectorPoint
    from app.services.tool_agent_service import ToolAgentAdapter
    from app.retrieval.hybrid import HybridRetriever
    from app.agents.tool_rag.agent_models import AgentStepResult
    from tests.agents.tool_rag.test_agent_loop import ScriptChat, call

    url = os.environ.get("CONVERSATION_TEST_QDRANT_URL")
    if url != "http://127.0.0.1:61448":
        pytest.skip("Requires the explicitly disposable S2B Qdrant endpoint")
    settings = api.settings
    settings.qdrant_url = url
    settings.qdrant_collection = "drivemind_s2b_" + uuid4().hex
    settings.hybrid_retrieval_enabled = True
    settings.agent_graph_enabled = mode == "graph"
    settings.tool_rag_agent_enabled = mode == "tool"
    settings.evidence_min_fusion_score = 0.0
    settings.retrieval_score_threshold = 0.0

    class Embeddings:
        embedding_dimension = 3

        async def embed_texts(self, texts):
            return [[1.0, 0.0, 0.0] for _ in texts]

    monkeypatch.setattr("app.retrieval.vector.get_embedding_service", lambda _: Embeddings())
    seen = []

    class Chat:
        model_name = "synthetic-only"

        async def generate_grounded_answer(self, question, chunks, **kwargs):
            seen.append(chunks)
            assert chunks and all("A-only" in c.text for c in chunks)
            return "Customer isolation uses owner checks. [1]"

        generate_file_target_answer = generate_grounded_answer
        generate_collection_answer = generate_grounded_answer

        async def generate_direct_answer(self, question):
            raise AssertionError("This is a grounded question")

        async def generate_inventory_answer(self, question, inventory_context):
            raise AssertionError("This is not inventory")

        async def rewrite_followup(self, question, history):
            return question

    points, chunks = [], {}
    async with api.world.sessions.begin() as db:
        for owner, label in ((USER_A, "A"), (USER_B, "B")):
            fid, did, chid = uuid4(), uuid4(), uuid4()
            content = (
                f"{label}-only customer information isolation uses owner authorization checks."
            )
            db.add(
                DriveFile(
                    id=fid,
                    user_id=owner,
                    drive_file_id="overlapping-provider-id",
                    name="same-name.txt",
                    mime_type="text/plain",
                    modified_at=datetime.now(UTC),
                    status=DriveFileStatus.INDEXED,
                )
            )
            await db.flush()
            db.add(
                Document(
                    id=did,
                    drive_file_id=fid,
                    extracted_text=content,
                    extracted_text_hash=label * 64,
                )
            )
            await db.flush()
            db.add(Chunk(id=chid, document_id=did, chunk_index=0, text=content, metadata_json={}))
            chunks[owner] = chid
            points.append(
                VectorPoint(
                    chid,
                    [1.0, 0.0, 0.0],
                    {
                        "chunk_id": str(chid),
                        "user_id": str(owner),
                        "drive_file_id": str(fid),
                        "document_id": str(did),
                        "filename": "same-name.txt",
                        "content_hash": label * 64,
                    },
                )
            )
    client = AsyncQdrantClient(url=url)
    store = QdrantVectorStore(settings, client=client)
    try:
        await store.ensure_collection(vector_size=3)
        for owner, point in zip((USER_A, USER_B), points):
            await store.upsert_points([point], user_id=owner)

        def factory(db, settings):
            adapter = None
            if mode == "tool":
                native = ScriptChat(
                    [
                        call(
                            "search_knowledge",
                            {
                                "query": "customer information isolation",
                                "scope": {"kind": "ALL_ELIGIBLE_INDEXED_FILES"},
                            },
                        ),
                        AgentStepResult(text="Customer isolation uses owner checks. [source_1]"),
                    ]
                )
                adapter = ToolAgentAdapter(
                    db, settings, chat=native, retriever=HybridRetriever(db, settings)
                )
            return RagService(
                db, settings, chat_service=Chat(), tool_agent=adapter, persist_query_history=False
            )

        def service(db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)):
            return ConversationChatService(db, settings, rag_factory=factory)

        api.app.dependency_overrides[get_conversation_chat_service] = service
        cid = (await create(api.world)).id
        original = "How does customer information isolation work?"
        response = await submit(api, cid, body(question=original))
        assert response.status_code == 200, response.text
        receipt = response.json()["turn"]
        assert receipt["status"] == "COMPLETED" and receipt["question"] == original
        assert receipt["citations"] and all(
            c["chunk_id"] == str(chunks[USER_A]) for c in receipt["citations"]
        )
        turns, results = await rows(api)
        assert len(turns) == len(results) == 1
        assert results[0].user_id == USER_A
        for owner, code in ((USER_A, 200), (USER_B, 404)):
            source = await api.client.get(
                f"/api/v1/sources/{chunks[USER_A]}", headers=api.headers[owner]
            )
            assert source.status_code == code
        if mode != "tool":
            assert seen
    finally:
        await client.delete_collection(settings.qdrant_collection)
        await client.close()


async def test_failed_replay_and_live_interruption_cannot_regenerate(api, chat):
    cid = (await create(api.world)).id
    chat.release = asyncio.Event()
    value = body()
    pending = asyncio.create_task(submit(api, cid, value))
    await asyncio.wait_for(chat.started.wait(), 5)
    replay = await submit(api, cid, value)
    tid = replay.json()["turn"]["id"]
    refused = await api.client.post(
        f"{BASE}/{cid}/turns/{tid}/interrupt", json={}, headers=api.headers[USER_A]
    )
    assert refused.status_code == 409
    chat.error = RuntimeError("synthetic model failure")
    chat.release.set()
    assert (await pending).status_code == 503
    terminal = await submit(api, cid, value)
    assert terminal.status_code == 200 and terminal.json()["turn"]["status"] == "FAILED"
    assert len(chat.calls) == 1 and not (await rows(api))[1]


async def test_history_bound_does_not_include_oversized_answer(api, chat):
    cid = (await create(api.world)).id
    turn = await reserve(api.world, cid)
    async with api.world.sessions.begin() as db:
        history = QueryHistory(
            id=uuid4(),
            user_id=USER_A,
            question="Stored original",
            answer="x" * 8001,
            citations_json=[],
        )
        db.add(history)
        await ConversationRepository(db).complete(
            USER_A,
            cid,
            turn.id,
            execution_id=turn.execution_id,
            result_id=history.id,
            retrieval_count=0,
        )
    async with api.world.sessions() as db:
        version = (await db.get(Conversation, cid)).content_version
    response = await submit(api, cid, body(version=version))
    assert response.status_code == 200
    assert chat.calls[0][2]["history"] == []
    assert chat.calls[0][2]["history_window_complete"] is False


async def test_transport_suppressing_timeout_cannot_publish(api, chat):
    cid = (await create(api.world)).id
    chat.timeout, chat.lease = 0.5, 2
    chat.release, chat.resistant = asyncio.Event(), True
    pending = asyncio.create_task(submit(api, cid))
    await asyncio.wait_for(chat.started.wait(), 5)
    await asyncio.wait_for(chat.cancelled.wait(), 5)
    chat.release.set()
    response = await pending
    assert response.status_code == 503
    turns, results = await rows(api)
    assert turns[0].status == "INTERRUPTED" and turns[0].error_code == "GENERATION_TIMEOUT"
    assert not results
