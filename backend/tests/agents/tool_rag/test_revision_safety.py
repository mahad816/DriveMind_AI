"""One allowed revision: document-local reads, bounded scope guard, final sources."""

import json
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects import postgresql

from app.agents.tool_rag import contracts as c
from app.agents.tool_rag.agent_service import ToolRagAgentService
from app.agents.tool_rag.agent_models import AgentStepResult
from app.agents.tool_rag.execution.context import ExecutionContext
from app.agents.tool_rag.execution.executor import ToolExecutor
from app.agents.tool_rag.handles import RuntimeHandleRegistry
from app.agents.tool_rag.scope_guard import unsupported_scope_widening
from app.agents.tool_rag.errors import ToolErrorCode
from app.db.enums import DriveFileStatus
from app.routing.intent_frame.scope import ResolvedFileScope
from tests.agents.tool_rag.test_tool_execution import InventoryDB, file, chunk, USER
from tests.agents.tool_rag.test_agent_loop import ScriptChat, call, inventory


class DocumentDB(InventoryDB):
    def __init__(self, files=(), rows=()):
        super().__init__(files)
        self.document_rows = list(rows)

    async def execute(self, statement):
        self.statements.append(statement)
        params = statement.compile().params
        assert params["user_id_1"] == USER
        assert params["status_1"] == DriveFileStatus.INDEXED
        assert params["id_1"] in {f.id for f in self.files}
        assert "JOIN documents" in str(statement) and "JOIN drive_files" in str(statement)
        selected = [row for row in self.document_rows if row[5] == params["id_1"]]
        selected.sort(key=lambda row: (row[1].int, row[2]))
        if "sum(" in str(statement):
            return SimpleNamespace(
                one=lambda: (len(selected), sum(len(row[3]) for row in selected))
            )
        assert "ORDER BY documents.id ASC, chunks.chunk_index ASC" in str(statement)
        budget = params["substr_3"]
        assert params["param_1"] == 20
        return [(*row[:3], row[3][:budget], row[4]) for row in selected[:20]]


def row(index, text, file_id=UUID(int=10), document=100):
    return (
        UUID(int=200 + index + document),
        UUID(int=document),
        index,
        text,
        "report.pdf",
        file_id,
    )


def make_context(files=None, rows=(), budget=12000, question=""):
    registry = RuntimeHandleRegistry()
    registry.register_file(UUID(int=10))
    return ExecutionContext(
        user_id=USER,
        db=cast(AsyncSession, DocumentDB(files if files is not None else [file()], rows)),
        handles=registry,
        retriever=None,
        max_context_chars=budget,
        original_question=question,
    )


async def full(ctx, handle="file_1"):
    return await ToolExecutor().execute(
        "file_evidence",
        json.dumps({"file_handle": {"kind": "FILE", "value": handle}, "mode": "FULL_DOCUMENT"}),
        ctx,
    )


@pytest.mark.asyncio
async def test_full_local_order_budget_source_prefix_and_no_retrieval():
    other = UUID(int=11)
    ctx = make_context(
        rows=[row(2, "CCCC"), row(0, "AAAA"), row(1, "BBBB"), row(0, "PRIVATE", other)], budget=6
    )
    spy = AsyncMock()
    object.__setattr__(ctx, "retriever", spy)
    result = await full(ctx)
    assert result.error is None
    rich = result.internal_result
    assert isinstance(rich, c.FileEvidenceResult)
    assert [s.members[0].chunk_index for s in rich.sections] == [0, 1]
    assert [s.combined_text for s in rich.sections] == ["AAAA", "BB"]
    assert sum(len(s.combined_text) for s in rich.sections) == 6
    assert isinstance(result.llm_result, c.FileEvidencePayload)
    assert result.llm_result.truncated
    assert result.llm_result.coverage == c.DocumentReadCoverage(total_chunks=3, total_chars=12)
    assert all(s.member_ranges[0][0] == s.members[0].chunk_id for s in rich.sections)
    assert "PRIVATE" not in result.llm_result.model_dump_json()
    assert str(UUID(int=10)) not in result.llm_result.model_dump_json()
    spy.retrieve.assert_not_awaited()
    sql = str(cast(DocumentDB, ctx.db).statements[-1].compile(dialect=postgresql.dialect()))
    assert "substr(" in sql and "LIMIT" in sql


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rows, truncated",
    [((), False), ((row(0, "content"),), False), (tuple(row(i, "x") for i in range(21)), True)],
)
async def test_empty_complete_and_row_cap(rows, truncated):
    result = await full(make_context(rows=rows))
    assert result.error is None
    assert isinstance(result.llm_result, c.FileEvidencePayload)
    assert result.llm_result.truncated == truncated
    assert len(result.llm_result.sections) <= 20


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "files, handle, code",
    [
        ([file(user=UUID(int=2))], "file_1", ToolErrorCode.NOT_FOUND),
        ([file(status=DriveFileStatus.FAILED)], "file_1", ToolErrorCode.NOT_FOUND),
        ([file()], "file_9", ToolErrorCode.UNKNOWN_HANDLE),
    ],
)
async def test_full_revalidates_ownership_status_handle(files, handle, code):
    ctx = make_context(files=files, rows=[row(0, "content")])
    result = await full(ctx, handle)
    assert result.error and result.error.code == code
    assert not any("substr(" in str(s) for s in cast(DocumentDB, ctx.db).statements)


@pytest.mark.asyncio
async def test_query_focused_still_exact_hybrid():
    ctx = make_context()
    spy = AsyncMock()
    spy.retrieve.return_value = [chunk()]
    object.__setattr__(ctx, "retriever", spy)
    result = await ToolExecutor().execute(
        "file_evidence",
        json.dumps(
            {
                "file_handle": {"kind": "FILE", "value": "file_1"},
                "mode": "QUERY_FOCUSED",
                "query": "deadline",
            }
        ),
        ctx,
    )
    assert result.error is None
    request = spy.retrieve.await_args.args[0]
    assert isinstance(request.scope, ResolvedFileScope)
    assert request.scope.file_ids == (UUID(int=10),)
    assert not any("substr(" in str(s) for s in cast(DocumentDB, ctx.db).statements)


def test_mode_is_bounded_and_specific_query_required():
    handle = {"kind": "FILE", "value": "file_1"}
    for data in [
        {"file_handle": handle},
        {"file_handle": handle, "mode": "MAGIC"},
        {"file_handle": handle, "mode": "QUERY_FOCUSED", "query": ""},
    ]:
        with pytest.raises(ValidationError):
            c.FileEvidenceArguments.model_validate_json(json.dumps(data))
    assert (
        c.FileEvidenceArguments.model_validate_json(
            json.dumps({"file_handle": handle, "mode": "FULL_DOCUMENT"})
        ).query
        is None
    )


@pytest.mark.parametrize(
    "question",
    [
        "Count only documents tagged confidential.",
        "List files in the Finance folder.",
        "Summarize documents changed this week.",
        "Count documents modified after March 1.",
        "Search files labelled confidential.",
    ],
)
def test_guard_finite_restrictions(question):
    assert unsupported_scope_widening(
        question, c.FilesQueryArguments(operation="COUNT", scope=c.AllEligibleFiles())
    )
    assert unsupported_scope_widening(
        question, c.SearchKnowledgeArguments(query="topic", scope=c.AllEligibleFiles())
    )


@pytest.mark.parametrize(
    "question",
    [
        "How many files do I have?",
        "List all files.",
        "What is our refund policy?",
        "Summarize my latest file.",
        "Explain the Finance folder policy.",
    ],
)
def test_guard_negative_controls(question):
    assert not unsupported_scope_widening(
        question, c.FilesQueryArguments(operation="LIST", scope=c.AllEligibleFiles())
    )


@pytest.mark.asyncio
async def test_scope_guard_blocks_before_db_and_safe_tool_history():
    chat = ScriptChat(
        [
            call("files_query", inventory("COUNT")),
            AgentStepResult(text="I cannot apply a tag restriction."),
        ]
    )
    db = DocumentDB([file()])
    state = await ToolRagAgentService(chat).run(
        "Count only documents tagged confidential.", user_id=USER, db=cast(AsyncSession, db)
    )
    assert not db.statements
    error = state["tool_history"][0].result.error
    assert error is not None and error.code == ToolErrorCode.UNSUPPORTED_SCOPE
    assert "UNSUPPORTED_SCOPE" in chat.received[1][-1].text
    assert not state["citations"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "producer, index", [("LIST", 0), ("LATEST", 0), ("resolve_file", 0), ("LIST", 1)]
)
async def test_four_dependent_full_document_workflows(producer, index):
    files = [file(10, "a.pdf"), file(11, "b.pdf")]
    target = files[index]
    rows = [row(0, "Authoritative project overview.", target.id)]
    first = (
        call("resolve_file", {"reference": "a.pdf"})
        if producer == "resolve_file"
        else call("files_query", inventory(producer))
    )
    chat = ScriptChat(
        [
            first,
            call(
                "file_evidence",
                {
                    "file_handle": {"kind": "FILE", "value": f"file_{index + 1}"},
                    "mode": "FULL_DOCUMENT",
                },
                "call_2",
            ),
            AgentStepResult(text="This file describes the project. [source_1]"),
        ]
    )
    spy = AsyncMock()
    state = await ToolRagAgentService(chat).run(
        "Summarize the selected file.",
        user_id=USER,
        db=cast(AsyncSession, DocumentDB(files, rows)),
        retriever=spy,
    )
    assert state["failure"] is None
    assert state["evidence"][0].members[0].file_id == target.id
    assert state["final_answer"] is not None
    assert "[1]" in state["final_answer"] and "file_" not in state["final_answer"]
    assert state["citations"][0].chunk_id == rows[0][0]
    assert all(str(target.id) not in m.model_dump_json() for m in state["messages"])
    spy.retrieve.assert_not_awaited()
    assert [h.call.tool_name for h in state["tool_history"]] == [
        first.tool_calls[0].tool_name,
        "file_evidence",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "answer, failure, cited",
    [
        ("Supported answer. [source_1]", False, True),
        ("Supported answer. [evidence_1]", False, True),
        ("Supported answer.", False, True),
        ("Supported answer. [source_999]", False, True),
        ("Evidence from file_1.", True, False),
        ("Quoted literal source_999 stays unmodified.", True, False),
        (str(UUID(int=10)), True, False),
    ],
)
async def test_finalizer_authoritative_sources_and_output_validation(answer, failure, cited):
    chat = ScriptChat(
        [
            call(
                "file_evidence",
                {"file_handle": {"kind": "FILE", "value": "file_1"}, "mode": "FULL_DOCUMENT"},
            ),
            AgentStepResult(text=answer),
        ]
    )
    # Register through a producer to maintain real application handle provenance.
    chat.steps.insert(0, call("files_query", inventory("LATEST"), "producer"))
    state = await ToolRagAgentService(chat).run(
        "Summarize my latest file.",
        user_id=USER,
        db=cast(AsyncSession, DocumentDB([file()], [row(0, "Authoritative text.")])),
    )
    assert (state["failure"] is not None) == failure
    assert bool(state["citations"]) == cited
    answer_text = state["final_answer"]
    assert answer_text is not None
    assert not any(
        token in answer_text for token in ["file_1", "source_999", "evidence_1", str(UUID(int=10))]
    )
    assert state["evidence"][0].combined_text == "Authoritative text."
    if cited:
        assert {c.chunk_id for c in state["citations"]} == {row(0, "x")[0]}


@pytest.mark.asyncio
async def test_no_evidence_no_fake_citations():
    state = await ToolRagAgentService(ScriptChat([AgentStepResult(text="Hello [source_99]")])).run(
        "Hello", user_id=USER, db=cast(AsyncSession, DocumentDB())
    )
    assert state["final_answer"] is not None
    assert not state["citations"] and "source_99" not in state["final_answer"]
