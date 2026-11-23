"""KI-034 (open, mechanism implemented): a document question whose first agent step calls no tool.

Scripted model, no network, no database, no key. The first step answers in prose without any tool call. Before the
corrective turn existed the run ended there: the prose is never shown (no evidence), the user got ``NO_CONTENT``,
and the retriever was never called, although a model that is asked again may search. The test states the behaviour
a user would call correct: a model that skips the tool once but searches when the run gives it one more chance
still ends with a cited answer.

The corrective turn is implemented (``docs/tickets/agent-first-step-fallback/01-no-tool-search-fallback.md``), so
the strict expected-failure marker was removed and this is now an ordinary test. That shows the MECHANISM only. The
script supplies the model's search; whether a real model searches after the note is unmeasured, so KI-034 stays
open in ``docs/KNOWN_ISSUES.md`` until a measured run on a frozen set. The guards below pin behaviour next to the
mechanism (a greeting, a follow-up that has history, and a run with too little cycle budget get no extra turn).

Real-model evidence (first step only, not answers): ``docs/EVALUATION_RESULTS.md``, section M1-08-G. The model's
own text for those turns was not stored, so why it skipped the tool is a hypothesis.
"""

from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tool_rag.agent_models import AgentMessage, AgentStepResult
from app.agents.tool_rag.agent_service import ToolRagAgentService
from app.agents.tool_rag.finalization import NO_CONTENT
from tests.agents.tool_rag.test_agent_loop import ScriptChat, assert_consumed, call, run
from tests.agents.tool_rag.test_grounding_policy import SEARCH
from tests.agents.tool_rag.test_tool_execution import USER, InventoryDB, chunk, file

QUESTION = "How many days of annual leave do employees get?"


@pytest.mark.asyncio
async def test_skipped_first_tool_still_ends_with_a_cited_answer():
    steps = [
        AgentStepResult(text="Employees get a number of days."),  # no tool call: the defect
        call("search_knowledge", SEARCH),  # what the model does when given one more chance
        AgentStepResult(text="Approval is required. [source_1]"),
    ]
    state, chat, retriever = await run(steps, question=QUESTION)
    assert_consumed(chat)  # exactly the three scripted replies were used
    assert retriever.retrieve.await_count == 1
    assert state["final_answer"] == "Approval is required. [1]"
    assert state["failure"] is None


# --- guards: behaviour next to the defect that the fix must not change (they pass before and after the mechanism) ---------------


@pytest.mark.asyncio
async def test_guard_greeting_keeps_its_fixed_reply_without_an_extra_turn():
    state, chat, retriever = await run([AgentStepResult(text="Hi there!")], question="Hi")
    assert_consumed(chat)
    assert state["final_answer"] == "Hello!"
    assert len(chat.received) == 1
    retriever.retrieve.assert_not_awaited()


@pytest.mark.asyncio
async def test_guard_follow_up_with_history_keeps_the_fixed_reply_without_an_extra_turn():
    chat = ScriptChat([AgentStepResult(text="Which one do you mean?")])
    retriever = AsyncMock()
    retriever.retrieve.return_value = [chunk()]
    state = await ToolRagAgentService(chat).run(
        "the second one",
        user_id=USER,
        db=cast(AsyncSession, InventoryDB([file()])),
        retriever=retriever,
        history=(
            AgentMessage(role="USER", text="Which files are there?"),
            AgentMessage(role="ASSISTANT", text="Two files."),
        ),
    )
    assert_consumed(chat)
    assert state["final_answer"] == NO_CONTENT
    assert len(chat.received) == 1
    retriever.retrieve.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("max_cycles", [1, 2])
async def test_guard_too_little_cycle_budget_keeps_the_fixed_reply(max_cycles):
    state, chat, retriever = await run(
        [AgentStepResult(text="Employees get a number of days.")],
        question=QUESTION,
        max_cycles=max_cycles,
    )
    assert_consumed(chat)
    assert state["final_answer"] == NO_CONTENT and state["failure"] is None
    assert len(chat.received) == 1
    retriever.retrieve.assert_not_awaited()
