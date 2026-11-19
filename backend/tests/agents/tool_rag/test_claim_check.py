"""KI-002: statements the retrieved evidence does not support are dropped before citation handling.

The model call is faked with a scripted JSON reply; what is under test is everything around it:
how an answer is cut into statements, how a reply is validated, what is removed, and that no
failure of the check can ever remove (or block) an answer.
"""

import json
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tool_rag.agent_models import AgentStepResult
from app.agents.tool_rag.agent_service import ToolRagAgentService
from app.agents.tool_rag.claim_check import (
    ClaimCheckResult,
    clean_unit,
    enforce_claims,
    find_unsupported,
    is_framing,
    parse_unsupported,
    split_statements,
)
from app.core.config import Settings
from app.llm.prompts import NO_EVIDENCE_ANSWER
from app.services.tool_agent_service import ToolAgentAdapter
from tests.agents.tool_rag.test_agent_loop import InventoryDB, ScriptChat, call, chunk, file
from tests.agents.tool_rag.test_grounding_policy import SEARCH
from tests.agents.tool_rag.test_tool_execution import USER


def make_settings(**overrides: Any) -> Settings:
    """Settings that ignore any local .env file."""
    return Settings(**{"_env_file": None, **overrides})


EVIDENCE = "[policy.txt]\nAuthoritative refund policy text."


def reply(*labels):
    """A scripted model: always answers with these unsupported labels."""
    return AsyncMock(return_value=json.dumps({"unsupported": list(labels)}))


# --- splitting -------------------------------------------------------------------------------


def test_splits_lines_and_sentences_and_keeps_list_numbers_with_their_text():
    text = "Try the following: 1. Check the setting. 2. Ensure the cable is connected to the TV.\n- Reboot it [1]."
    assert split_statements(text) == [
        "Try the following:",
        "1. Check the setting.",
        "2. Ensure the cable is connected to the TV.",
        "- Reboot it [1].",
    ]


def test_a_citation_marker_after_the_full_stop_stays_with_its_sentence():
    assert split_statements("Refunds take 30 days. [source_1] Fees apply. [2]") == [
        "Refunds take 30 days. [source_1]",
        "Fees apply. [2]",
    ]


def test_a_sentence_that_ends_in_a_number_is_not_cut():
    assert split_statements("The fee is 5. It is paid monthly.") == [
        "The fee is 5.",
        "It is paid monthly.",
    ]
    assert clean_unit("It costs 5.") == "It costs 5."
    assert clean_unit("Check the TV. 3.") == "Check the TV."


@pytest.mark.parametrize(
    "text,framing",
    [
        ("Key points:", True),
        ("Biddle.", True),
        ("Yes, it is.", True),
        ("Refunds are approved within 90 days.", False),
    ],
)
def test_framing_is_structural_not_semantic(text, framing):
    assert is_framing(text) is framing


# --- reply validation ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,count,expected",
    [
        ('{"unsupported": ["S2", "s3"]}', 3, frozenset({1, 2})),
        ('{"unsupported": [1, 3]}', 3, frozenset({0, 2})),
        ('{"unsupported": []}', 3, frozenset()),
        ('{"unsupported": ["S4"]}', 3, None),  # out of range: never guess
        ('{"unsupported": [0]}', 3, None),
        ('{"unsupported": [true]}', 3, None),  # a bool is not a statement number
        ('{"unsupported": "S1"}', 3, None),
        ('{"other": []}', 3, None),
        ("not json", 3, None),
    ],
)
def test_parse_unsupported_accepts_only_valid_labels(raw, count, expected):
    assert parse_unsupported(raw, count) == expected


# --- the model call --------------------------------------------------------------------------


async def test_find_unsupported_returns_flagged_indexes_without_framing():
    statements = ["Refunds are always approved within 90 days.", "Key points:"]
    assert await find_unsupported(reply("S1", "S2"), statements, EVIDENCE) == frozenset({0})


@pytest.mark.parametrize(
    "failure", [TimeoutError(), RuntimeError("provider down"), ValueError("x")]
)
async def test_a_failing_model_call_means_unchecked_not_unsupported(failure):
    assert (
        await find_unsupported(
            AsyncMock(side_effect=failure), ["A long enough statement here."], EVIDENCE
        )
        is None
    )


async def test_nothing_is_asked_without_statements_or_evidence_or_with_too_many():
    complete = reply("S1")
    assert await find_unsupported(complete, [], EVIDENCE) is None
    assert await find_unsupported(complete, ["A long enough statement here."], "   ") is None
    assert (
        await find_unsupported(complete, ["A long enough statement here."] * 41, EVIDENCE) is None
    )
    complete.assert_not_called()


# --- enforcement -----------------------------------------------------------------------------

FABRICATED = "Refunds are always approved within 90 days. [source_1]"


async def test_removes_only_the_flagged_statement_and_keeps_the_rest_intact():
    answer = "The policy is authoritative [source_1].\nRefunds are always approved within 90 days [source_1].\nIt is a text file."
    result = await enforce_claims(reply("S2"), answer, EVIDENCE)
    assert result.text == "The policy is authoritative [source_1].\nIt is a text file."
    assert result.removed == 1 and result.checked and not result.nothing_left


async def test_removes_one_sentence_from_the_middle_of_a_line():
    answer = "Refunds exist. Refunds are always approved within 90 days. They need a form."
    result = await enforce_claims(reply("S2"), answer, EVIDENCE)
    assert result.text == "Refunds exist. They need a form."


async def test_everything_flagged_means_nothing_left_for_the_caller_to_replace():
    result = await enforce_claims(reply("S1"), FABRICATED, EVIDENCE)
    assert result.text == "" and result.nothing_left and result.removed == 1


async def test_a_remaining_text_of_only_citation_markers_counts_as_nothing_left():
    result = await enforce_claims(
        reply("S1"), "Refunds are always approved within 90 days.\n[1]", EVIDENCE
    )
    assert result.nothing_left


async def test_no_flags_returns_the_answer_unchanged_and_marks_it_checked():
    result = await enforce_claims(reply(), FABRICATED, EVIDENCE)
    assert result == ClaimCheckResult(FABRICATED, 0, True)


async def test_an_unusable_check_leaves_the_answer_exactly_as_it_was():
    for complete in (
        AsyncMock(side_effect=TimeoutError()),
        AsyncMock(return_value="garbage"),
        reply("S9"),
    ):
        assert await enforce_claims(complete, FABRICATED, EVIDENCE) == ClaimCheckResult(
            FABRICATED, 0, False
        )


async def test_a_marker_only_answer_is_not_sent_to_the_model():
    complete = reply("S1")
    assert (await enforce_claims(complete, "[1] [2]", EVIDENCE)).checked is False
    complete.assert_not_called()


# --- inside the agent (the KI-002 reproduction, now with the check) ---------------------------


async def run_with(claim_check, steps):
    from unittest.mock import AsyncMock as AM

    retriever = AM()
    retriever.retrieve.return_value = [
        chunk()
    ]  # evidence text: "Authoritative refund policy text."
    service = ToolRagAgentService(ScriptChat(steps), claim_check=claim_check)
    return await service.run(
        "Synthetic question",
        user_id=USER,
        db=cast(AsyncSession, InventoryDB([file()])),
        retriever=retriever,
    )


def checker(complete):
    async def check(answer, evidence):
        return await enforce_claims(complete, answer, evidence)

    return check


async def test_ki002_an_unsupported_claim_is_not_published_with_a_real_citation():
    state = await run_with(
        checker(reply("S1")), [call("search_knowledge", SEARCH), AgentStepResult(text=FABRICATED)]
    )
    assert "90 days" not in (state["final_answer"] or "")
    assert state["final_answer"] == NO_EVIDENCE_ANSWER and state["citations"] == ()


async def test_a_supported_answer_still_gets_its_citation():
    supported = "Authoritative refund policy text. [source_1]"
    state = await run_with(
        checker(reply()), [call("search_knowledge", SEARCH), AgentStepResult(text=supported)]
    )
    assert "Authoritative refund policy text." in (state["final_answer"] or "")
    assert len(state["citations"]) == 1


async def test_partial_removal_keeps_the_supported_part_and_its_citation():
    mixed = "Authoritative refund policy text. [source_1]\nRefunds are always approved within 90 days. [source_1]"
    state = await run_with(
        checker(reply("S2")), [call("search_knowledge", SEARCH), AgentStepResult(text=mixed)]
    )
    assert "90 days" not in (
        state["final_answer"] or ""
    ) and "Authoritative refund policy text." in (state["final_answer"] or "")
    assert len(state["citations"]) == 1


async def test_the_check_only_runs_when_there_is_evidence():
    complete = reply("S1")
    state = await run_with(
        checker(complete), [AgentStepResult(text="Refunds are approved within 90 days.")]
    )
    complete.assert_not_called()
    assert state["final_answer"]  # existing no-tool behaviour is untouched


async def test_a_checker_that_raises_cannot_take_answering_down():
    async def broken(answer, evidence):
        raise RuntimeError("bug in the checker")

    supported = "Authoritative refund policy text. [source_1]"
    state = await run_with(
        broken, [call("search_knowledge", SEARCH), AgentStepResult(text=supported)]
    )
    assert state["failure"] is None and "Authoritative refund policy text." in (
        state["final_answer"] or ""
    )


# --- wiring through the adapter --------------------------------------------------------------


async def adapter_answer(settings, **kw):
    steps = [call("search_knowledge", SEARCH), AgentStepResult(text=FABRICATED)]
    retriever = AsyncMock()
    retriever.retrieve.return_value = [chunk()]
    db = InventoryDB([file()])
    adapter = ToolAgentAdapter(
        cast(AsyncSession, db), settings, chat=ScriptChat(steps), retriever=retriever, **kw
    )
    return await adapter.answer(
        "Synthetic question", user_id=USER, history=[], history_window_complete=True
    )


async def test_adapter_uses_an_injected_claim_checker():
    complete = reply("S1")
    result = await adapter_answer(make_settings(), claim_complete=complete)
    complete.assert_awaited()
    assert result.answer == NO_EVIDENCE_ANSWER and result.citations == ()


async def test_adapter_without_a_claim_checker_is_unchanged():
    result = await adapter_answer(make_settings())
    assert "90 days" in result.answer  # the documented gap when the check is not wired


def test_claim_check_settings_defaults():
    settings = make_settings()
    assert settings.claim_check_enabled is True and settings.claim_check_model == "gpt-5.4-mini"


def fake_service_factory(made):
    class Fake(ScriptChat):
        def __init__(self, settings):
            super().__init__([call("search_knowledge", SEARCH), AgentStepResult(text=FABRICATED)])
            self.model, self.closed = settings.chat_model, False
            made.append(self)

        async def complete_json(self, system, user):
            if self.model == "gpt-5.4-mini":  # the dedicated claim-check model
                return '{"unsupported": ["S1"]}'
            return '{"intent": "document_question"}'  # the intent gate on the chat model

        async def aclose(self):
            self.closed = True

    return Fake


async def owned_answer(monkeypatch, settings, factory):
    import app.services.tool_agent_service as integration

    monkeypatch.setattr(integration, "OpenAIAgentChatService", factory)
    retriever = AsyncMock()
    retriever.retrieve.return_value = [chunk()]
    adapter = ToolAgentAdapter(
        cast(AsyncSession, InventoryDB([file()])), settings, retriever=retriever
    )
    return await adapter.answer(
        "Synthetic question", user_id=USER, history=[], history_window_complete=True
    )


async def test_owned_path_builds_the_checker_on_its_own_model_and_closes_both_clients(monkeypatch):
    made: list = []
    result = await owned_answer(monkeypatch, make_settings(), fake_service_factory(made))
    assert [m.model for m in made] == ["gpt-5.4-nano", "gpt-5.4-mini"]
    assert all(m.closed for m in made)
    assert result.answer == NO_EVIDENCE_ANSWER and result.citations == ()


async def test_owned_path_can_switch_the_check_off(monkeypatch):
    made: list = []
    settings = make_settings(claim_check_enabled=False)
    result = await owned_answer(monkeypatch, settings, fake_service_factory(made))
    assert [m.model for m in made] == ["gpt-5.4-nano"] and "90 days" in result.answer


async def test_owned_path_unbuildable_checker_means_unchecked_not_unanswered(monkeypatch):
    made: list = []
    base = fake_service_factory(made)

    class NoJson(base):
        def __getattribute__(self, name):
            if name == "complete_json" and object.__getattribute__(self, "model") == "gpt-5.4-mini":
                raise AttributeError(name)
            return super().__getattribute__(name)

    result = await owned_answer(monkeypatch, make_settings(), NoJson)
    assert "90 days" in result.answer  # answered, just not checked
