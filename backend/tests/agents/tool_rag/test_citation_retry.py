"""KI-026: a citation marker that does not exist gets one corrective turn, not an error.

The model sometimes writes [source_2] when only source_1 exists. Rejecting the answer is right (an invented
marker is never repaired by deleting it or adding real ones), but ending the run with ChatError was not. The
model is now told which markers are valid and may rewrite once; the rewrite passes the same checks.
"""

from __future__ import annotations

import pytest

from app.agents.tool_rag.agent_models import AgentStepResult
from tests.agents.tool_rag.test_agent_loop import call, run

SEARCH = {"query": "late fee", "scope": {"kind": "ALL_ELIGIBLE_INDEXED_FILES"}}
GOOD = "The fee is 1.5% per month. [source_1]"


@pytest.mark.asyncio
async def test_one_bad_marker_is_corrected_and_the_run_succeeds():
    state, chat, _ = await run(
        [
            call("search_knowledge", SEARCH),
            AgentStepResult(text="The fee is 1.5% per month. [source_2]"),
            AgentStepResult(text=GOOD),
        ]
    )
    assert state["failure"] is None
    assert state["final_answer"] == "The fee is 1.5% per month. [1]"
    assert len(state["citations"]) == 1
    # the model saw its own bad answer, then a server note naming the markers that do exist
    last = chat.received[-1]
    assert last[-2].role == "ASSISTANT" and "[source_2]" in (last[-2].text or "")
    assert last[-1].role == "USER" and "[source_1]" in (last[-1].text or "")
    assert "does not exist" in (last[-1].text or "")


@pytest.mark.asyncio
async def test_a_bad_numeric_marker_is_corrected_too():
    state, _, _ = await run(
        [
            call("search_knowledge", SEARCH),
            AgentStepResult(text="The fee is 1.5% per month. [7]"),
            AgentStepResult(text=GOOD),
        ]
    )
    assert state["failure"] is None and state["final_answer"] == "The fee is 1.5% per month. [1]"


@pytest.mark.asyncio
async def test_only_one_correction_is_allowed():
    state, chat, _ = await run(
        [
            call("search_knowledge", SEARCH),
            AgentStepResult(text="Fee. [source_2]"),
            AgentStepResult(text="Fee. [source_3]"),
        ]
    )
    assert state["failure"] == "UNSAFE_FINAL_OUTPUT"
    assert not state["citations"] and "source_3" not in (state["final_answer"] or "")
    assert len(chat.received) == 3  # tool call, first answer, one retry: no third attempt


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "leak", ["See file_1 for details.", "Handle 123e4567-e89b-12d3-a456-426614174000."]
)
async def test_leaking_a_handle_or_id_is_never_retried(leak):
    state, chat, _ = await run(
        [call("search_knowledge", SEARCH), AgentStepResult(text=leak + " [source_1]")]
    )
    assert state["failure"] == "UNSAFE_FINAL_OUTPUT"
    assert len(chat.received) == 2  # no corrective turn for an unsafe output


@pytest.mark.asyncio
async def test_a_correct_first_answer_is_untouched():
    state, chat, _ = await run([call("search_knowledge", SEARCH), AgentStepResult(text=GOOD)])
    assert state["final_answer"] == "The fee is 1.5% per month. [1]"
    assert len(chat.received) == 2


@pytest.mark.asyncio
async def test_the_note_lists_source_handles_never_bare_numbers():
    """The model only knows source_N handles; "[1]" is what the user sees, so it must not be offered."""
    _, chat, _ = await run(
        [
            call("search_knowledge", SEARCH),
            AgentStepResult(text="The fee is 1.5% per month. [7]"),
            AgentStepResult(text=GOOD),
        ]
    )
    note = chat.received[-1][-1].text or ""
    assert "[source_1]" in note and "[1]" not in note and "evidence_" not in note


@pytest.mark.asyncio
async def test_no_retry_when_the_cycle_limit_leaves_no_model_call_for_it():
    state, chat, _ = await run(
        [call("search_knowledge", SEARCH), AgentStepResult(text="Fee. [source_9]")], max_cycles=2
    )
    # a plain refusal of the unsafe output, not the misleading "cycle limit" message
    assert state["failure"] == "UNSAFE_FINAL_OUTPUT"
    assert len(chat.received) == 2
