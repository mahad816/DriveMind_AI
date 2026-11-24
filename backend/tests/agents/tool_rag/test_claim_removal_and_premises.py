"""Claim-check removal by statement index (KI-035) and the premise rules in the prompts (tickets A and B).

Everything here is structural and free: the checker's model is a scripted JSON reply. Nothing in this file shows
that a real model follows the revised prompts; that needs the small real-model validation (not run).
"""

import json
import logging
import re
from unittest.mock import AsyncMock

import pytest

from app.agents.tool_rag.claim_check import (
    SYSTEM_PROMPT,
    build_user_message,
    enforce_claims,
    split_statements,
)
from app.agents.tool_rag.prompts import AGENT_SYSTEM_PROMPT

EVIDENCE = "[plan.txt]\nThe Wharf plan is a draft. A board decision is scheduled for January 2027. Refunds take 30 days."


def flag(*labels: str) -> AsyncMock:
    return AsyncMock(return_value=json.dumps({"unsupported": list(labels)}))


async def run(answer: str, *labels: str):
    return await enforce_claims(flag(*labels), answer, EVIDENCE, "question")


# --- removal: units are the ones the checker saw -------------------------------------------------


async def test_a_flagged_numbered_statement_goes_and_its_neighbours_stay() -> None:
    answer = "1. The plan is a draft. [source_1]\n2. Refunds take 90 days. [source_1]\n3. A decision is due. [source_1]"
    result = await run(answer, "S2")
    assert result.text == "1. The plan is a draft. [source_1]\n3. A decision is due. [source_1]"
    assert result.removed == 1


async def test_a_flagged_first_sentence_of_a_numbered_line_keeps_the_list_number_for_the_survivor() -> (
    None
):
    result = await run("1. Wrong claim. Right claim. [source_1]\n2. Other. [source_1]", "S1")
    assert result.text == "1. Right claim. [source_1]\n2. Other. [source_1]"
    assert result.removed == 1


async def test_a_bullet_prefix_moves_to_the_surviving_sentence() -> None:
    result = await run("- Wrong claim about the plan. Right claim about the plan.", "S1")
    assert result.text == "- Right claim about the plan."


async def test_every_sentence_of_a_multi_sentence_line_can_be_flagged_independently() -> None:
    answer = "Alpha is plainly true. Beta is wholly invented. Gamma is plainly true. Delta is wholly invented."
    result = await run(answer, "S2", "S4")
    assert result.text == "Alpha is plainly true. Gamma is plainly true."
    assert result.removed == 2


async def test_only_the_flagged_copy_of_a_repeated_statement_is_removed() -> None:
    answer = "Refunds take 30 days.\nSomething else is stated here.\nRefunds take 30 days."
    result = await run(answer, "S3")
    assert result.text == "Refunds take 30 days.\nSomething else is stated here."
    assert result.removed == 1


async def test_two_flagged_copies_of_a_repeated_statement_count_twice() -> None:
    result = await run(
        "Refunds take 90 days.\nKeep this line here.\nRefunds take 90 days.", "S1", "S3"
    )
    assert result.text == "Keep this line here." and result.removed == 2


async def test_citation_markers_of_surviving_statements_are_untouched() -> None:
    result = await run("Wrong claim here. [source_2] Right claim here. [source_1]", "S1")
    assert result.text == "Right claim here. [source_1]"


async def test_markdown_structure_stays_readable() -> None:
    answer = "## Summary\n\nIntro line here today.\n\n- Wrong claim about X.\n- Right claim about Y.\n\nClosing line stays."
    result = await run(answer, "S3")
    assert (
        result.text
        == "## Summary\n\nIntro line here today.\n\n- Right claim about Y.\n\nClosing line stays."
    )


async def test_a_colon_lead_in_with_inline_items_removes_only_the_flagged_item() -> None:
    result = await run("The steps are the following: 1. Open the form. 2. Invent a rule.", "S3")
    assert "Invent a rule" not in result.text and "Open the form" in result.text
    assert result.removed == 1


async def test_the_count_and_the_log_equal_what_really_went(
    caplog: pytest.LogCaptureFixture,
) -> None:
    answer = "1. First fact is stated here. Second fact is stated here. Third fact is stated here.\n2. Fourth fact is stated here."
    with caplog.at_level(logging.INFO):
        result = await run(answer, "S1", "S3", "S4")
    gone = len(split_statements(answer)) - len(split_statements(result.text))
    assert gone == 3 == result.removed
    assert [int(n) for n in re.findall(r"REMOVED count=(\d+)", caplog.text)] == [3]


async def test_whole_answer_replacement_still_signals_nothing_left() -> None:
    result = await run("1. Wrong claim. Another wrong claim. [source_1]", "S1", "S2")
    assert result.text == "" and result.nothing_left and result.removed == 2


async def test_unflagged_lines_keep_their_exact_inner_text() -> None:
    answer = (
        "  Indented line with   odd spacing.  \nWrong claim is made here.\nTail line is kept here."
    )
    result = await run(answer, "S2")
    assert result.text == "Indented line with   odd spacing.  \nTail line is kept here.".strip()


# --- checker verdict handling: what a scripted verdict does ----------------------------------------


async def test_a_mixed_answer_keeps_the_supported_statement_and_drops_the_invented_event() -> None:
    answer = "The plan is a draft. [source_1] The board rejected the plan in March. [source_1]"
    result = await run(answer, "S2")
    assert result.text == "The plan is a draft. [source_1]"


async def test_a_supported_numeric_answer_is_untouched() -> None:
    answer = "Refunds take 30 days. [source_1]"
    assert (await run(answer)).text == answer


async def test_an_incorrect_numeric_answer_is_removed_when_flagged_and_gets_the_absent_number_hint() -> (
    None
):
    answer = "Refunds take 90 days. [source_1]"
    assert "[S1] 90" in build_user_message(
        split_statements(answer), EVIDENCE, "How long are refunds?"
    )
    result = await run(answer, "S1")
    assert result.nothing_left


# --- prompts: structure only, not model behaviour ----------------------------------------------------


def test_checker_prompt_no_longer_excuses_a_statement_for_partial_support() -> None:
    assert "partial support" not in SYSTEM_PROMPT
    assert "most of the statement is in the evidence" not in SYSTEM_PROMPT


def test_checker_prompt_requires_each_material_assertion_and_rejects_user_premises_as_evidence() -> (
    None
):
    text = SYSTEM_PROMPT
    assert "on its own" in text and "even when the rest of it is supported" in text
    assert "the user's question assumes" in text and "is not evidence" in text


def test_checker_prompt_keeps_the_protections_and_the_allowances() -> None:
    text = SYSTEM_PROMPT
    for needle in (
        "Numbers written in a statement that appear nowhere",
        "Numbers the user wrote are not claims",
        "simple arithmetic",
        "do not establish it",
        "conversational wording",
        "Reply with JSON only",
    ):
        assert needle in text


def test_agent_prompt_treats_question_assumptions_as_unverified_without_case_specific_words() -> (
    None
):
    text = AGENT_SYSTEM_PROMPT
    assert "unverified until returned evidence supports it" in text
    assert "not that it is false" in text and "Do not refuse the whole question" in text
    for benchmark_word in ("Fennick", "Wharf", "board", "January", "2027"):
        assert benchmark_word not in text
        assert benchmark_word not in SYSTEM_PROMPT
