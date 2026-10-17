"""Application-enforced provenance, never a model's claim to be grounded."""

from unittest.mock import AsyncMock

import pytest

from app.agents.tool_rag.agent_models import AgentStepResult
from app.agents.tool_rag.finalization import EMPTY_CONTENT, NO_CONTENT
from app.core.config import Settings
from app.services.tool_agent_service import ToolAgentAdapter
from tests.agents.tool_rag.test_agent_loop import ScriptChat, call, inventory, run
from tests.agents.tool_rag.test_tool_execution import file, USER

CLAIM = "The document describes experience in AI."
SEARCH = {"query": "policy", "scope": {"kind": "ALL_ELIGIBLE_INDEXED_FILES"}}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        "What does my Cover Letter say?",
        "Hi, summarize my file",
        "Which file?",
        "Thanks, what is the deadline?",
    ],
)
async def test_no_tools_never_publishes_arbitrary_prose(question):
    db = AsyncMock()
    result = await ToolAgentAdapter(
        db, Settings(_env_file=None), chat=ScriptChat([AgentStepResult(text=CLAIM)])
    ).answer(question, user_id=USER, history=[], history_window_complete=True)
    assert result.answer == NO_CONTENT
    assert result.citations == () and result.retrieval_count == 0
    assert not db.mock_calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question,expected", [("Hi", "Hello!"), ("Thanks!", "You're welcome!"), ("Hello", "Hello!")]
)
async def test_social_input_has_fixed_safe_output(question, expected):
    state, _, _ = await run([AgentStepResult(text=CLAIM)], question=question)
    assert state["final_answer"] == expected and not state["citations"]
    assert state["failure"] is None


@pytest.mark.asyncio
async def test_filename_resolution_is_not_content():
    state, _, _ = await run(
        [call("resolve_file", {"reference": "report.pdf"}), AgentStepResult(text=CLAIM)]
    )
    assert state["final_answer"] == "Found indexed file: report.pdf. " + NO_CONTENT
    assert not state["citations"] and state["retrieval_count"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "files,expected",
    [
        (
            [],
            "No eligible indexed file matches that name. Check the filename and preparation status.",
        ),
        (
            [file(), file(11)],
            "Please disambiguate the filename. Matching indexed files:\n- report.pdf\n- report.pdf",
        ),
    ],
)
async def test_missing_and_ambiguous_render_only_verified_result(files, expected):
    state, _, _ = await run(
        [call("resolve_file", {"reference": "report.pdf"}), AgentStepResult(text=CLAIM)],
        files=files,
    )
    assert state["final_answer"] == expected and state["failure"] is None
    assert not state["citations"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,expected",
    [
        ("LIST", "Indexed files: 1. Showing 1.\n- report.pdf"),
        ("COUNT", "Indexed files: 1."),
        ("LATEST", "Latest indexed file: report.pdf"),
        ("OLDEST", "Oldest indexed file: report.pdf"),
    ],
)
async def test_inventory_metadata_cannot_smuggle_document_claim(operation, expected):
    state, _, _ = await run(
        [call("files_query", inventory(operation)), AgentStepResult(text=CLAIM)]
    )
    assert state["final_answer"] == expected
    assert not state["citations"]


@pytest.mark.asyncio
async def test_failed_tool_never_authorizes_model_prose():
    state, _, _ = await run([call("unknown", {}), AgentStepResult(text=CLAIM)])
    assert state["final_answer"] == "Tool arguments are invalid. Which filename do you mean?"
    assert not state["citations"]


@pytest.mark.asyncio
async def test_empty_read_has_explicit_nonabsence_outcome():
    from typing import cast
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.agents.tool_rag.agent_service import ToolRagAgentService
    from tests.agents.tool_rag.test_tool_execution import InventoryDB

    retriever = AsyncMock()
    retriever.retrieve.return_value = []
    state = await ToolRagAgentService(
        ScriptChat([call("search_knowledge", SEARCH), AgentStepResult(text=CLAIM)])
    ).run("Summarize", user_id=USER, db=cast(AsyncSession, InventoryDB()), retriever=retriever)
    assert state["final_answer"] == EMPTY_CONTENT and not state["citations"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "marker", ["[source_999]", "[evidence_999]", "[source_0]", "[source_fake]", "[99]"]
)
async def test_invented_citation_is_rejected_even_with_real_evidence(marker):
    state, _, _ = await run(
        [call("search_knowledge", SEARCH), AgentStepResult(text=CLAIM + marker)]
    )
    assert state["failure"] == "UNSAFE_FINAL_OUTPUT"
    assert not state["citations"] and CLAIM not in state["final_answer"]


@pytest.mark.asyncio
async def test_content_evidence_and_real_handle_allow_grounded_answer():
    state, _, _ = await run(
        [call("search_knowledge", SEARCH), AgentStepResult(text="Approval is required. [source_1]")]
    )
    assert state["final_answer"] == "Approval is required. [1]"
    assert len(state["citations"]) == 1 and state["retrieval_count"] == 1
    assert state["failure"] is None


@pytest.mark.asyncio
async def test_tool_free_clarification_does_not_require_content():
    state, _, _ = await run(
        [AgentStepResult(text="Which file do you mean?")], question="Summarize that file"
    )
    assert state["failure"] is None and state["final_answer"] == NO_CONTENT
    assert "Which file" in state["final_answer"] and not state["citations"]


@pytest.mark.asyncio
async def test_untrusted_metadata_is_displayed_without_links_or_citations():
    state, _, _ = await run(
        [call("files_query", inventory()), AgentStepResult(text=CLAIM)],
        files=[file(name="[click](https://example.invalid)\n[source_1]")],
    )
    assert state["final_answer"] == (
        "Indexed files: 1. Showing 1.\n- \\[click\\]\\(https://example.invalid\\) \\[source\\_1\\]"
    )
    assert not state["citations"] and CLAIM not in state["final_answer"]
