"""A supported lead-in survives when the items it introduced are removed; a pure heading does not (P2 #3).

The checker's model is a scripted JSON reply, so these tests prove what ``enforce_claims`` does with a verdict, never
that a model gives it. Expected values are the published text, not counters. A "lead-in" is a statement that ends in
a colon and introduces the lines below it; it is *meaningful* when it is more than a two-word label and most of its
longer words are in the evidence the checker was given, *structural* otherwise (a heading, a short label, or
boilerplate such as "here is what I found").
"""

import json
from unittest.mock import AsyncMock

from app.agents.tool_rag.claim_check import enforce_claims, split_statements

EVIDENCE = "[policy.txt]\nRefunds take 30 days for hardware items. Receipts are required. Every claim is reviewed."
LEAD = "Refunds take 30 days for these items:"


def labels(answer: str, *fragments: str) -> list[str]:
    """The checker's labels for the statements that contain any fragment (numbering as the checker sees it)."""
    return [
        f"S{i}"
        for i, statement in enumerate(split_statements(answer), 1)
        if any(f in statement for f in fragments)
    ]


async def run(answer: str, *fragments: str):  # noqa: ANN201
    reply = json.dumps({"unsupported": labels(answer, *fragments)})
    return await enforce_claims(AsyncMock(return_value=reply), answer, EVIDENCE, "question")


# --- A. a meaningful lead-in survives, without a dangling colon -------------------------------------------


async def test_supported_lead_in_survives_when_every_bullet_is_flagged() -> None:
    result = await run(f"{LEAD}\n- Wrong one is here.\n- Wrong two is here.", "Wrong")
    assert result.text == "Refunds take 30 days for these items."
    assert result.removed == 2 and not result.nothing_left


async def test_supported_lead_in_survives_when_a_numbered_list_is_flagged() -> None:
    result = await run(f"{LEAD}\n1. Wrong one is here.\n2. Wrong two is here.", "Wrong")
    assert result.text == "Refunds take 30 days for these items."


async def test_supported_sentence_then_a_vacuous_lead_in_keeps_only_the_sentence() -> None:
    """Probe A: the supported sentence stays; the colon-ending boilerplate that introduced nothing goes."""
    answer = (
        "Refunds take 30 days. The steps are:\n- Wrong step one is here.\n- Wrong step two is here."
    )
    result = await run(answer, "Wrong")
    assert result.text == "Refunds take 30 days."
    assert (
        result.removed == 3 and not result.nothing_left
    )  # two flagged, one lead-in dropped with them


async def test_a_lead_in_with_its_own_citation_keeps_it_and_loses_the_colon() -> None:
    result = await run(f"{LEAD} [source_1]\n- Wrong one is here.\n- Wrong two is here.", "Wrong")
    assert result.text == "Refunds take 30 days for these items. [source_1]"


# --- B. a pure heading does not survive as an answer ------------------------------------------------------


async def test_a_short_label_with_all_its_bullets_flagged_leaves_no_answer() -> None:
    result = await run("Additional details:\n- Wrong one is here.\n- Wrong two is here.", "Wrong")
    assert result.text == "" and result.nothing_left and result.removed == 3


async def test_a_markdown_heading_with_all_its_content_flagged_leaves_no_answer() -> None:
    result = await run("## Details\n- Wrong one is here.\n- Wrong two is here.", "Wrong")
    assert result.text == "" and result.nothing_left


async def test_boilerplate_lead_in_with_all_its_bullets_flagged_leaves_no_answer() -> None:
    """Probe B: the reported count equals the statements that really went (flagged and the lead-in)."""
    answer = "Here is what I found today:\n- Wrong claim one is here.\n- Wrong claim two is here.\n[source_6]"
    result = await run(answer, "Wrong")
    assert result.text == "" and result.nothing_left and result.removed == 3


async def test_a_heading_is_dropped_but_a_supported_sentence_elsewhere_stays() -> None:
    answer = "Receipts are required.\n\nAdditional details:\n- Wrong one is here."
    result = await run(answer, "Wrong")
    assert result.text == "Receipts are required."


# --- C. a list that partly survives ----------------------------------------------------------------------


async def test_lead_in_and_the_supported_bullet_stay_when_one_bullet_is_flagged() -> None:
    answer = f"{LEAD}\n- Receipts are required.\n- Wrong claim is here."
    result = await run(answer, "Wrong")
    assert result.text == f"{LEAD}\n- Receipts are required."
    assert result.removed == 1


async def test_numbers_are_not_lost_or_duplicated_when_a_numbered_item_goes() -> None:
    answer = (
        f"{LEAD}\n1. Receipts are required.\n2. Wrong claim is here.\n3. Every claim is reviewed."
    )
    result = await run(answer, "Wrong")
    assert result.text == f"{LEAD}\n1. Receipts are required.\n3. Every claim is reviewed."


async def test_a_nested_lead_in_loses_its_colon_when_its_children_go_and_its_siblings_stay() -> (
    None
):
    answer = (
        f"{LEAD}\n- Receipts are required:\n  - Wrong a is here.\n  - Wrong b is here.\n"
        "- Every claim is reviewed."
    )
    result = await run(answer, "Wrong")
    assert result.text == f"{LEAD}\n- Receipts are required.\n- Every claim is reviewed."


async def test_an_indented_child_that_survives_keeps_its_parent_colon() -> None:
    answer = f"{LEAD}\n- Receipts are required:\n  - Every claim is reviewed.\n  - Wrong b is here."
    result = await run(answer, "Wrong")
    assert result.text == f"{LEAD}\n- Receipts are required:\n  - Every claim is reviewed."


async def test_a_colon_before_an_inline_numbered_list_is_tidied_when_the_list_goes() -> None:
    result = await run("Refunds take 30 days for these items: 1. Wrong one. 2. Wrong two.", "Wrong")
    assert result.text == "Refunds take 30 days for these items."


# --- D. citations -----------------------------------------------------------------------------------------


async def test_the_marker_line_of_removed_bullets_does_not_follow_the_lead_in() -> None:
    answer = f"{LEAD}\n- Wrong one is here.\n- Wrong two is here.\n[source_1]"
    result = await run(answer, "Wrong")
    assert result.text == "Refunds take 30 days for these items."


async def test_the_marker_line_stays_with_a_surviving_bullet() -> None:
    answer = f"{LEAD}\n- Receipts are required.\n- Wrong claim is here.\n[source_1]"
    result = await run(answer, "Wrong")
    assert result.text == f"{LEAD}\n- Receipts are required.\n[source_1]"


# --- repeated statements, partial removal, complete removal, plain sentences ------------------------------


async def test_a_repeated_statement_is_removed_by_position_not_by_text() -> None:
    answer = f"{LEAD}\n- Wrong claim is here.\n- Receipts are required.\n- Wrong claim is here."
    reply = json.dumps({"unsupported": ["S2"]})  # only the first copy
    result = await enforce_claims(AsyncMock(return_value=reply), answer, EVIDENCE, "question")
    assert result.text == f"{LEAD}\n- Receipts are required.\n- Wrong claim is here."


async def test_one_flagged_sentence_of_a_plain_paragraph_goes_and_the_rest_stays() -> None:
    result = await run("Refunds take 30 days. Wrong claim is here.", "Wrong")
    assert result.text == "Refunds take 30 days."
    assert result.removed == 1


async def test_a_plain_supported_sentence_is_untouched() -> None:
    answer = "Refunds take 30 days for hardware items."
    result = await run(answer, "nothing matches this")
    assert result.text == answer and result.removed == 0 and result.checked


async def test_flagging_every_statement_triggers_the_no_evidence_fallback() -> None:
    result = await run("Wrong one is here. Wrong two is here.", "Wrong")
    assert result.text == "" and result.nothing_left and result.removed == 2


async def test_an_answer_with_no_removal_keeps_its_own_colon() -> None:
    answer = f"{LEAD}\n- Receipts are required."
    result = await run(answer, "nothing matches this")
    assert result.text == answer


async def test_a_lead_in_that_was_never_followed_by_items_is_left_as_written() -> None:
    answer = f"Receipts are required. {LEAD}"
    result = await run(answer, "nothing matches this")
    assert result.text == answer


# --- blank lines and markdown structure (P2-1) -------------------------------------------------------------


async def test_a_blank_line_between_a_lead_in_and_its_list_does_not_leave_the_colon() -> None:
    result = await run(f"{LEAD}\n\n- Wrong one is here.\n- Wrong two is here.", "Wrong")
    assert result.text == "Refunds take 30 days for these items."
    assert result.removed == 2 and not result.nothing_left


async def test_a_loose_list_with_blank_lines_between_items_is_one_list() -> None:
    result = await run(f"{LEAD}\n\n- Wrong one is here.\n\n- Wrong two is here.", "Wrong")
    assert result.text == "Refunds take 30 days for these items."


async def test_a_boilerplate_lead_in_before_a_blank_line_is_dropped_and_the_paragraph_before_stays() -> (
    None
):
    answer = (
        "Receipts are required.\n\nHere is what I found today:\n\n"
        "- Wrong one is here.\n- Wrong two is here."
    )
    result = await run(answer, "Wrong")
    assert result.text == "Receipts are required."
    assert result.removed == 3


async def test_an_unrelated_supported_paragraph_after_the_removed_list_is_not_swept_up() -> None:
    answer = f"{LEAD}\n\n- Wrong one is here.\n\nReceipts are required."
    result = await run(answer, "Wrong")
    assert result.text == "Refunds take 30 days for these items.\n\nReceipts are required."


async def test_a_lead_in_followed_by_a_plain_paragraph_keeps_its_colon() -> None:
    """No list was introduced and nothing was removed from under it: the text is left as written."""
    answer = f"{LEAD}\n\nReceipts are required.\n- Wrong claim is here."
    result = await run(answer, "Wrong")
    assert result.text == f"{LEAD}\n\nReceipts are required."


async def test_a_heading_whose_whole_section_is_flagged_leaves_no_answer() -> None:
    answer = "## Details\n\nWrong claim is here.\n\nAnother wrong claim is here."
    result = await run(answer, "Wrong claim", "wrong claim")
    assert result.text == "" and result.nothing_left


async def test_a_heading_keeps_a_section_paragraph_that_survives() -> None:
    answer = "## Details\nWrong claim is here.\n\nReceipts are required."
    result = await run(answer, "Wrong")
    assert result.text == "## Details\n\nReceipts are required."


async def test_a_flagged_section_goes_and_the_next_section_stays() -> None:
    answer = "## One\nWrong claim is here.\n\n## Two\nReceipts are required."
    result = await run(answer, "Wrong")
    assert result.text == "## Two\nReceipts are required."


async def test_nested_headings_are_closed_from_the_inside_out() -> None:
    result = await run("## One\n### Sub\nWrong claim is here.", "Wrong")
    assert result.text == "" and result.nothing_left


# --- source labels are provenance, not evidence (P2-2) ----------------------------------------------------


async def test_words_of_a_file_name_do_not_make_a_source_naming_lead_in_meaningful() -> None:
    answer = "According to the employee handbook:\n- Wrong a is here.\n- Wrong b is here."
    evidence = "[employee_handbook.txt]\nUnrelated text about parking."
    reply = json.dumps({"unsupported": labels(answer, "Wrong")})
    result = await enforce_claims(AsyncMock(return_value=reply), answer, evidence, "question")
    assert result.text == "" and result.nothing_left and result.removed == 3


async def test_words_of_the_document_text_still_make_a_lead_in_meaningful() -> None:
    answer = "According to the employee handbook:\n- Wrong a is here.\n- Wrong b is here."
    evidence = "[notes.txt]\nThe employee handbook says visitors need a badge."
    reply = json.dumps({"unsupported": labels(answer, "Wrong")})
    result = await enforce_claims(AsyncMock(return_value=reply), answer, evidence, "question")
    assert result.text == "According to the employee handbook."
