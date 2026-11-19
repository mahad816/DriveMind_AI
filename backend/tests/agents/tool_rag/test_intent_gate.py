"""Intent gate: meaning-based, fail-safe, and unable to produce document claims."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from app.agents.tool_rag import conversation
from app.agents.tool_rag.agent_models import AgentStepResult
from app.agents.tool_rag.conversation import (
    CONVERSATIONAL,
    INTENTS,
    MAX_CLASSIFIED_CHARS,
    REPLIES,
    classify_intent,
)
from app.agents.tool_rag.finalization import NO_CONTENT
from app.core.config import Settings
from app.services.tool_agent_service import ToolAgentAdapter
from tests.agents.tool_rag.test_agent_loop import ScriptChat, run
from tests.agents.tool_rag.test_tool_execution import USER

CLAIM = "The document describes experience in AI."


def declares(intent: str, **extra):
    """A stand-in for the model call: returns the JSON the real classifier would."""
    calls = []

    async def complete(system: str, user: str) -> str:
        calls.append((system, user))
        return json.dumps({"intent": intent, **extra})

    complete.calls = calls  # type: ignore[attr-defined]
    return complete


def failing(error: Exception):
    async def complete(system: str, user: str) -> str:
        raise error

    return complete


def raw(text: str):
    async def complete(system: str, user: str) -> str:
        return text

    return complete


# --- classify_intent -------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("intent", sorted(INTENTS))
async def test_every_declared_intent_is_returned(intent):
    assert await classify_intent(declares(intent), "anything") == intent


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "complete",
    [
        raw("not json"),
        raw(""),
        raw("[]"),
        raw('"greeting"'),
        raw("null"),
        raw('{"intent": 7}'),
        raw('{"intent": "Greeting"}'),  # Exact enum only: no guessing.
        raw('{"intent": "hello"}'),
        raw('{"other": "greeting"}'),
        failing(RuntimeError("provider down")),
        failing(TimeoutError()),
    ],
)
async def test_anything_uncertain_falls_back_to_document_question(complete):
    assert await classify_intent(complete, "Hello there") == "document_question"


@pytest.mark.asyncio
async def test_slow_classifier_times_out_to_document_question(monkeypatch):
    monkeypatch.setattr(conversation, "CLASSIFY_TIMEOUT_SECONDS", 0.01)

    async def slow(system: str, user: str) -> str:
        await asyncio.sleep(1)
        return '{"intent": "greeting"}'

    assert await classify_intent(slow, "hi") == "document_question"


@pytest.mark.asyncio
@pytest.mark.parametrize("question", ["", "   ", "x" * (MAX_CLASSIFIED_CHARS + 1)])
async def test_empty_or_long_messages_skip_the_call(question):
    complete = declares("greeting")
    assert await classify_intent(complete, question) == "document_question"
    assert complete.calls == []


@pytest.mark.asyncio
async def test_classifier_receives_only_the_trimmed_message():
    complete = declares("greeting")
    await classify_intent(complete, "  Hello, can you hear me?  ")
    system, user = complete.calls[0]
    assert user == "Hello, can you hear me?"
    assert system == conversation.INTENT_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_previous_assistant_message_is_sent_as_truncated_context():
    complete = declares("document_question")
    await classify_intent(complete, "yes please", "Which file?" + "x" * 1000)
    _, user = complete.calls[0]
    assert user.startswith("Previous assistant message: Which file?")
    assert user.endswith("\nUser message: yes please")
    assert len(user) < conversation.MAX_CONTEXT_CHARS + 100


@pytest.mark.asyncio
@pytest.mark.parametrize("previous", [None, "", "   "])
async def test_no_usable_previous_message_sends_only_the_question(previous):
    complete = declares("greeting")
    await classify_intent(complete, "hi", previous)
    assert complete.calls[0][1] == "hi"


def test_prompt_covers_roman_urdu_mixed_requests_and_the_safe_default():
    prompt = conversation.INTENT_SYSTEM_PROMPT
    for needle in ("Roman Urdu", "salam", "document_question", "If you are unsure"):
        assert needle in prompt


def test_server_owned_replies_exist_for_exactly_the_conversational_intents():
    assert set(REPLIES) == set(CONVERSATIONAL) == INTENTS - {"document_question"}
    for text in REPLIES.values():
        assert text.strip() and "[source" not in text and "file_" not in text


# --- ToolAgentAdapter wiring -----------------------------------------------------------


async def ask(question, intent_complete, steps=None, **settings):
    db = AsyncMock()
    chat = ScriptChat(steps if steps is not None else [AgentStepResult(text=CLAIM)])
    adapter = ToolAgentAdapter(
        db, Settings(_env_file=None, **settings), chat=chat, intent_complete=intent_complete
    )
    result = await adapter.answer(question, user_id=USER, history=[], history_window_complete=True)
    return result, chat, db


@pytest.mark.asyncio
@pytest.mark.parametrize("intent", sorted(CONVERSATIONAL))
async def test_conversational_intent_returns_server_text_without_touching_the_agent(intent):
    result, chat, db = await ask("Hello, can you hear me?", declares(intent))
    assert result.answer == REPLIES[intent]
    assert result.citations == () and result.retrieval_count == 0
    assert chat.received == [] and not db.mock_calls  # No agent call, no SQL, no embeddings.


@pytest.mark.asyncio
async def test_model_prose_in_the_classifier_reply_is_never_shown():
    result, _, _ = await ask(
        "hi", declares("greeting", reply="Your contract says refunds are 90 days", text=CLAIM)
    )
    assert result.answer == REPLIES["greeting"]
    assert "90 days" not in result.answer and CLAIM not in result.answer


@pytest.mark.asyncio
async def test_document_question_goes_to_the_grounded_agent():
    result, chat, _ = await ask("Hi, summarize my resume", declares("document_question"))
    assert len(chat.received) == 1  # The agent ran; with no tools its prose is still refused.
    assert result.answer == NO_CONTENT and CLAIM not in result.answer


@pytest.mark.asyncio
@pytest.mark.parametrize("broken", [failing(RuntimeError("down")), raw("garbage")])
async def test_classifier_failure_never_blocks_a_question(broken):
    result, chat, _ = await ask("What does the contract say?", broken)
    assert len(chat.received) == 1 and result.answer == NO_CONTENT


@pytest.mark.asyncio
async def test_demo_mode_never_calls_the_classifier():
    complete = declares("greeting")
    _, chat, _ = await ask("hi", complete, demo_mode=True)
    assert complete.calls == [] and len(chat.received) == 1


@pytest.mark.asyncio
async def test_without_a_classifier_behaviour_is_unchanged():
    result, chat, _ = await ask("Hello", None)
    assert result.answer == "Hello!" and len(chat.received) == 1  # Legacy exact-phrase path.


# --- Legacy exact-phrase fallback (used when no classifier is wired) must stay strict -----


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        "Hello, can you summarize my resume?",
        "Hi, what does the contract say about refunds?",
        "Thanks, what is the deadline?",
        "Hey, which file mentions onboarding?",
    ],
)
async def test_fallback_greeting_plus_document_question_still_needs_evidence(question):
    state, _, _ = await run([AgentStepResult(text=CLAIM)], question=question)
    assert state["final_answer"] == NO_CONTENT
    assert not state["citations"] and CLAIM not in state["final_answer"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question,expected",
    [("Hey!", "Hello!"), ("Good morning!", "Hello!"), ("Thanks!", "You're welcome!")],
)
async def test_fallback_punctuated_greetings_keep_working(question, expected):
    state, _, _ = await run([AgentStepResult(text=CLAIM)], question=question)
    assert state["final_answer"] == expected


@pytest.mark.asyncio
async def test_adapter_passes_only_the_last_assistant_turn_as_context():
    complete = declares("document_question")
    db = AsyncMock()
    adapter = ToolAgentAdapter(
        db,
        Settings(_env_file=None),
        chat=ScriptChat([AgentStepResult(text=CLAIM)]),
        intent_complete=complete,
    )
    history = [
        {"role": "user", "text": "first question"},
        {"role": "assistant", "text": "first answer"},
        {"role": "user", "text": "second question"},
        {"role": "assistant", "text": "Which file should I look up?"},
    ]
    await adapter.answer("yes please", user_id=USER, history=history, history_window_complete=True)
    assert complete.calls[0][1] == (
        "Previous assistant message: Which file should I look up?\nUser message: yes please"
    )
