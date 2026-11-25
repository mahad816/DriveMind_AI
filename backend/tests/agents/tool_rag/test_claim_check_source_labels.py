"""A file name or source label says where a passage came from; it is never evidence that a statement is true (P2-2).

The checker still receives the labels (it needs them to judge "the handbook says ..." and the citation mapping uses
them); what changes is every deterministic place that used the evidence text as proof: the grounding of a lead-in and
the "number appears nowhere in the evidence" hint. Free tests, no model.
"""

from typing import Any

import pytest

from app.agents.tool_rag.claim_check import (
    SYSTEM_PROMPT,
    build_user_message,
    evidence_body,
    numbers_missing,
)
from evaluation.rag_eval import claim_trace, planted_claims

LABELLED = "[report_2023.pdf]\nBudget grew.\n\n[plan_v7.txt]\nSecond passage."


def test_evidence_body_drops_the_section_labels_and_keeps_the_text() -> None:
    assert evidence_body(LABELLED) == "Budget grew.\n\nSecond passage."


def test_a_bracketed_line_inside_a_passage_is_text_not_a_label() -> None:
    body = "[a.txt]\nBefore\n[TBD]\nAfter"
    assert evidence_body(body) == "Before\n[TBD]\nAfter"


def test_text_with_no_label_is_returned_unchanged() -> None:
    assert evidence_body("plain passage") == "plain passage"


def test_the_checker_still_receives_the_labels() -> None:
    message = build_user_message(["Budget grew."], LABELLED, "")
    assert "[report_2023.pdf]" in message and "[plan_v7.txt]" in message


def test_a_number_that_is_only_in_a_file_name_is_reported_as_absent() -> None:
    message = build_user_message(["Budget was 2023 dollars."], LABELLED, "")
    assert (
        "appear nowhere in the evidence" in message and "2023" in message.split("appear nowhere")[1]
    )


def test_a_number_in_the_passage_text_is_not_reported() -> None:
    message = build_user_message(
        ["Budget was 2023 dollars."], "[x.txt]\nBudget was 2023 dollars.", ""
    )
    assert "appear nowhere" not in message


def test_a_number_the_user_wrote_is_still_given() -> None:
    message = build_user_message(["Budget was 2023 dollars."], LABELLED, "What about 2023?")
    assert "appear nowhere" not in message


def test_the_trace_computes_the_same_hint_as_the_application() -> None:
    hints = claim_trace._number_hints(["Budget was 2023 dollars."], LABELLED, "")
    assert hints == {"S1": ["2023"]}


def test_planted_claims_leaves_out_a_case_whose_number_is_only_in_a_file_name() -> None:
    case = {
        "id": "t01",
        "split": "dev",
        "question": "How much?",
        "expected_behavior": "answer",
        "computed": False,
        "category": "single_fact",
        "reference_answer": "Budget was 2023 dollars.",
        "expected_files": ["v1/report_2023.txt"],
    }
    assert (
        planted_claims.build_items({"cases": [case]}, {"v1/report_2023.txt": "Budget grew."}) == []
    )


def test_numbers_missing_itself_is_unchanged_for_plain_text() -> None:
    assert numbers_missing("It was 30 days.", "Refunds take 30 days.") == []
    assert numbers_missing("It was 31 days.", "Refunds take 30 days.") == ["31"]


def test_the_prompt_tells_the_checker_that_labels_are_not_evidence() -> None:
    assert "file name" in SYSTEM_PROMPT.lower() and "never evidence" in SYSTEM_PROMPT


@pytest.mark.parametrize("name", ["plain.txt", "odd\r\nname [1].txt", "a\n\nb.txt"])
def test_the_trace_offsets_follow_the_same_label_as_the_evidence_text(name: str) -> None:
    """The trace must locate chunks in the text the checker saw: one label implementation (``section_label``)."""
    from types import SimpleNamespace

    from app.agents.tool_rag.claim_check import evidence_text
    from evaluation.rag_eval.claim_trace import describe_evidence

    body = "Body one."
    member = SimpleNamespace(filename=name, chunk_id="c1", chunk_index=0, file_id="f1")
    section = SimpleNamespace(
        members=[member], combined_text=body, member_ranges=[("c1", 0, len(body))]
    )
    parts: Any = [section]
    sent = evidence_text(parts)
    chunk = describe_evidence(parts, sent)["sections"][0]["chunks"][0]
    assert sent[chunk["start"] : chunk["end"]] == body
