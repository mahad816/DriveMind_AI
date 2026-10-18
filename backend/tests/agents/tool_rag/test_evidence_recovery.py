"""Exact-file recovery after empty focused retrieval; providers and SQL are isolated doubles."""

import json
from dataclasses import replace
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tool_rag.agent_models import AgentStepResult
from app.agents.tool_rag.execution.context import ExecutionContext
from app.agents.tool_rag.execution.executor import ToolExecutor
from app.agents.tool_rag.handles import RuntimeHandleRegistry
from app.retrieval.hybrid import HybridRetriever
from app.llm.prompts import no_evidence_answer
from tests.agents.tool_rag.test_agent_loop import call, inventory
from tests.agents.tool_rag.test_revision_safety import DocumentDB, row
from tests.agents.tool_rag.test_tool_execution import USER, file, chunk
from tests.test_tool_agent_api import api

QUESTION = "Compare Cover Letter and Project Plan: identify the applicant and project manager, their dates, and the launch prerequisite."
COVER = "Alex Example applies for a library assistant position and can begin on 1 November 2026."
PLAN = "Jordan Example manages Project Atlas, launching 15 November 2026 after security testing."


def source(number, name, content):
    value = row(0, content, file_id=UUID(int=number), document=100 + number)
    return (*value[:4], name, value[5])


def focused(handle, identifier):
    return call(
        "file_evidence",
        {
            "file_handle": {"kind": "FILE", "value": handle},
            "mode": "QUERY_FOCUSED",
            "query": "dates and people",
        },
        identifier,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("semantic_hit", [False, True])
async def test_exact_j_recovers_empty_reads_before_model_publication(monkeypatch, semantic_hit):
    steps = [
        call("resolve_file", {"reference": "Cover Letter"}, "resolve_cover"),
        call("resolve_file", {"reference": "Project Plan"}, "resolve_plan"),
        focused("file_1", "read_cover"),
        focused("file_2", "read_plan"),
        AgentStepResult(
            text="Alex Example applies for a library assistant position, available 1 November 2026. [source_1] Jordan Example manages Project Atlas, launching 15 November 2026 after security testing. [source_2]"
        ),
    ]
    async with api(
        monkeypatch,
        steps,
        files=[file(10, "Cover Letter"), file(11, "Project Plan")],
        rows=[source(10, "Cover Letter", COVER), source(11, "Project Plan", PLAN)],
        chunks=[],
    ) as (client, db, chat, retriever, _):
        if semantic_hit:

            async def retrieve(request):
                retriever.requests.append(request)
                if request.scope.file_ids == (UUID(int=11),):
                    return [
                        replace(
                            chunk(),
                            chunk_id=UUID(int=311),
                            document_id=UUID(int=111),
                            drive_file_id=UUID(int=11),
                            filename="Project Plan",
                            text=PLAN,
                        )
                    ]
                return []

            retriever.retrieve = retrieve
        response = await client.post("/api/v1/chat", json={"question": QUESTION})
        assert response.status_code == 200
        body = response.json()
        assert "1 November 2026" in body["answer"] and "15 November 2026" in body["answer"]
        assert {c["filename"] for c in body["citations"]} == {"Cover Letter", "Project Plan"}
        assert len(retriever.requests) == 2
        assert (
            db.saved[0].answer == body["answer"] and db.saved[0].citations_json == body["citations"]
        )
        assert any(
            '"mode":"FULL_DOCUMENT"' in m.text
            for messages in chat.received
            for m in messages
            if m.role == "TOOL"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["empty", "failed", "unauthorized", "contradictory"])
async def test_missing_failed_unauthorized_and_conflicting_sources(monkeypatch, kind):
    steps = [
        call("resolve_file", {"reference": "report.pdf"}),
        focused("file_1", "read"),
        AgentStepResult(
            text="The sources disagree: date A and date B. [source_1] [source_2]"
            if kind == "contradictory"
            else "Invented protected fact."
        ),
    ]
    files = [file(user=UUID(int=2))] if kind == "unauthorized" else [file()]
    rows = [row(0, "date A"), row(1, "date B")] if kind == "contradictory" else []
    async with api(monkeypatch, steps, files=files, rows=rows, chunks=[]) as (
        client,
        db,
        _chat,
        retriever,
        _,
    ):
        if kind == "failed":
            retriever.retrieve = AsyncMock(side_effect=RuntimeError("private provider failure"))
        response = await client.post(
            "/api/v1/chat", json={"question": "Compare the dates in report.pdf"}
        )
        if kind == "failed":
            assert response.status_code == 503
            assert not db.saved
            assert not any("JOIN documents" in str(stmt) for stmt in db.statements)
            assert "private provider failure" not in response.text
            return
        assert response.status_code == 200
        body = response.json()
        assert (
            "Invented protected fact" not in body["answer"]
            and "private provider failure" not in response.text
        )
        if kind == "contradictory":
            assert "date A and date B" in body["answer"] and len(body["citations"]) == 2
        else:
            assert not body["citations"]
        if kind in ("failed", "unauthorized"):
            assert not any("JOIN documents" in str(stmt) for stmt in db.statements)
        assert db.saved[0].answer == body["answer"]


@pytest.mark.asyncio
async def test_repeated_inventory_uses_authoritative_count_and_list(monkeypatch):
    for operation in ("COUNT", "LIST", "COUNT", "LIST"):
        async with api(
            monkeypatch,
            [call("files_query", inventory(operation)), AgentStepResult(text="999 invented.pdf")],
            files=[file(), file(11, "other.pdf")],
        ) as (client, db, *_):
            r = await client.post("/api/v1/chat", json={"question": "Show my indexed files"})
            assert r.status_code == 200 and "Indexed files: 2." in r.json()["answer"]
            assert "999" not in r.text and "invented.pdf" not in r.text
            if operation == "LIST":
                assert "report.pdf" in r.json()["answer"] and "other.pdf" in r.json()["answer"]
            assert db.saved[0].answer == r.json()["answer"]


@pytest.mark.asyncio
async def test_recovery_budget_is_per_request_and_once_per_file():
    files = [file(n) for n in (10, 11, 12)]
    db = DocumentDB(
        files,
        [row(0, "authorized content", file_id=f.id, document=100 + i) for i, f in enumerate(files)],
    )
    handles = RuntimeHandleRegistry()
    for f in files:
        handles.register_file(f.id)
    ctx = ExecutionContext(
        user_id=USER,
        db=cast(AsyncSession, db),
        handles=handles,
        retriever=cast(HybridRetriever, SimpleNamespace(retrieve=AsyncMock(return_value=[]))),
    )
    executor = ToolExecutor()
    for n in (1, 2):
        result = await executor.execute(
            "file_evidence", json.dumps(focused(f"file_{n}", str(n)).tool_calls[0].arguments), ctx
        )
        assert not result.error and result.internal_result.sections
        assert result.internal_result.mode == "FULL_DOCUMENT"
    reads = sum("JOIN documents" in str(stmt) for stmt in db.statements)
    for n in (1, 3):
        result = await executor.execute(
            "file_evidence", json.dumps(focused(f"file_{n}", str(n)).tool_calls[0].arguments), ctx
        )
        assert not result.error and not result.internal_result.sections
    assert (
        sum("JOIN documents" in str(stmt) for stmt in db.statements) == reads
    )  # No repeated/third source read.
    assert len(ctx.recovery_budget.attempted_files) == 2
    assert replace(ctx, recovery_budget=type(ctx.recovery_budget)()).recovery_budget.claim(
        files[2].id
    )


@pytest.mark.asyncio
async def test_exhausted_recovery_cannot_publish_unsupported_answer(monkeypatch):
    from app.agents.tool_rag.execution.context import EvidenceRecoveryBudget

    monkeypatch.setattr(EvidenceRecoveryBudget, "claim", lambda self, file_id: False)
    steps = [
        call("resolve_file", {"reference": "report.pdf"}),
        focused("file_1", "read"),
        AgentStepResult(text="Invented claim without evidence"),
    ]
    async with api(monkeypatch, steps, rows=[row(0, "real content")], chunks=[]) as (
        client,
        db,
        *_,
    ):
        r = await client.post("/api/v1/chat", json={"question": "Read report.pdf"})
        assert r.status_code == 200 and r.json()["answer"] == no_evidence_answer(demo_mode=False)
        assert not r.json()["citations"] and "Invented claim" not in db.saved[0].answer
        assert not any("JOIN documents" in str(stmt) for stmt in db.statements)
