"""KI-025: a failed file-name lookup must not end the run when the reference was not a file name.

``resolve_file`` matches exact file names only. A model that passes "invoice INV-0457" to it always gets
NOT_FOUND. That used to be final for the whole run (the provenance guard blocks prose after any failed
lookup), so a question the documents can answer got "No eligible indexed file matches that name".

Rule under test: a NOT_FOUND for a reference that does *not* end in a file extension is "soft": a later
successful content read in the same run clears it. A reference that looks like a file name
("budget_2027.txt") stays final, so a missing file is never answered from other documents.
"""

from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tool_rag.agent_models import AgentStepResult
from app.agents.tool_rag.agent_service import ToolRagAgentService
from app.agents.tool_rag.finalization import EMPTY_CONTENT, FILE_NOT_FOUND_TEXT, names_a_file
from tests.agents.tool_rag.test_agent_loop import ScriptChat, call, run
from tests.agents.tool_rag.test_tool_execution import USER, InventoryDB, file

SEARCH = {"query": "INV-0457 total due", "scope": {"kind": "ALL_ELIGIBLE_INDEXED_FILES"}}
QUESTION = "What is the total due on invoice INV-0457?"


@pytest.mark.parametrize(
    "reference,expected",
    [
        ("budget_2026.txt", True),
        ("Invoice_0457.PDF", True),
        ("notes.md", True),
        ("sales 2026.xlsx", True),
        ("  report.pdf  ", True),
        ("INV-0457", False),
        ("invoice INV-0457", False),
        ("the Q3 board deck", False),
        ("release 1.3.2", False),  # ".2" is a version, not an extension
        ("v1.3", False),
        ("Q3.", False),
        ("", False),
    ],
)
def test_names_a_file_means_the_reference_ends_in_a_file_extension(reference, expected):
    assert names_a_file(reference) is expected


@pytest.mark.asyncio
async def test_a_search_after_a_failed_lookup_of_a_non_file_name_gives_a_grounded_answer():
    state, chat, _ = await run(
        [
            call("resolve_file", {"reference": "invoice INV-0457"}),
            call("search_knowledge", SEARCH, "call_2"),
            AgentStepResult(text="The total is due. [source_1]"),
        ],
        question=QUESTION,
    )
    assert state["final_answer"] == "The total is due. [1]"
    assert len(state["citations"]) == 1 and state["failure"] is None
    # the model was told the lookup is by exact file name and where content questions go
    first_result = chat.received[1][-1].text
    assert "NOT_FOUND" in first_result and "search_knowledge" in first_result


@pytest.mark.asyncio
async def test_a_failed_lookup_of_a_file_name_stays_final_even_if_the_model_searches_on():
    state, _, _ = await run(
        [
            call("resolve_file", {"reference": "invoice_0457.pdf"}),
            call("search_knowledge", SEARCH, "call_2"),
            AgentStepResult(text="The total is due. [source_1]"),
        ],
        question="What is the total due in invoice_0457.pdf?",
    )
    assert state["final_answer"] == FILE_NOT_FOUND_TEXT
    assert not state["citations"]


@pytest.mark.asyncio
async def test_evidence_read_before_the_failed_lookup_does_not_clear_it():
    state, _, _ = await run(
        [
            call("search_knowledge", SEARCH),
            call("resolve_file", {"reference": "INV-0457"}, "call_2"),
            AgentStepResult(text="The total is due. [source_1]"),
        ],
        question=QUESTION,
    )
    assert state["final_answer"] == FILE_NOT_FOUND_TEXT and not state["citations"]


@pytest.mark.asyncio
async def test_a_failed_non_file_lookup_with_no_search_after_it_gets_the_lookup_message():
    state, _, _ = await run(
        [call("resolve_file", {"reference": "INV-0457"}), AgentStepResult(text="It is 6,543.60.")],
        question=QUESTION,
    )
    assert state["final_answer"] == FILE_NOT_FOUND_TEXT and not state["citations"]


@pytest.mark.asyncio
async def test_an_empty_search_after_a_failed_non_file_lookup_says_the_index_had_nothing():
    retriever = AsyncMock()
    retriever.retrieve.return_value = []
    state = await ToolRagAgentService(
        ScriptChat(
            [
                call("resolve_file", {"reference": "INV-0457"}),
                call("search_knowledge", SEARCH, "call_2"),
                AgentStepResult(text="It is 6,543.60."),
            ]
        )
    ).run(QUESTION, user_id=USER, db=cast(AsyncSession, InventoryDB([file()])), retriever=retriever)
    assert state["final_answer"] == EMPTY_CONTENT and not state["citations"]


@pytest.mark.asyncio
async def test_a_resolved_file_still_needs_its_own_read():
    """Unchanged rule: resolving a real file is not content, and another file's text does not stand in."""
    state, _, _ = await run(
        [
            call("resolve_file", {"reference": "INV-0457"}),
            call("resolve_file", {"reference": "report.pdf"}, "call_2"),
            call("search_knowledge", SEARCH, "call_3"),
            AgentStepResult(text="Text. [source_1]"),
        ],
        question=QUESTION,
    )
    # the search reads report.pdf's chunk, which satisfies the resolved file and clears the soft failure
    assert state["failure"] is None and state["final_answer"] == "Text. [1]"
