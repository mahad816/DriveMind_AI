"""KI-034: the once-only corrective turn after a first agent step that used no tool.

Scripted model only: no network, no database, no key. Every test that scripts the model consumes exactly its
scripted replies (``assert_consumed``): a missing reply would otherwise end as a provider error that can look
like an ordinary failure reply.

What these tests show is the mechanism (when the note is sent, what is sent, what the run does next). They do not
show that a real model searches after the note; that needs a measured run and stays open (KI-034).
"""

import json
import re
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tool_rag.agent_models import AgentMessage, AgentStepResult
from app.agents.tool_rag.agent_service import ToolRagAgentService
from app.agents.tool_rag.finalization import EMPTY_CONTENT, FILE_NOT_FOUND_TEXT, NO_CONTENT
from app.agents.tool_rag.graph import CYCLE_LIMIT_MESSAGE, SEARCH_NUDGE_NOTE
from app.core.config import Settings
from app.llm.openai_agent_service import OpenAIAgentChatService, native_messages
from app.services.chat_stream import stream_sink
from app.services.tool_agent_service import ToolAgentAdapter
from tests.agents.tool_rag.test_agent_loop import (
    RecordingExecutor,
    ScriptChat,
    assert_consumed,
    call,
    inventory,
    run,
)
from tests.agents.tool_rag.test_grounding_policy import SEARCH
from tests.agents.tool_rag.test_tool_execution import USER, InventoryDB, chunk, file
from tests.test_chat_streaming import ProviderStream, tool_stream


def settings(**overrides: Any) -> Settings:
    return cast(Any, Settings)(_env_file=None, **overrides)


QUESTION = "How many days of annual leave do employees get?"
SKIPPED = AgentStepResult(text="Employees get a number of days.")  # prose, no tool call
CITED = AgentStepResult(text="Approval is required. [source_1]")


def note_count(chat) -> int:
    """How many times the corrective note appears in the LAST request sent to the model."""
    return sum(1 for m in chat.received[-1] if m.role == "USER" and m.text == SEARCH_NUDGE_NOTE)


def note_ever_sent(chat) -> bool:
    return any(m.text == SEARCH_NUDGE_NOTE for turn in chat.received for m in turn)


# --- provider-protocol invariants (on the real wire shape, not on a mock call) -------------------------------


def check_wire_sequence(messages) -> None:
    """Chat-completions ordering: every tool message answers an earlier assistant tool call, and every tool call is
    answered before any other message follows it."""
    open_ids: set[str] = set()
    seen_ids: set[str] = set()
    for raw in native_messages(messages):
        item = cast(dict[str, Any], raw)
        role = item["role"]
        if open_ids:
            assert role == "tool", f"a {role} message follows an unanswered tool call"
        if role == "assistant" and item.get("tool_calls"):
            ids = {t["id"] for t in item["tool_calls"]}
            assert not ids & seen_ids, "a tool call id was reused"
            open_ids |= ids
            seen_ids |= ids
        elif role == "tool":
            assert item["tool_call_id"] in open_ids, "orphan tool message"
            open_ids.discard(item["tool_call_id"])
    assert not open_ids, "the request ends with an unanswered tool call"


def test_the_wire_check_itself_rejects_orphans_and_unanswered_calls():
    orphan = (
        AgentMessage(role="SYSTEM", text="s"),
        AgentMessage(role="USER", text="q"),
        AgentMessage(role="TOOL", call_id="call_x", text="{}"),
    )
    with pytest.raises(AssertionError, match="orphan"):
        check_wire_sequence(orphan)
    dangling = (
        AgentMessage(role="USER", text="q"),
        call("search_knowledge", SEARCH, "call_y"),
    )
    assert dangling[1].tool_calls
    with pytest.raises(AssertionError, match="unanswered"):
        check_wire_sequence(
            (
                dangling[0],
                AgentMessage(role="ASSISTANT", text=None, tool_calls=dangling[1].tool_calls),
            )
        )


# --- the mechanism ----------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skipped_first_tool_gets_one_note_then_a_search_then_a_cited_answer():
    state, chat, retriever = await run([SKIPPED, call("search_knowledge", SEARCH), CITED], QUESTION)
    assert_consumed(chat)
    assert len(chat.received) == 3
    assert state["final_answer"] == "Approval is required. [1]" and state["failure"] is None
    assert len(state["citations"]) == 1 and state["retrieval_count"] == 1
    retriever.retrieve.assert_awaited_once()
    assert state["search_nudged"] is True
    # the note is the last message of the second request, sent once, after the model's own skipped text
    second = chat.received[1]
    assert second[-1].role == "USER" and second[-1].text == SEARCH_NUDGE_NOTE
    assert second[-2].role == "ASSISTANT" and second[-2].text == SKIPPED.text
    assert note_count(chat) == 1  # still exactly one in the last request: never repeated
    for turn in chat.received:
        check_wire_sequence(turn)


@pytest.mark.asyncio
async def test_the_note_is_fixed_server_text_with_no_user_text_and_no_handle():
    _, chat, _ = await run([SKIPPED, call("search_knowledge", SEARCH), CITED], QUESTION)
    assert_consumed(chat)
    assert QUESTION not in SEARCH_NUDGE_NOTE and "annual leave" not in SEARCH_NUDGE_NOTE
    assert not re.search(r"(?<!\w)(?:file|source|evidence)_[1-9]", SEARCH_NUDGE_NOTE)
    assert "search_knowledge" in SEARCH_NUDGE_NOTE


@pytest.mark.asyncio
async def test_wire_shape_is_valid_on_the_adapter_path_too():
    """The adapter adds a history-window system note, so the exact shape differs; the invariants must not."""
    chat = ScriptChat([SKIPPED, call("search_knowledge", SEARCH), CITED])
    retriever = AsyncMock()
    retriever.retrieve.return_value = [chunk()]
    adapter = ToolAgentAdapter(
        cast(AsyncSession, InventoryDB([file()])),
        settings(),
        chat=chat,
        retriever=retriever,
    )
    result = await adapter.answer(QUESTION, user_id=USER, history=[], history_window_complete=True)
    assert_consumed(chat)
    assert result.answer == "Approval is required. [1]" and result.retrieval_count == 1
    assert [m.role for m in chat.received[1]][-2:] == ["ASSISTANT", "USER"]
    assert all(
        m.role != "TOOL" for m in chat.received[1]
    )  # no tool message exists before the model made a call
    for turn in chat.received:
        check_wire_sequence(turn)


@pytest.mark.asyncio
async def test_a_model_that_ignores_the_note_ends_with_the_fixed_reply_and_is_not_nudged_twice():
    state, chat, retriever = await run([SKIPPED, SKIPPED], QUESTION)
    assert_consumed(chat)
    assert len(chat.received) == 2 and note_count(chat) == 1
    assert state["final_answer"] == NO_CONTENT and state["failure"] is None
    retriever.retrieve.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_clarifying_reply_to_the_note_is_still_safe_and_uncited():
    ask_back = AgentStepResult(text="Which file do you mean?")
    state, chat, _ = await run([SKIPPED, ask_back], "Summarize that file")
    assert_consumed(chat)
    assert state["final_answer"] == NO_CONTENT and "Which file" in state["final_answer"]
    assert not state["citations"] and state["failure"] is None


@pytest.mark.asyncio
async def test_empty_retrieval_after_the_note_gives_the_not_enough_evidence_reply():
    retriever_empty = AsyncMock()
    retriever_empty.retrieve.return_value = []
    chat = ScriptChat(
        [SKIPPED, call("search_knowledge", SEARCH), AgentStepResult(text="Nothing found.")]
    )
    state = await ToolRagAgentService(chat).run(
        QUESTION,
        user_id=USER,
        db=cast(AsyncSession, InventoryDB([file()])),
        retriever=retriever_empty,
    )
    assert_consumed(chat)
    assert state["final_answer"] == EMPTY_CONTENT and state["failure"] is None
    assert not state["citations"]
    assert len(chat.received) == 3 and note_count(chat) == 1  # no second note, no loop


# --- when the note must NOT be sent ----------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("question,reply", [("Hi", "Hello!"), ("Thanks!", "You're welcome!")])
async def test_social_phrases_get_their_fixed_reply_and_no_note(question, reply):
    state, chat, _ = await run([AgentStepResult(text="Hi there!")], question)
    assert_consumed(chat)
    assert state["final_answer"] == reply and not note_ever_sent(chat)


@pytest.mark.asyncio
async def test_a_question_with_history_gets_no_note():
    chat = ScriptChat([AgentStepResult(text="Which one do you mean?")])
    state = await ToolRagAgentService(chat).run(
        "the second one",
        user_id=USER,
        db=cast(AsyncSession, InventoryDB([file()])),
        retriever=AsyncMock(),
        history=(
            AgentMessage(role="USER", text="Which files are there?"),
            AgentMessage(role="ASSISTANT", text="Two files."),
        ),
    )
    assert_consumed(chat)
    assert state["final_answer"] == NO_CONTENT and not note_ever_sent(chat)


@pytest.mark.asyncio
@pytest.mark.parametrize("max_cycles", [1, 2])
async def test_too_little_cycle_budget_gets_no_note(max_cycles):
    state, chat, _ = await run([SKIPPED], QUESTION, max_cycles=max_cycles)
    assert_consumed(chat)
    assert state["final_answer"] == NO_CONTENT and state["failure"] is None
    assert not note_ever_sent(chat)


@pytest.mark.asyncio
async def test_exactly_three_cycles_is_enough_for_note_search_and_answer():
    state, chat, retriever = await run(
        [SKIPPED, call("search_knowledge", SEARCH), CITED], QUESTION, max_cycles=3
    )
    assert_consumed(chat)
    assert state["failure"] is None and state["final_answer"] == "Approval is required. [1]"
    assert state["cycle_count"] == 3
    retriever.retrieve.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "first,files",
    [
        (call("resolve_file", {"reference": "report.pdf"}), None),  # found, then prose
        (
            call(
                "files_query",
                {"operation": "COUNT", "scope": {"kind": "ALL_ELIGIBLE_INDEXED_FILES"}},
            ),
            None,
        ),
        (call("unknown", {}), None),  # a failed tool call
        (call("search_knowledge", SEARCH), None),  # evidence retrieved
    ],
)
async def test_an_earlier_tool_call_means_no_note(first, files):
    _, chat, _ = await run([first, AgentStepResult(text="Some prose.")], QUESTION, files=files)
    assert_consumed(chat)
    assert len(chat.received) == 2 and not note_ever_sent(chat)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reference,files,expected",
    [
        ("budget_2027.txt", [], FILE_NOT_FOUND_TEXT),  # file-shaped name that does not exist
        (
            "report.pdf",
            [file(), file(11)],
            "Please disambiguate the filename",
        ),  # two files, one name
    ],
)
async def test_named_file_not_found_and_ambiguous_replies_are_unchanged(reference, files, expected):
    state, chat, retriever = await run(
        [call("resolve_file", {"reference": reference}), AgentStepResult(text="It is 5.")],
        f"What does {reference} say?",
        files=files,
    )
    assert_consumed(chat)
    assert not note_ever_sent(chat)
    retriever.retrieve.assert_not_awaited()
    assert state["final_answer"] is not None and state["final_answer"].startswith(expected)


@pytest.mark.asyncio
async def test_out_of_scope_and_conversational_intents_never_reach_the_agent():
    async def gate(system, user):
        return json.dumps({"intent": "out_of_scope"})

    chat = ScriptChat([])
    adapter = ToolAgentAdapter(
        cast(AsyncSession, AsyncMock()), settings(), chat=chat, intent_complete=gate
    )
    result = await adapter.answer(
        "Write me a poem", user_id=USER, history=[], history_window_complete=True
    )
    assert "can only answer using the documents" in result.answer
    assert chat.received == [] and chat.steps == [] and not chat.exhausted


@pytest.mark.asyncio
async def test_demo_mode_behaves_like_normal_mode():
    """Demo mode skips the intent gate but not the agent, so a skipped first tool gets the same single note."""
    chat = ScriptChat([SKIPPED, call("search_knowledge", SEARCH), CITED])
    retriever = AsyncMock()
    retriever.retrieve.return_value = [chunk()]
    adapter = ToolAgentAdapter(
        cast(AsyncSession, InventoryDB([file()])),
        settings(demo_mode=True),
        chat=chat,
        retriever=retriever,
    )
    result = await adapter.answer(QUESTION, user_id=USER, history=[], history_window_complete=True)
    assert_consumed(chat)
    assert result.answer == "Approval is required. [1]" and note_count(chat) == 1


@pytest.mark.asyncio
async def test_demo_mode_social_phrase_still_gets_no_note():
    chat = ScriptChat([AgentStepResult(text="Hello!")])
    adapter = ToolAgentAdapter(
        cast(AsyncSession, InventoryDB([file()])),
        settings(demo_mode=True),
        chat=chat,
    )
    result = await adapter.answer("hi", user_id=USER, history=[], history_window_complete=True)
    assert_consumed(chat)
    assert result.answer == "Hello!" and not note_ever_sent(chat)


# --- interaction with the citation retry and the claim check -------------------------------------------------


@pytest.mark.asyncio
async def test_the_note_comes_first_and_the_citation_retry_stays_available_once():
    bad = AgentStepResult(text="Approval is required. [source_9]")
    state, chat, _ = await run(
        [bad, call("search_knowledge", SEARCH), bad, CITED], QUESTION
    )  # the bad marker on the discarded first step does not spend the retry
    assert_consumed(chat)
    assert len(chat.received) == 4
    assert state["search_nudged"] is True and state["citation_retried"] is True
    assert state["final_answer"] == "Approval is required. [1]" and state["failure"] is None
    for turn in chat.received:
        check_wire_sequence(turn)


@pytest.mark.asyncio
async def test_with_exactly_three_cycles_a_bad_marker_after_the_search_has_no_retry_left():
    bad = AgentStepResult(text="Approval is required. [source_9]")
    state, chat, _ = await run(
        [SKIPPED, call("search_knowledge", SEARCH), bad], QUESTION, max_cycles=3
    )
    assert_consumed(chat)
    assert state["failure"] == "UNSAFE_FINAL_OUTPUT" and not state["citations"]


@pytest.mark.asyncio
async def test_the_claim_check_may_see_the_note_as_a_user_message_and_still_runs_on_evidence():
    seen = {}

    async def checker(answer, evidence, question=""):
        seen["question"] = question
        return None  # unusable check: the answer stays as it was

    retriever = AsyncMock()
    retriever.retrieve.return_value = [chunk()]
    chat = ScriptChat([SKIPPED, call("search_knowledge", SEARCH), CITED])
    state = await ToolRagAgentService(chat, claim_check=cast(Any, checker)).run(
        QUESTION,
        user_id=USER,
        db=cast(AsyncSession, InventoryDB([file()])),
        retriever=retriever,
    )
    assert_consumed(chat)
    assert state["final_answer"] == "Approval is required. [1]"
    assert (
        QUESTION in seen["question"] and SEARCH_NUDGE_NOTE in seen["question"]
    )  # documented, as for the KI-026 note


# --- authorization boundary at the unit level (container test: tests/security) ------------------------------------


@pytest.mark.asyncio
async def test_the_post_note_search_runs_for_the_caller_through_the_unchanged_executor():
    executor = RecordingExecutor()
    _, chat, retriever = await run(
        [SKIPPED, call("search_knowledge", SEARCH), CITED], QUESTION, executor=executor
    )
    assert_consumed(chat)
    assert executor.calls == ["search_knowledge"]
    assert {c.user_id for c in executor.contexts} == {USER}
    request = retriever.retrieve.await_args.args[0]
    assert request.user_id == USER


# --- streaming: the skipped step's prose is never shown --------------------------------------------------------


@pytest.mark.asyncio
async def test_streaming_never_shows_the_skipped_steps_prose():
    streams = [
        ProviderStream(
            [({"content": "Skipped fabricated claim "}, "stop")]
        ),  # first step: prose, no tool
        tool_stream(),  # after the note: the search
        ProviderStream(
            [({"content": "Approval is required. "}, None), ({"content": "[source_1]"}, "stop")]
        ),
    ]
    create = AsyncMock(side_effect=streams)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    client.with_options = Mock(return_value=client)
    chat = OpenAIAgentChatService(settings(), client=cast(Any, client))
    retriever = AsyncMock()
    retriever.retrieve.return_value = [chunk()]
    events: list = []

    async def sink(name, data):
        events.append((name, data))

    token = stream_sink.set(sink)
    try:
        result = await ToolRagAgentService(chat).run(
            "Refund policy?",
            user_id=USER,
            db=cast(AsyncSession, InventoryDB([file()])),
            retriever=retriever,
        )
    finally:
        stream_sink.reset(token)
    assert create.await_count == 3 and all(s.closed for s in streams)
    assert result["failure"] is None and result["final_answer"] == "Approval is required. [1]"
    assert "fabricated" not in json.dumps(events)
    assert not any(name == "provisional" and "Skipped" in data["text"] for name, data in events)


# --- review follow-up: loop bounds and failure modes after the corrective turn ---------------------------------


def chained(n: int) -> list[AgentStepResult]:
    """n tool-call steps that retrieve no evidence (a file inventory), each with its own call id."""
    return [call("files_query", inventory(), f"call_chain_{i}") for i in range(n)]


@pytest.mark.asyncio
@pytest.mark.parametrize("max_cycles,tool_steps", [(3, 2), (6, 5)])
async def test_a_model_that_chains_tools_after_the_note_ends_at_the_cycle_limit_with_one_note(
    max_cycles, tool_steps
):
    """The skipped first step has already used one cycle. A model that then keeps calling tools reaches the normal
    cycle limit: the note is still sent exactly once, no step is added beyond max_cycles, and the loop cannot run on."""
    state, chat, retriever = await run(
        [SKIPPED, *chained(tool_steps)], QUESTION, max_cycles=max_cycles
    )
    assert_consumed(chat)  # 1 skipped step + tool_steps steps, nothing left over, nothing missing
    assert len(chat.received) == 1 + tool_steps == max_cycles
    assert state["failure"] == "CYCLE_LIMIT" and state["final_answer"] == CYCLE_LIMIT_MESSAGE
    assert state["cycle_count"] == max_cycles
    assert (
        sum(note_in(turn) for turn in chat.received) == max_cycles - 1
    )  # present in every later request...
    assert (
        note_total(chat) == 1
    )  # ...but it is ONE message that was added once, never a second copy
    retriever.retrieve.assert_not_awaited()
    for turn in chat.received:
        check_wire_sequence(turn)


@pytest.mark.asyncio
async def test_a_second_search_after_the_note_is_allowed_and_the_note_is_not_repeated():
    state, chat, retriever = await run(
        [
            SKIPPED,
            call("search_knowledge", SEARCH, "call_s1"),
            call("search_knowledge", SEARCH, "call_s2"),
            CITED,
        ],
        QUESTION,
    )
    assert_consumed(chat)
    assert len(chat.received) == 4 and note_total(chat) == 1
    assert state["failure"] is None and state["final_answer"] == "Approval is required. [1]"
    assert retriever.retrieve.await_count == 2
    for turn in chat.received:
        check_wire_sequence(turn)


@pytest.mark.asyncio
async def test_two_bad_markers_after_the_note_and_a_search_end_in_the_existing_unsafe_output_failure():
    """Not a regression of the nudge: the same two bad markers after a search that the model made on its own end the
    same way (KI-026 allows one correction). The failure is the safe one, with no citations and no prose."""
    bad = AgentStepResult(text="Approval is required. [source_9]")
    state, chat, _ = await run([SKIPPED, call("search_knowledge", SEARCH), bad, bad], QUESTION)
    assert_consumed(chat)
    assert len(chat.received) == 4 and note_total(chat) == 1
    assert state["failure"] == "UNSAFE_FINAL_OUTPUT" and not state["citations"]
    assert "source_9" not in (state["final_answer"] or "")
    own, own_chat, _ = await run(
        [call("search_knowledge", SEARCH), bad, bad], QUESTION
    )  # the same model behaviour without any note
    assert_consumed(own_chat)
    assert own["failure"] == state["failure"] and own["final_answer"] == state["final_answer"]


def note_in(turn) -> int:
    return sum(1 for m in turn if m.role == "USER" and m.text == SEARCH_NUDGE_NOTE)


def note_total(chat) -> int:
    """The most copies of the note that any single request carried: more than 1 would mean it was added twice."""
    return max(note_in(turn) for turn in chat.received)
