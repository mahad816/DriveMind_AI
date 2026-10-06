"""Real API/service/graph/executor boundary with fake datastores and native LLM steps."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.chat import get_rag_service
from app.api.dependencies import require_demo_index
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.llm.base import ChatError
from app.main import create_app
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.types import RetrievedChunk
from app.routing.intent_frame.execution import RetrievalRequest
from app.routing.intent_frame.scope import ResolvedFileScope
from app.services.rag_service import RagService
from app.services.tool_agent_service import (
    ToolAgentAdapter,
    TRUNCATION_NOTICE,
    bounded_agent_history,
)
from app.agents.tool_rag.agent_models import AgentStepResult
from tests.agents.tool_rag.test_agent_loop import ScriptChat, call, inventory
from tests.agents.tool_rag.test_revision_safety import DocumentDB, row
from tests.agents.tool_rag.test_tool_execution import file, chunk, USER


class RequestDB(DocumentDB):
    def __init__(self, files, rows):
        super().__init__(files, rows)
        self.saved = []
        self.closed = False
        self.exited = False
        self.exit_error = None

    async def scalar(self, statement):
        if "google_oauth_tokens" in str(statement):
            return SimpleNamespace(user_id=USER)
        return await super().scalar(statement)

    async def get(self, model, identity):
        return SimpleNamespace(id=USER) if identity == USER else None

    def add(self, value):
        self.saved.append(value)

    async def commit(self):
        pass

    async def refresh(self, value):
        value.id = UUID(int=700)

    async def __aenter__(self):
        return self

    async def __aexit__(self, error_type, error, traceback):
        self.exited = True
        self.exit_error = error_type
        self.closed = True


class ScriptRetriever(HybridRetriever):
    def __init__(self, settings, chunks):
        self.settings = settings
        self.chunks = chunks
        self.requests = []

    async def retrieve(self, question: str | RetrievalRequest) -> list[RetrievedChunk]:
        assert isinstance(question, RetrievalRequest)
        assert question.user_id == USER
        self.requests.append(question)
        return self.chunks


@asynccontextmanager
async def api(
    monkeypatch, steps, *, files=None, rows=None, chunks=None, budget=12000, enabled=True
) -> AsyncIterator[tuple[AsyncClient, RequestDB, ScriptChat, ScriptRetriever, AsyncMock]]:
    settings = Settings(
        tool_rag_agent_enabled=enabled, demo_mode=False, debug=False, rag_max_context_chars=budget
    )
    db = RequestDB(
        files if files is not None else [file()],
        rows if rows is not None else [row(0, "Project deadline is March 18.")],
    )
    chat = ScriptChat(steps)
    retriever = ScriptRetriever(settings, chunks if chunks is not None else [chunk()])
    legacy = AsyncMock()
    legacy.generate_direct_answer.return_value = "Legacy hello"
    legacy.generate_grounded_answer.return_value = "Legacy evidence [1]"
    adapter = ToolAgentAdapter(cast(AsyncSession, db), settings, chat=chat, retriever=retriever)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[require_demo_index] = lambda: None
    # Exercise the existing get_db async-with implementation and cleanup boundary.
    monkeypatch.setattr("app.db.session.SessionLocal", lambda: db)

    def service(session: AsyncSession = Depends(get_db)):
        assert session is db
        return RagService(
            session, settings, retriever=retriever, chat_service=legacy, tool_agent=adapter
        )

    app.dependency_overrides[get_rag_service] = service
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, db, chat, retriever, legacy


def full(handle="file_1", identifier="read"):
    return call(
        "file_evidence",
        {"file_handle": {"kind": "FILE", "value": handle}, "mode": "FULL_DOCUMENT"},
        identifier,
    )


def search(identifier="search"):
    return call(
        "search_knowledge",
        {"query": "policy", "scope": {"kind": "ALL_ELIGIBLE_INDEXED_FILES"}},
        identifier,
    )


def public(body):
    assert set(body) == {"query_id", "user_id", "answer", "citations", "retrieval_count", "message"}
    assert body["user_id"] == str(USER)
    prose = body["answer"]
    assert not any(
        s in prose
        for s in (
            str(USER),
            str(UUID(int=10)),
            "file_1",
            "source_1",
            "evidence_1",
            "SELECT ",
            "Traceback",
            "/Users/",
        )
    )
    for citation in body["citations"]:
        assert set(citation) == {"chunk_id", "drive_file_id", "filename", "snippet", "score"}
        UUID(citation["chunk_id"])
        UUID(citation["drive_file_id"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question, steps, expected_sources",
    [
        ("Hello", [AgentStepResult(text="Hello")], 0),
        (
            "How many files do I have?",
            [call("files_query", inventory("COUNT")), AgentStepResult(text="One indexed file.")],
            0,
        ),
        (
            "List my files.",
            [call("files_query", inventory()), AgentStepResult(text="report.pdf")],
            0,
        ),
        (
            "What is our policy?",
            [search(), AgentStepResult(text="Approval is required. [source_1]")],
            1,
        ),
        (
            "Summarize my latest file.",
            [
                call("files_query", inventory("LATEST")),
                full(),
                AgentStepResult(text="Project deadline is March 18."),
            ],
            1,
        ),
        (
            "Summarize report.pdf.",
            [
                call("resolve_file", {"reference": "report.pdf"}),
                full(),
                AgentStepResult(text="Project deadline is March 18. [source_1]"),
            ],
            1,
        ),
        (
            "List files and summarize the first one.",
            [
                call("files_query", inventory()),
                full(),
                AgentStepResult(text="report.pdf: deadline is March 18."),
            ],
            1,
        ),
        (
            "Find missing.pdf",
            [
                call("resolve_file", {"reference": "missing.pdf"}),
                AgentStepResult(text="The file was not found."),
            ],
            0,
        ),
        ("Explain file_1", [full(), AgentStepResult(text="Please specify a filename.")], 0),
        (
            "Use unavailable tool",
            [call("unknown", {}), AgentStepResult(text="That operation is unavailable.")],
            0,
        ),
    ],
)
async def test_integrated_success_matrix(monkeypatch, question, steps, expected_sources):
    async with api(monkeypatch, steps) as (client, db, chat, _retriever, legacy):
        response = await client.post("/api/v1/chat", json={"question": question})
        assert response.status_code == 200, response.text
        body = response.json()
        public(body)
        assert len(body["citations"]) == expected_sources
        assert db.closed and db.exited
        assert len(db.saved) == 1
        record = db.saved[0]
        assert record.question == question and record.answer == body["answer"]
        assert record.citations_json == body["citations"]
        assert not hasattr(record, "tool_history")
        legacy.generate_grounded_answer.assert_not_awaited()
        legacy.generate_direct_answer.assert_not_awaited()
        legacy.rewrite_followup.assert_not_awaited()
        for messages in chat.received:
            assert str(USER) not in json.dumps([m.model_dump(mode="json") for m in messages])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        "Count documents tagged confidential.",
        "List files in the Finance folder.",
        "Summarize documents changed this week.",
    ],
)
async def test_unsupported_scope_blocks_before_inventory_and_persists_safe_answer(
    monkeypatch, question
):
    async with api(
        monkeypatch,
        [
            call("files_query", inventory("COUNT")),
            AgentStepResult(text="That restriction is unsupported."),
        ],
    ) as (client, db, chat, retriever, _legacy):
        response = await client.post("/api/v1/chat", json={"question": question})
        assert response.status_code == 200
        public(response.json())
        assert not db.statements and not retriever.requests
        assert "UNSUPPORTED_SCOPE" in chat.received[1][-1].text
        assert db.closed


@pytest.mark.asyncio
async def test_ambiguous_file_and_no_evidence(monkeypatch):
    async with api(
        monkeypatch,
        [
            call("resolve_file", {"reference": "report.pdf"}),
            AgentStepResult(text="Please disambiguate the two files."),
        ],
        files=[file(10), file(11)],
    ) as (client, db, chat, retriever, _legacy):
        response = await client.post("/api/v1/chat", json={"question": "Summarize report.pdf."})
        assert response.status_code == 200 and "disambiguate" in response.json()["answer"]
        assert "AMBIGUOUS" in chat.received[1][-1].text and not retriever.requests
    async with api(
        monkeypatch,
        [search(), AgentStepResult(text="The index provided insufficient evidence.")],
        chunks=[],
    ) as (client, db, chat, retriever, _legacy):
        response = await client.post(
            "/api/v1/chat", json={"question": "What is the unknown policy?"}
        )
        assert response.status_code == 200 and not response.json()["citations"]
        assert response.json()["retrieval_count"] == 0 and db.closed


@pytest.mark.asyncio
async def test_exact_focused_and_truncation(monkeypatch):
    steps = [
        call("resolve_file", {"reference": "report.pdf"}),
        call(
            "file_evidence",
            {
                "file_handle": {"kind": "FILE", "value": "file_1"},
                "mode": "QUERY_FOCUSED",
                "query": "deadline",
            },
            "read",
        ),
        AgentStepResult(text="Approval is required. [source_1]"),
    ]
    async with api(monkeypatch, steps) as (client, _db, chat, retriever, _legacy):
        response = await client.post(
            "/api/v1/chat", json={"question": "What deadline is in report.pdf?"}
        )
        assert response.status_code == 200
        assert isinstance(retriever.requests[0].scope, ResolvedFileScope)
        assert retriever.requests[0].scope.file_ids == (UUID(int=10),)
    async with api(
        monkeypatch,
        [
            call("files_query", inventory("LATEST")),
            full(),
            AgentStepResult(text="This portion introduces a project. [source_1]"),
        ],
        budget=6,
    ) as (client, _db, chat, retriever, _legacy):
        response = await client.post("/api/v1/chat", json={"question": "Summarize my latest file."})
        assert response.status_code == 200
        assert response.json()["answer"].startswith(TRUNCATION_NOTICE)
        assert '"truncated":true' in chat.received[2][-1].text
        assert not retriever.requests


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "steps",
    [
        [ChatError("private token XYZ")],
        [AgentStepResult(text=str(UUID(int=10)))],
        [
            call(
                "files_query",
                {
                    "operation": "COUNT",
                    "scope": {"kind": "ALL_ELIGIBLE_INDEXED_FILES"},
                    "user_id": str(UUID(int=2)),
                },
            ),
            AgentStepResult(text="Invalid arguments."),
        ],
    ],
)
async def test_failures_no_fallback_or_sensitive_error(monkeypatch, steps):
    async with api(monkeypatch, steps) as (client, db, _chat, _retriever, legacy):
        response = await client.post(
            "/api/v1/chat", json={"question": "Use the index.", "user_id": str(UUID(int=2))}
        )
        assert response.status_code in (200, 503)
        assert "private token XYZ" not in response.text and str(UUID(int=2)) not in response.text
        assert db.closed
        legacy.generate_grounded_answer.assert_not_awaited()
        if response.status_code == 503:
            assert not db.saved
        else:
            assert response.json()["user_id"] == str(USER)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["files_query", "unknown"])
async def test_integrated_cycle_limit(monkeypatch, name):
    steps = [
        call(name, inventory() if name == "files_query" else {}, f"call_{i}") for i in range(6)
    ]
    async with api(monkeypatch, steps) as (client, db, chat, _retriever, _legacy):
        response = await client.post("/api/v1/chat", json={"question": "Keep working"})
        assert response.status_code == 200
        assert "available tool steps" in response.json()["answer"]
        assert len(chat.received) == 6 and db.closed
        assert sum("SELECT drive_files" in str(s) for s in db.statements) <= 5


@pytest.mark.asyncio
async def test_flag_off_does_not_invoke_agent(monkeypatch):
    async with api(monkeypatch, [RuntimeError("Agent must not run")], enabled=False) as (
        client,
        _db,
        chat,
        _retriever,
        legacy,
    ):
        response = await client.post("/api/v1/chat", json={"question": "Hello"})
        assert response.status_code == 200 and response.json()["answer"] == "Legacy hello"
        assert not chat.received
        legacy.generate_direct_answer.assert_awaited_once_with("Hello")
        assert Settings().tool_rag_agent_enabled is False


@pytest.mark.asyncio
async def test_history_and_request_registry_isolation(monkeypatch):
    steps = [
        call("resolve_file", {"reference": "report.pdf"}),
        full(),
        AgentStepResult(text="Deadline is March 18. [source_1]"),
        full(identifier="old_handle"),
        AgentStepResult(text="Please name the file."),
        call("resolve_file", {"reference": "report.pdf"}, "new_resolve"),
        full(identifier="new_read"),
        AgentStepResult(text="Deadline is March 18. [source_1]"),
    ]
    async with api(monkeypatch, steps) as (client, _db, chat, _retriever, _legacy):
        first = (
            await client.post("/api/v1/chat", json={"question": "Summarize report.pdf."})
        ).json()
        history = [
            {"role": "user", "text": "Summarize report.pdf."},
            {"role": "assistant", "text": first["answer"]},
        ]
        second = await client.post(
            "/api/v1/chat",
            json={"question": "Explain that more.", "conversation_id": "one", "history": history},
        )
        assert second.status_code == 200
        assert "UNKNOWN_HANDLE" in chat.received[4][-1].text
        third = await client.post(
            "/api/v1/chat",
            json={
                "question": "Explain report.pdf more.",
                "conversation_id": "one",
                "history": history,
            },
        )
        assert third.status_code == 200 and third.json()["citations"]
        assert not any(m.call_id for m in chat.received[3])
        assert [m.role for m in chat.received[3]][-3:] == ["USER", "ASSISTANT", "USER"]
        assert all("file_1" not in m.text for m in chat.received[3] if m.text)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question, history, answer",
    [
        (
            "Summarize the first one.",
            [
                {"role": "user", "text": "List my files."},
                {"role": "assistant", "text": "report.pdf, other.pdf"},
            ],
            "Please specify the filename from that earlier list.",
        ),
        (
            "Who owns the checklist?",
            [
                {"role": "user", "text": "What is the pilot date?"},
                {"role": "assistant", "text": "March 25."},
            ],
            "Mira owns the checklist. [source_1]",
        ),
        (
            "What did I ask previously?",
            [{"role": "user", "text": "What is the pilot date?"}],
            "You asked: What is the pilot date?",
        ),
    ],
)
async def test_bounded_history_edge_cases(monkeypatch, question, history, answer):
    steps = (
        [search(), AgentStepResult(text=answer)]
        if "checklist" in question
        else [AgentStepResult(text=answer)]
    )
    async with api(monkeypatch, steps) as (client, _db, chat, _retriever, legacy):
        response = await client.post(
            "/api/v1/chat",
            json={"question": question, "conversation_id": "bounded", "history": history},
        )
        assert response.status_code == 200
        assert chat.received[0][-1].text == question
        assert "previous inventory list is not authoritative" in chat.received[0][1].text
        assert sum(len(m.text or "") for m in chat.received[0][2:-1]) <= 6000
        legacy.rewrite_followup.assert_not_awaited()


def test_bounded_history_scrubs_identifiers_without_replaying_tools():
    turns = [
        {"role": "assistant", "text": "old file_1 " + str(UUID(int=10)) + " a" * 4000}
        for _ in range(8)
    ]
    history = bounded_agent_history(turns)
    assert len(history) <= 6 and sum(len(m.text or "") for m in history) <= 6000
    assert all(
        "file_1" not in (m.text or "")
        and str(UUID(int=10)) not in (m.text or "")
        and not m.tool_calls
        for m in history
    )


@pytest.mark.asyncio
async def test_cancellation_closes_request_resources(monkeypatch):
    started = asyncio.Event()

    async with api(monkeypatch, []) as (client, db, chat, _retriever, _legacy):

        async def wait_step(**kwargs):
            started.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(chat, "step", wait_step)
        task = asyncio.create_task(client.post("/api/v1/chat", json={"question": "Hello"}))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert db.closed and not db.saved and not db.statements


@pytest.mark.asyncio
async def test_multisource_citation_order_dedup_and_schema(monkeypatch):
    from dataclasses import replace
    from app.schemas.chat import ChatResponse

    one = chunk()
    two = replace(one, chunk_id=UUID(int=31), chunk_index=1)
    three = replace(
        one,
        chunk_id=UUID(int=32),
        document_id=UUID(int=40),
        drive_file_id=UUID(int=11),
        filename="other.pdf",
    )
    async with api(
        monkeypatch,
        [
            search(),
            AgentStepResult(text="Supported [source_3] [source_1] [source_3] [source_999]."),
        ],
        files=[file(10), file(11, "other.pdf")],
        chunks=[one, two, three],
    ) as (client, _db, _chat, _retriever, _legacy):
        response = await client.post("/api/v1/chat", json={"question": "Compare documents"})
        assert response.status_code == 200
        body = response.json()
        public(body)
        ChatResponse.model_validate(body)
        assert [c["chunk_id"] for c in body["citations"]] == [
            str(three.chunk_id),
            str(one.chunk_id),
        ]
        assert "[1] [2] [1]" in body["answer"] and "999" not in body["answer"]
        assert body["retrieval_count"] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["other_owner", "not_indexed", "raw_uuid", "wrong_kind"])
async def test_authorization_injected_identifiers_and_scoped_hydration(monkeypatch, bad):
    from dataclasses import replace
    from app.db.enums import DriveFileStatus

    steps = [
        call("resolve_file", {"reference": "report.pdf"}),
        full(),
        AgentStepResult(text="Insufficient authorized evidence."),
    ]
    files = [file(10), file(11, user=UUID(int=2))]
    chunks = [replace(chunk(), drive_file_id=UUID(int=11))] if bad == "other_owner" else [chunk()]
    if bad == "not_indexed":
        files = [file(10, status=DriveFileStatus.FAILED)]
        steps = [
            call("resolve_file", {"reference": "report.pdf"}),
            AgentStepResult(text="No indexed file matched."),
        ]
    if bad in ("raw_uuid", "wrong_kind"):
        args = {
            "file_handle": {"kind": "FILE", "value": str(UUID(int=10))}
            if bad == "raw_uuid"
            else {"kind": "SOURCE", "value": "source_1"},
            "mode": "FULL_DOCUMENT",
        }
        steps = [
            call("file_evidence", args),
            AgentStepResult(text="Please resolve a filename first."),
        ]
    if bad == "other_owner":
        steps = [search(), AgentStepResult(text="No authorized evidence.")]
    async with api(monkeypatch, steps, files=files, chunks=chunks) as (
        client,
        db,
        _chat,
        _retriever,
        legacy,
    ):
        response = await client.post("/api/v1/chat", json={"question": "Read document"})
        assert response.status_code in (200, 503)
        assert str(UUID(int=11)) not in response.text
        assert str(UUID(int=2)) not in response.text
        if response.status_code == 200:
            assert not response.json()["citations"]
        legacy.generate_grounded_answer.assert_not_awaited()
        assert db.closed


@pytest.mark.asyncio
async def test_timeout_and_owned_client_cleanup(monkeypatch):
    import app.services.tool_agent_service as integration

    closed = []

    class OwnedChat:
        async def step(self, **kwargs) -> AgentStepResult:
            await asyncio.sleep(1)
            return AgentStepResult(text="Too late")

        async def aclose(self):
            closed.append(True)

    monkeypatch.setattr(integration, "TOOL_AGENT_TIMEOUT_SECONDS", 0.001)
    monkeypatch.setattr(integration, "OpenAIAgentChatService", lambda settings: OwnedChat())
    db = RequestDB([file()], [])
    adapter = ToolAgentAdapter(cast(AsyncSession, db), Settings())
    with pytest.raises(ChatError, match="timed out safely"):
        await adapter.answer("Hello", user_id=USER, history=(), history_window_complete=False)
    assert closed == [True] and not db.statements and not db.saved


@pytest.mark.asyncio
async def test_malformed_call_and_duplicate_ids_do_not_execute(monkeypatch):
    from app.agents.tool_rag.agent_models import ToolCallRequest

    malformed = AgentStepResult(
        tool_calls=(
            ToolCallRequest(
                call_id="malformed",
                tool_name="files_query",
                arguments={},
                argument_error="INVALID_ARGUMENT",
            ),
        )
    )
    async with api(
        monkeypatch, [malformed, AgentStepResult(text="The arguments were invalid.")]
    ) as (client, db, chat, _retriever, _legacy):
        response = await client.post("/api/v1/chat", json={"question": "Count files"})
        assert response.status_code == 200 and not db.statements
        assert chat.received[1][-1].call_id == "malformed"
    async with api(
        monkeypatch,
        [call("files_query", inventory(), "repeat"), call("files_query", inventory(), "repeat")],
    ) as (client, db, chat, _retriever, _legacy):
        response = await client.post("/api/v1/chat", json={"question": "List files"})
        assert response.status_code == 503 and len(db.statements) == 1 and db.closed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        "Summarize the first one.",
        "Summarize the second one.",
        "Summarize that file.",
        "Explain that document.",
    ],
)
async def test_cross_turn_inferred_filename_blocked_before_db(monkeypatch, question):
    steps = [
        call("resolve_file", {"reference": "report.pdf"}),
        AgentStepResult(text="Which filename do you mean?"),
    ]
    async with api(monkeypatch, steps) as (client, db, chat, retriever, legacy):
        response = await client.post(
            "/api/v1/chat",
            json={
                "question": question,
                "conversation_id": "prior",
                "history": [{"role": "assistant", "text": "1. report.pdf\n2. other.pdf"}],
            },
        )
        assert response.status_code == 200 and "Which filename" in response.json()["answer"]
        assert not db.statements and not retriever.requests
        assert "UNRESOLVED_CROSS_TURN_REFERENCE" in chat.received[1][-1].text
        assert not response.json()["citations"]
        assert db.closed
        legacy.generate_grounded_answer.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        "Summarize report.pdf.",
        "Explain report.pdf more.",
        "Tell me about report.pdf.",
        "Summarize that file: report.pdf.",
    ],
)
async def test_cross_turn_explicit_filename_remains_supported(monkeypatch, question):
    steps = [
        call("resolve_file", {"reference": "report.pdf"}),
        full(),
        AgentStepResult(text="Project deadline is March 18. [source_1]"),
    ]
    async with api(monkeypatch, steps) as (client, db, chat, retriever, _legacy):
        response = await client.post(
            "/api/v1/chat",
            json={
                "question": question,
                "conversation_id": "prior",
                "history": [{"role": "assistant", "text": "Previous files: other.pdf"}],
            },
        )
        assert response.status_code == 200 and response.json()["citations"]
        assert "UNRESOLVED_CROSS_TURN_REFERENCE" not in chat.received[1][-1].text
        assert db.closed and not retriever.requests
        public(response.json())


@pytest.mark.asyncio
async def test_cross_turn_guard_allows_current_run_filename_provenance(monkeypatch):
    steps = [
        call("files_query", inventory(), "list"),
        call("resolve_file", {"reference": "report.pdf"}, "resolve"),
        full(),
        AgentStepResult(text="Project deadline is March 18. [source_1]"),
    ]
    async with api(monkeypatch, steps) as (client, _db, chat, _retriever, _legacy):
        response = await client.post(
            "/api/v1/chat",
            json={
                "question": "List current files and summarize the first one.",
                "conversation_id": "prior",
                "history": [{"role": "assistant", "text": "An old list mentioned other.pdf."}],
            },
        )
        assert response.status_code == 200 and response.json()["citations"]
        assert "RESOLVED" in chat.received[2][-1].text
        assert "UNRESOLVED_CROSS_TURN_REFERENCE" not in chat.received[2][-1].text
        public(response.json())


def test_cross_turn_guard_is_bounded_and_literal_only():
    from app.agents.tool_rag.cross_turn_guard import unresolved_cross_turn_reference as guard

    args = {"has_prior_history": True, "proposed_reference": "report.pdf", "returned_in_run": False}
    assert guard(question="Summarize the first one.", **args)
    assert not guard(question="Explain that more.", **args)
    assert not guard(question="What did I ask before?", **args)
    assert not guard(question="Hello", **args)
    assert not guard(question="What is our refund policy?", **args)
    assert not guard(question='Summarize that file: "REPORT.PDF".', **args)
    assert guard(question="Summarize that file: old.report.pdf.", **args)
    assert not guard(question="Summarize the first one.", **{**args, "has_prior_history": False})
    assert not guard(question="Summarize the first one.", **{**args, "returned_in_run": True})


@pytest.mark.asyncio
async def test_empty_file_evidence_does_not_turn_into_an_absence_claim(monkeypatch):
    from app.llm.prompts import no_evidence_answer

    steps = [
        call("resolve_file", {"reference": "report.pdf"}),
        call(
            "file_evidence",
            {
                "file_handle": {"kind": "FILE", "value": "file_1"},
                "mode": "QUERY_FOCUSED",
                "query": "deadline",
            },
            "read",
        ),
        AgentStepResult(text="There is no deadline in that file."),
    ]
    async with api(monkeypatch, steps, chunks=[]) as (client, _db, _chat, retriever, _legacy):
        response = await client.post(
            "/api/v1/chat", json={"question": "What deadline is in report.pdf?"}
        )
        assert response.status_code == 200
        assert response.json()["answer"] == no_evidence_answer(demo_mode=False)
        assert not response.json()["citations"]
        assert response.json()["retrieval_count"] == 0
        assert isinstance(retriever.requests[0].scope, ResolvedFileScope)
        assert len(retriever.requests) == 1  # no corpus retry/fallback
