"""Mixed tool provenance must constrain actual API publication, not just citations."""

from uuid import UUID

import pytest

from app.agents.tool_rag.agent_models import AgentStepResult
from tests.agents.tool_rag.test_agent_loop import call, inventory
from tests.agents.tool_rag.test_revision_safety import row
from tests.agents.tool_rag.test_tool_execution import chunk, file
from tests.test_tool_agent_api import api, full, search
from tests.services.test_conversation_failure_diagnostics import execution as execution

FABRICATED = "other.pdf proves the invented private claim. [source_1]"


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["empty", "resolve_only", "missing", "ambiguous", "failed"])
async def test_unrelated_evidence_cannot_authorize_target_claim(monkeypatch, outcome):
    files = [file(), file(11, "other.pdf")]
    steps = [search()]
    if outcome == "failed":
        steps.append(call("unknown", {}, "failure"))
    else:
        if outcome == "ambiguous":
            files.append(file(12, "other.pdf"))
        reference = "missing.pdf" if outcome == "missing" else "other.pdf"
        steps.append(call("resolve_file", {"reference": reference}, "resolve_b"))
        if outcome == "empty":
            steps.append(full("file_2", "empty_b"))
    steps.append(AgentStepResult(text=FABRICATED))
    async with api(monkeypatch, steps, files=files) as (client, db, *_):
        response = await client.post("/api/v1/chat", json={"question": "Summarize other.pdf"})
        assert response.status_code == 200
        body = response.json()
        assert "invented private claim" not in body["answer"]
        assert body["citations"] == []
        assert len(db.saved) == 1
        assert db.saved[0].answer == body["answer"]
        assert "invented private claim" not in db.saved[0].answer
        assert not db.saved[0].citations_json
        if outcome == "empty":
            assert "enough evidence" in body["answer"]
        elif outcome == "resolve_only":
            assert "Found indexed file: other.pdf" in body["answer"]
        elif outcome == "missing":
            assert "No eligible indexed file" in body["answer"]
        elif outcome == "ambiguous":
            assert "disambiguate" in body["answer"]
        else:
            assert "Tool arguments are invalid" in body["answer"]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["COUNT", "LIST", "LATEST", "OLDEST"])
@pytest.mark.parametrize("inventory_first", [False, True])
async def test_inventory_remains_authoritative_after_content(
    monkeypatch, operation, inventory_first
):
    ordered = [search(), call("files_query", inventory(operation), "inventory")]
    if inventory_first:
        ordered.reverse()
    async with api(
        monkeypatch,
        ordered + [AgentStepResult(text="Indexed files: 999. fabricated.pdf")],
        files=[file(), file(11, "other.pdf", day=2)],
    ) as (client, db, *_):
        response = await client.post("/api/v1/chat", json={"question": "Show my files"})
        assert response.status_code == 200
        body = response.json()
        assert "999" not in body["answer"] and "fabricated.pdf" not in body["answer"]
        assert not body["citations"]
        if operation == "COUNT":
            assert "Indexed files: 2." in body["answer"]
        elif operation == "LIST":
            assert "Indexed files: 2." in body["answer"]
            assert "other.pdf" in body["answer"] and "report.pdf" in body["answer"]
        elif operation == "LATEST":
            assert "Latest indexed file: other.pdf" in body["answer"]
        else:
            assert "Oldest indexed file: report.pdf" in body["answer"]
        assert db.saved[0].answer == body["answer"] and not db.saved[0].citations_json


@pytest.mark.asyncio
@pytest.mark.parametrize("cross_document", [False, True])
async def test_valid_target_and_cross_document_answers_remain_publishable(
    monkeypatch, cross_document
):
    brow = (
        *row(0, "B authorized content.", file_id=UUID(int=11), document=101)[:4],
        "other.pdf",
        UUID(int=11),
    )
    answer = "B authorized content. [source_2]"
    if cross_document:
        answer = "A and B authorized content. [source_1] [source_2]"
    async with api(
        monkeypatch,
        [
            search(),
            call("resolve_file", {"reference": "other.pdf"}, "resolve_b"),
            full("file_2", "read_b"),
            AgentStepResult(text=answer),
        ],
        files=[file(), file(11, "other.pdf")],
        rows=[brow],
        chunks=[chunk()],
    ) as (client, db, *_):
        response = await client.post("/api/v1/chat", json={"question": "Compare the documents"})
        assert response.status_code == 200
        body = response.json()
        ids = {c["drive_file_id"] for c in body["citations"]}
        assert ids == (
            {str(UUID(int=10)), str(UUID(int=11))} if cross_document else {str(UUID(int=11))}
        )
        assert "authorized content" in db.saved[0].answer
        assert db.saved[0].citations_json == body["citations"]


@pytest.mark.asyncio
async def test_later_unrelated_read_does_not_satisfy_resolved_target(monkeypatch):
    async with api(
        monkeypatch,
        [
            call("resolve_file", {"reference": "other.pdf"}, "resolve_b"),
            search(),
            AgentStepResult(text=FABRICATED),
        ],
        files=[file(), file(11, "other.pdf")],
    ) as (client, db, *_):
        response = await client.post("/api/v1/chat", json={"question": "Summarize other.pdf"})
        assert response.status_code == 200
        assert "Found indexed file: other.pdf" in response.json()["answer"]
        assert "invented private claim" not in db.saved[0].answer
        assert not response.json()["citations"]


@pytest.mark.asyncio
async def test_empty_search_after_success_does_not_publish_old_evidence(monkeypatch):
    from tests.test_tool_agent_api import ScriptRetriever

    original = ScriptRetriever.retrieve

    async def retrieve(self, request):
        if self.requests:
            self.requests.append(request)
            return []
        return await original(self, request)

    monkeypatch.setattr(ScriptRetriever, "retrieve", retrieve)
    async with api(
        monkeypatch, [search(), search("empty_search"), AgentStepResult(text=FABRICATED)]
    ) as (client, db, *_):
        response = await client.post("/api/v1/chat", json={"question": "Summarize other.pdf"})
        assert response.status_code == 200
        assert "enough evidence" in response.json()["answer"]
        assert "invented private claim" not in db.saved[0].answer
        assert not response.json()["citations"]


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["empty_target", "count"])
async def test_durable_completed_turn_contains_only_controlled_result(
    monkeypatch, execution, scenario
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from uuid import uuid4

    from app.core.config import Settings
    from app.services.conversation_chat_service import TurnStatus
    from app.services.rag_service import RagService
    from app.services.tool_agent_service import ToolAgentAdapter
    from tests.agents.tool_rag.test_tool_execution import USER

    steps = [search()]
    if scenario == "empty_target":
        steps += [
            call("resolve_file", {"reference": "other.pdf"}, "resolve_b"),
            full("file_2", "read_b"),
        ]
        claim = FABRICATED
    else:
        steps += [call("files_query", inventory("COUNT"), "count")]
        claim = "Indexed files: 999"
    steps.append(AgentStepResult(text=claim))
    async with api(monkeypatch, steps, files=[file(), file(11, "other.pdf")]) as (
        _client,
        db,
        chat,
        retriever,
        _legacy,
    ):
        settings = Settings(tool_rag_agent_enabled=True, demo_mode=False)
        rag = RagService(
            db,
            settings,
            retriever=retriever,
            tool_agent=ToolAgentAdapter(db, settings, chat=chat, retriever=retriever),
            persist_query_history=False,
        )
        execution.service.settings = settings
        execution.service.rag_factory = lambda _db, _settings: rag
        execution.principal.corpus_user_id = USER
        execution.service._status = AsyncMock(
            side_effect=[
                SimpleNamespace(status=TurnStatus.RUNNING),
                SimpleNamespace(status=TurnStatus.COMPLETED),
            ]
        )
        receipt, status = await execution.service.submit(
            execution.principal, uuid4(), execution.body
        )
        assert status == 200 and receipt.turn.status == TurnStatus.COMPLETED
        execution.repo.complete.assert_awaited_once()
        execution.repo.fail.assert_not_awaited()
        saved = execution.service.db.add.call_args.args[0]
        assert "invented private claim" not in saved.answer and "999" not in saved.answer
        assert not saved.citations_json
        if scenario == "count":
            assert "Indexed files: 2." in saved.answer
        else:
            assert "enough evidence" in saved.answer


@pytest.mark.asyncio
async def test_both_explicit_targets_require_and_receive_content(monkeypatch):
    rows = [row(0, "A authorized content.")]
    rows.append(
        (
            *row(0, "B authorized content.", file_id=UUID(int=11), document=101)[:4],
            "other.pdf",
            UUID(int=11),
        )
    )
    async with api(
        monkeypatch,
        [
            call("resolve_file", {"reference": "report.pdf"}, "resolve_a"),
            full("file_1", "read_a"),
            call("resolve_file", {"reference": "other.pdf"}, "resolve_b"),
            full("file_2", "read_b"),
            AgentStepResult(text="A and B authorized content. [source_1] [source_2]"),
        ],
        files=[file(), file(11, "other.pdf")],
        rows=rows,
    ) as (client, db, *_):
        response = await client.post(
            "/api/v1/chat", json={"question": "Compare report.pdf and other.pdf"}
        )
        assert response.status_code == 200
        assert {c["drive_file_id"] for c in response.json()["citations"]} == {
            str(UUID(int=10)),
            str(UUID(int=11)),
        }
        assert "A and B authorized content" in db.saved[0].answer


@pytest.mark.asyncio
async def test_new_successful_read_does_not_erase_an_unread_target(monkeypatch):
    async with api(
        monkeypatch,
        [
            search(),
            call("resolve_file", {"reference": "other.pdf"}, "resolve_b"),
            call("resolve_file", {"reference": "report.pdf"}, "resolve_a"),
            full("file_1", "read_a"),
            AgentStepResult(text=FABRICATED),
        ],
        files=[file(), file(11, "other.pdf")],
    ) as (client, db, *_):
        response = await client.post("/api/v1/chat", json={"question": "Summarize other.pdf"})
        assert response.status_code == 200
        assert "Found indexed file: other.pdf" in response.json()["answer"]
        assert "invented private claim" not in db.saved[0].answer and not db.saved[0].citations_json


@pytest.mark.asyncio
async def test_failed_target_read_after_success_is_not_published(monkeypatch):
    from tests.agents.tool_rag.test_revision_safety import DocumentDB

    original = DocumentDB.execute

    async def execute(self, statement):
        if statement.compile().params["id_1"] == UUID(int=11):
            raise RuntimeError("SYNTHETIC_PRIVATE_TOOL_FAILURE")
        return await original(self, statement)

    monkeypatch.setattr(DocumentDB, "execute", execute)
    async with api(
        monkeypatch,
        [
            search(),
            call("resolve_file", {"reference": "other.pdf"}, "resolve_b"),
            full("file_2", "read_b"),
            AgentStepResult(text=FABRICATED),
        ],
        files=[file(), file(11, "other.pdf")],
    ) as (client, db, *_):
        response = await client.post("/api/v1/chat", json={"question": "Summarize other.pdf"})
        assert response.status_code == 503
        assert "invented private claim" not in response.text
        assert "SYNTHETIC_PRIVATE_TOOL_FAILURE" not in response.text
        assert not db.saved
