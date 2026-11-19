"""Known defects in the native tool agent's final answer. Correct behaviour is asserted."""

import pytest

from app.agents.tool_rag.agent_models import AgentStepResult
from app.agents.tool_rag.finalization import NO_CONTENT
from tests.agents.tool_rag.test_agent_loop import call, run
from tests.agents.tool_rag.test_grounding_policy import SEARCH
from tests.known_issues import known_issue

# Model text must never reach the user when no tool ran (see test_grounding_policy), so
# it is deliberately a document-like claim: only a server-owned reply may be shown.
MODEL_TEXT = "The document describes experience in AI."

SOCIAL_VARIANTS = [
    "Hello, can you hear me?",  # The real failure reported against the paid OpenAI key.
    "Hi there",
    "How are you?",
    "Thanks a lot",
    "thank you so much",
    "What can you do?",
    "Who are you?",
]


async def _answer(question: str):
    state, _, retriever = await run([AgentStepResult(text=MODEL_TEXT)], question=question)
    return state, retriever


SUPPORTED_TODAY = {"Hey!": "Hello!", "Good morning!": "Hello!", "Thanks!": "You're welcome!"}


@pytest.mark.asyncio
@pytest.mark.parametrize("question,expected", SUPPORTED_TODAY.items())
async def test_ki001_guard_supported_greetings_keep_working(question, expected):
    """Passing today: ending punctuation is already ignored. Must survive the KI-001 fix."""
    state, _ = await _answer(question)
    assert state["final_answer"] == expected


# --- KI-001 -----------------------------------------------------------------------------


@known_issue(
    "KI-001", "greetings/small talk beyond an exact 10-phrase list get the NO_CONTENT refusal"
)
@pytest.mark.asyncio
@pytest.mark.parametrize("question", SOCIAL_VARIANTS)
async def test_ki001_social_input_is_not_refused_as_missing_evidence(question):
    state, retriever = await _answer(question)
    assert state["final_answer"] != NO_CONTENT
    assert state["final_answer"].strip()
    # A social reply must stay safe: server-owned text, no model prose, no sources.
    assert MODEL_TEXT not in state["final_answer"]
    assert not state["citations"] and state["retrieval_count"] == 0
    assert not state["tool_history"] and not retriever.retrieve.called


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
async def test_ki001_guard_greeting_plus_document_question_still_needs_evidence(question):
    """Passing today and must keep passing after KI-001 is fixed: do not over-broaden."""
    state, _ = await _answer(question)
    assert state["final_answer"] == NO_CONTENT
    assert not state["citations"] and MODEL_TEXT not in state["final_answer"]


# --- KI-002 -----------------------------------------------------------------------------


@known_issue(
    "KI-002", "a valid [source_N] marker is accepted even when the claim is not in the evidence"
)
@pytest.mark.asyncio
async def test_ki002_claim_absent_from_evidence_is_not_published_with_a_citation():
    # run() retrieves one chunk whose text is "Authoritative refund policy text.".
    fabricated = "Refunds are always approved within 90 days. [source_1]"
    state, _, _ = await run([call("search_knowledge", SEARCH), AgentStepResult(text=fabricated)])
    assert "90 days" not in state["final_answer"], (
        "Citation checking only proves source_1 exists; it never checks the claim "
        "against that source, so an unsupported statement is shown with a real citation."
    )
