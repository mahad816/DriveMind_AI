"""Backend stabilization of the claim check: citation-only lines, factual lead-ins, list markers, footer.

Free and structural. The checker's model is a scripted JSON reply, so nothing here shows that a real model
follows the revised prompt (qualified absence, document attribution, lead-ins). That needs the one bounded
real-model validation in ``docs/tickets/backend-stabilization/``; the prompt tests only pin what the prompt says.
"""

import json
from unittest.mock import AsyncMock

import pytest

from app.agents.tool_rag.agent_models import AgentStepResult
from app.agents.tool_rag.claim_check import (
    SYSTEM_PROMPT,
    enforce_claims,
    find_unsupported,
    is_framing,
    split_statements,
)
from tests.agents.tool_rag.test_claim_check import checker, reply, run_with
from tests.agents.tool_rag.test_agent_loop import call
from tests.agents.tool_rag.test_grounding_policy import SEARCH

EVIDENCE = "[handbook.txt]\nThe gate opens at 06:00. Slots are booked 36 hours ahead."


def flag(*labels: str) -> AsyncMock:
    return AsyncMock(return_value=json.dumps({"unsupported": list(labels)}))


async def run(answer: str, *labels: str):
    return await enforce_claims(flag(*labels), answer, EVIDENCE, "question")


# --- a citation marker on its own line is not a statement -------------------------------------------


def test_a_standalone_citation_line_is_not_a_statement() -> None:
    assert split_statements("The gate opens at 06:00.\n[source_6]") == ["The gate opens at 06:00."]
    assert split_statements("- The gate opens at 06:00.\n- [source_6]") == [
        "- The gate opens at 06:00."
    ]
    assert split_statements("Slots are booked early.  \n[source_1] [source_2]") == [
        "Slots are booked early."
    ]


def test_a_marker_with_text_is_still_a_statement() -> None:
    assert split_statements("[source_1] The gate opens at 06:00.") == [
        "[source_1] The gate opens at 06:00."
    ]


async def test_the_checker_is_not_shown_a_bare_marker() -> None:
    complete = flag()
    await enforce_claims(complete, "The gate opens at 06:00.\n[source_6]", EVIDENCE, "q")
    assert complete.await_args is not None
    shown = complete.await_args.args[1]
    assert "[S1] The gate opens at 06:00." in shown
    assert "[S2]" not in shown


async def test_a_flagged_bullet_goes_and_the_citation_line_stays_with_the_survivors() -> None:
    answer = "Intro line is here.\n- Wrong bullet is here.\n- Right bullet is here.\n[source_6]"
    result = await run(answer, "S2")
    assert result.text == "Intro line is here.\n- Right bullet is here.\n[source_6]"
    assert result.removed == 1 and not result.nothing_left


async def test_removing_the_last_bullet_keeps_the_citation_for_the_earlier_ones() -> None:
    result = await run("- Right bullet is here.\n- Wrong bullet is here.\n[source_6]", "S2")
    assert result.text == "- Right bullet is here.\n[source_6]"


async def test_when_every_statement_above_a_citation_line_goes_the_line_goes_too() -> None:
    result = await run("Wrong one is here.\nWrong two is here.\n[source_1]", "S1", "S2")
    assert result.text == "" and result.nothing_left and result.removed == 2


async def test_a_citation_line_never_moves_to_another_paragraph() -> None:
    answer = "A is stated here.\n[source_1]\n\nB is wrong here.\n[source_2]"
    result = await run(answer, "S2")
    assert result.text == "A is stated here.\n[source_1]"


async def test_a_citation_line_after_a_blank_line_belongs_to_the_text_above_it() -> None:
    answer = "Wrong claim is made.\n\n[source_1]\n\nRight claim stays."
    result = await run(answer, "S1")
    assert result.text == "Right claim stays."


async def test_an_unflagged_answer_with_a_citation_line_is_unchanged() -> None:
    answer = "- The gate opens at 06:00.\n[source_6]"
    result = await run(answer)
    assert result.text == answer and result.removed == 0 and result.checked


async def test_a_leading_citation_line_with_nothing_above_it_is_left_alone() -> None:
    result = await run("[source_1]\nWrong claim is made here.\nRight claim stays here.", "S1")
    assert result.text == "[source_1]\nRight claim stays here."


async def test_the_nm07_shape_keeps_its_citation_and_drops_a_flagged_attribution() -> None:
    """A lead-in that names a source, a supported fact and the model's trailing marker on its own line."""
    draft = "According to the policy handbook:\nAuthoritative refund policy text.\n[source_1]"
    state = await run_with(
        checker(reply("S1")), [call("search_knowledge", SEARCH), AgentStepResult(text=draft)]
    )
    answer = state["final_answer"] or ""
    assert "According to" not in answer
    assert "Authoritative refund policy text." in answer
    assert len(state["citations"]) == 1 and "[1]" in answer
    assert "Sources consulted" not in answer


# --- factual lead-ins are not framing ---------------------------------------------------------------


@pytest.mark.parametrize(
    "text,framing",
    [
        ("Key findings:", True),
        ("Summary:", True),
        ("**Key findings:**", True),
        ("Next steps:", True),
        ("Per the handbook:", False),
        ("From the handbook:", False),
        ("According to policy:", False),
        ("According to the driver handbook:", False),
        ("The approved policy requires:", False),
        ("The handbook says that for the north gate:", False),
        ("Yes, it is.", True),
        ("Refunds are approved within 90 days.", False),
    ],
)
def test_only_a_label_of_at_most_two_words_is_framing_a_colon_alone_is_not(
    text: str, framing: bool
) -> None:
    assert is_framing(text) is framing


async def test_a_flagged_factual_lead_in_is_not_ignored_but_a_flagged_label_is() -> None:
    statements = ["According to the driver handbook:", "- Slots are booked early.", "Key points:"]
    flagged = await find_unsupported(flag("S1", "S3"), statements, EVIDENCE, "q")
    assert flagged == frozenset({0})


async def test_a_flagged_short_source_lead_in_is_not_ignored() -> None:
    statements = ["Per the handbook:", "- Slots are booked early."]
    assert await find_unsupported(flag("S1"), statements, EVIDENCE, "q") == frozenset({0})


# --- citation lines in the other placement styles ---------------------------------------------------


async def test_markers_placed_before_their_text_follow_the_text_below_them() -> None:
    answer = "[source_1]\nWrong claim is made here.\n[source_2]\nRight claim stays here."
    result = await run(answer, "S1")
    assert result.text == "[source_2]\nRight claim stays here."


async def test_a_supported_sentence_before_a_trailing_lead_in_is_not_emptied() -> None:
    answer = (
        "Refunds take 30 days. The steps are:\n- Wrong step one is here.\n- Wrong step two is here."
    )
    result = await run(answer, "S3", "S4")
    # the supported sentence stays; the colon that introduced the removed items does not dangle
    assert result.text == "Refunds take 30 days."
    assert (
        result.removed == 3 and not result.nothing_left
    )  # two flagged, the vacuous lead-in dropped with them


async def test_a_citation_line_stays_with_a_supported_sentence_that_shares_a_line_with_a_lead_in() -> (
    None
):
    answer = "Refunds take 30 days. The steps are:\n- Wrong step one is here.\n[source_1]"
    result = await run(answer, "S3")
    assert result.text == "Refunds take 30 days.\n[source_1]"


async def test_a_lead_in_alone_does_not_keep_a_citation_or_count_as_an_answer() -> None:
    answer = "Here is what I found today:\n- Wrong claim one is here.\n- Wrong claim two is here.\n[source_6]"
    result = await run(answer, "S2", "S3")
    # the unflagged lead-in goes with the answer, so the count equals the statements really dropped
    assert result.text == "" and result.nothing_left and result.removed == 3


def test_only_protocol_and_numeric_markers_make_a_line_citation_only() -> None:
    assert split_statements("[TBD]") == ["[TBD]"]
    assert split_statements("- [ ] Check the gate opens.") == ["- [ ] Check the gate opens."]
    assert split_statements("Fact is stated here.\n[3]") == ["Fact is stated here."]
    # a marker followed by a full stop on a text line keeps its old splitting (unchanged, not a citation line)
    assert split_statements("[source_1]. Fact is stated here.") == [
        "[source_1].",
        "Fact is stated here.",
    ]


async def test_a_leading_marker_on_a_text_line_survives_when_a_later_sentence_goes() -> None:
    result = await run("[source_1]. Right claim is here. Wrong claim is here.", "S3")
    assert result.text == "[source_1]. Right claim is here."


# --- list markers and indentation in removal --------------------------------------------------------


@pytest.mark.parametrize("marker", ["+ ", "• ", "> ", "> - ", "- ", "1. "])
async def test_the_marker_of_a_removed_first_statement_moves_to_the_survivor(marker: str) -> None:
    result = await run(f"{marker}Wrong claim is made here. Right claim stays here.", "S1")
    assert result.text == f"{marker}Right claim stays here."


async def test_a_second_piece_of_an_indented_line_keeps_the_indent() -> None:
    # S1 is the lead-in, S2 "1. Open it here.", S3 "2. Close it here."; the answer text is stripped at its ends.
    result = await run("  The steps are as follows: 1. Open it here. 2. Close it here.", "S2")
    assert result.text == "The steps are as follows:\n  2. Close it here."


async def test_an_unflagged_copy_of_a_repeated_statement_survives_with_markers() -> None:
    answer = "+ Refunds take 30 days.\n+ Other fact is here.\n+ Refunds take 30 days."
    result = await run(answer, "S1")
    assert result.text == "+ Other fact is here.\n+ Refunds take 30 days."
    assert result.removed == 1


# --- the "Sources consulted" footer is not attached after the model's own citations were removed ---


async def test_no_footer_when_the_only_cited_statement_was_removed() -> None:
    draft = "The supplier is not stated in the documents.\nRefunds are always approved within 90 days. [source_1]"
    state = await run_with(
        checker(reply("S2")), [call("search_knowledge", SEARCH), AgentStepResult(text=draft)]
    )
    answer = state["final_answer"] or ""
    assert "supplier is not stated" in answer and "90 days" not in answer
    assert "Sources consulted" not in answer and state["citations"] == ()


async def test_an_uncited_draft_without_removals_keeps_the_consulted_footer() -> None:
    state = await run_with(
        checker(reply()),
        [
            call("search_knowledge", SEARCH),
            AgentStepResult(text="Authoritative refund policy text."),
        ],
    )
    assert "Sources consulted:" in (state["final_answer"] or "")
    assert len(state["citations"]) == 1


async def test_a_surviving_cited_statement_keeps_its_citation_and_gets_no_footer() -> None:
    draft = "Authoritative refund policy text. [source_1]\nRefunds are always approved within 90 days. [source_1]"
    state = await run_with(
        checker(reply("S2")), [call("search_knowledge", SEARCH), AgentStepResult(text=draft)]
    )
    answer = state["final_answer"] or ""
    assert "[1]" in answer and "Sources consulted" not in answer and len(state["citations"]) == 1


# --- prompt: structure only, never proof of model behaviour -----------------------------------------


def test_prompt_separates_what_the_passages_lack_from_a_claim_about_the_world() -> None:
    text = SYSTEM_PROMPT
    assert "not stated" in text and "does state" in text
    assert "never happened" in text or "does not exist" in text
    assert "do not establish it" in text  # the existing allowance is kept


def test_prompt_makes_document_attribution_a_material_assertion() -> None:
    text = SYSTEM_PROMPT
    assert "labelled with its file name" in text
    assert "place a fact comes from" in text
    assert "found only in a different document" in text


def test_prompt_treats_a_lead_in_that_names_a_source_as_a_claim() -> None:
    assert "lead-in" in SYSTEM_PROMPT and "names a source" in SYSTEM_PROMPT


def test_prompt_has_no_case_specific_words() -> None:
    for word in ("refrigerant", "supplier", "handbook", "customs", "Greywater", "Zone C", "Wren"):
        assert word not in SYSTEM_PROMPT
