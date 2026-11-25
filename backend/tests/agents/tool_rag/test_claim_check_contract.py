"""The claim-check correctness contract, as one table-driven suite (free; the checker's model is a scripted reply).

Contract (docs/specs/backend-stabilization.md, "Claim-check contract"):
A evidence: only a passage's text supports a claim; a file name or label is provenance, never evidence.
B structure: a heading is "#"s then a space; "#1 priority" and "Ticket #5" are facts; lists, nesting, blank lines.
C removal: flagged statements go; supported ones, meaningful lead-ins and unrelated paragraphs stay; no empty heading.
D citations: a marker stays with the text it follows, goes with text that was removed, and renumbers cleanly.
E fallback: the no-evidence reply only when nothing meaningful is left; any failure of the check leaves the answer.
Every test asserts the published text. ``tests/agents/tool_rag/test_claim_check_lead_ins.py`` has the worked examples.
"""

import itertools
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.agents.tool_rag import claim_check as cc
from app.agents.tool_rag.claim_check import (
    build_user_message,
    enforce_claims,
    evidence_body,
    evidence_text,
    is_framing,
    split_statements,
)
from app.llm.prompts import normalize_answer_citations
from evaluation.rag_eval.claim_trace import attribute_removals

EVIDENCE = (
    "[policy.txt]\nRefunds take 30 days for hardware items. Receipts are required. "
    "The north gate is priority one. Ticket 5 was closed yesterday. Ticket 123 was closed yesterday."
)
LEAD = "Refunds take 30 days for these items:"
CLOSED = "Refunds take 30 days for these items."


def labels(answer: str, *fragments: str) -> list[str]:
    return [
        f"S{i}" for i, s in enumerate(split_statements(answer), 1) if any(f in s for f in fragments)
    ]


async def run(answer: str, *fragments: str, evidence: str = EVIDENCE) -> Any:
    reply = json.dumps({"unsupported": labels(answer, *fragments)})
    return await enforce_claims(AsyncMock(return_value=reply), answer, evidence, "question")


# --- B. headings are "#"s and a space; hash-led facts are not headings ------------------------------------


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("# Heading\n- Wrong one is here.", ""),
        ("## Heading\n- Wrong one is here.", ""),
        ("### Heading\n- Wrong one is here.", ""),
        ("###### Heading\n- Wrong one is here.", ""),
        ("# Important information\n- Wrong one is here.", ""),
        ("#1 priority is the north gate.\nWrong claim is here.", "#1 priority is the north gate."),
        ("#123 was closed yesterday.\nWrong claim is here.", "#123 was closed yesterday."),
        (
            "Ticket #5 was closed yesterday.\nWrong claim is here.",
            "Ticket #5 was closed yesterday.",
        ),
        ("#hashtag is a fact here.\nWrong claim is here.", "#hashtag is a fact here."),
        (
            "#1 priority is the north gate.\n\n## Details\n- Wrong one is here.",
            "#1 priority is the north gate.",
        ),
    ],
)
async def test_headings_are_told_apart_from_facts_that_start_with_a_hash(
    answer: str, expected: str
) -> None:
    result = await run(answer, "Wrong")
    assert result.text == expected
    assert result.nothing_left == (expected == "")


# --- B/C. lead-ins: punctuation, paragraphs, markers -------------------------------------------------------


@pytest.mark.parametrize("punctuation", [":", ";"])
async def test_a_meaningful_lead_in_is_closed_whichever_mark_introduced_the_list(
    punctuation: str,
) -> None:
    answer = f"Refunds take 30 days for these items{punctuation}\n- Wrong one is here.\n- Wrong two is here."
    assert (await run(answer, "Wrong")).text == CLOSED


async def test_a_lead_in_that_already_ends_in_a_full_stop_is_left_as_it_is() -> None:
    result = await run(f"{CLOSED}\n- Wrong one is here.\n- Wrong two is here.", "Wrong")
    assert result.text == CLOSED and result.removed == 2


async def test_a_boilerplate_lead_in_with_a_semicolon_is_dropped_with_its_items() -> None:
    result = await run("Here is what I found today;\n- Wrong one is here.", "Wrong")
    assert result.text == "" and result.nothing_left


async def test_a_lead_in_followed_by_several_paragraphs_keeps_every_unrelated_paragraph() -> None:
    answer = f"{LEAD}\n\n- Wrong one is here.\n\nReceipts are required.\n\nThe north gate is priority one."
    result = await run(answer, "Wrong")
    assert result.text == f"{CLOSED}\n\nReceipts are required.\n\nThe north gate is priority one."


async def test_two_independent_lists_are_judged_separately() -> None:
    answer = (
        f"{LEAD}\n- Wrong a is here.\n- Wrong b is here.\n\n"
        "Another lead-in for these items:\n- Receipts are required."
    )
    result = await run(answer, "Wrong")
    assert result.text == f"{CLOSED}\n\nAnother lead-in for these items:\n- Receipts are required."


async def test_lists_separated_by_paragraphs_do_not_share_items() -> None:
    answer = f"{LEAD}\n- Wrong a is here.\n\nReceipts are required.\n\nSecond list for these items:\n- Wrong b is here."
    result = await run(answer, "Wrong")
    assert result.text == f"{CLOSED}\n\nReceipts are required."


@pytest.mark.parametrize("prefix", ["-", "*", "+", "•", "1.", "1)"])
async def test_every_list_marker_style_is_tidied_the_same_way(prefix: str) -> None:
    gone = await run(f"{LEAD}\n{prefix} Wrong one is here.\n{prefix} Wrong two is here.", "Wrong")
    assert gone.text == CLOSED
    kept = await run(
        f"{LEAD}\n{prefix} Receipts are required.\n{prefix} Wrong claim is here.", "Wrong"
    )
    assert kept.text == f"{LEAD}\n{prefix} Receipts are required."


async def test_items_separated_by_blank_lines_form_one_list() -> None:
    answer = f"{LEAD}\n\n- Receipts are required.\n\n- Wrong claim is here.\n\n- Wrong two is here."
    result = await run(answer, "Wrong")
    assert result.text == f"{LEAD}\n\n- Receipts are required."


# --- C. removal position and identity ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("answer", "flagged", "expected"),
    [
        (
            "Wrong one is here.\nReceipts are required.\nThe north gate is priority one.",
            "Wrong one",
            "Receipts are required.\nThe north gate is priority one.",
        ),
        (
            "Receipts are required.\nWrong one is here.\nThe north gate is priority one.",
            "Wrong one",
            "Receipts are required.\nThe north gate is priority one.",
        ),
        (
            "Receipts are required.\nThe north gate is priority one.\nWrong one is here.",
            "Wrong one",
            "Receipts are required.\nThe north gate is priority one.",
        ),
        (
            "Receipts are required. Wrong one is here. The north gate is priority one.",
            "Wrong one",
            "Receipts are required. The north gate is priority one.",
        ),
        (
            "1. Receipts are required. Wrong one is here.\n2. The north gate is priority one.",
            "Wrong one",
            "1. Receipts are required.\n2. The north gate is priority one.",
        ),
        (
            "1. Wrong one is here. Receipts are required.\n2. The north gate is priority one.",
            "Wrong one",
            "1. Receipts are required.\n2. The north gate is priority one.",
        ),
        (
            "Receipts are required.\nThe north gate is priority one.",
            "no such text",
            "Receipts are required.\nThe north gate is priority one.",
        ),
        ("Wrong one is here.\nWrong two is here.", "Wrong", ""),
    ],
)
async def test_a_statement_is_removed_wherever_it_stands(
    answer: str, flagged: str, expected: str
) -> None:
    result = await run(answer, flagged)
    assert result.text == expected
    assert result.nothing_left == (expected == "")


async def test_one_copy_of_a_repeated_statement_goes_and_the_other_stays() -> None:
    answer = (
        "Receipts are required.\nWrong one is here.\nReceipts are required.\nWrong one is here."
    )
    reply = json.dumps({"unsupported": ["S2"]})
    result = await enforce_claims(AsyncMock(return_value=reply), answer, EVIDENCE, "q")
    assert result.text == "Receipts are required.\nReceipts are required.\nWrong one is here."


# --- A. a file name or label is provenance, never evidence -------------------------------------------------

NAMES = [
    "employee_handbook.pdf",
    "Handbook [2025].pdf",
    "Policy [Final].docx",
    "report_2025_final.pdf",
    "notes (copy 2).txt",
    "Q&A #3 – 2025.txt",
    "a]b[c.txt",
    "odd name\nwith newline.txt",
]


def sections(name: str, text: str) -> list[Any]:
    return [SimpleNamespace(members=[SimpleNamespace(filename=name)], combined_text=text)]


@pytest.mark.parametrize("name", NAMES)
def test_the_label_never_reaches_the_text_used_as_evidence_whatever_the_file_is_called(
    name: str,
) -> None:
    labelled = evidence_text(sections(name, "Unrelated parking text."))
    assert evidence_body(labelled) == "Unrelated parking text."
    assert name.split("\n")[0] in labelled  # the checker still sees where the passage came from


def test_two_passages_each_lose_their_own_label_only() -> None:
    both = evidence_text(
        sections("A [1].pdf", "First text.") + sections("B (2).pdf", "Second text.")
    )
    assert evidence_body(both) == "First text.\n\nSecond text."


@pytest.mark.parametrize("name", NAMES)
async def test_a_lead_in_made_of_the_file_name_words_is_not_meaningful(name: str) -> None:
    words = " ".join(
        w for w in "".join(c if c.isalnum() else " " for c in name).split() if len(w) > 2
    )
    answer = f"According to {words}:\n- Wrong a is here.\n- Wrong b is here."
    result = await run(
        answer, "Wrong", evidence=evidence_text(sections(name, "Unrelated parking text."))
    )
    assert result.text == "" and result.nothing_left


@pytest.mark.parametrize("name", NAMES)
async def test_the_same_words_in_the_passage_text_do_ground_the_lead_in(name: str) -> None:
    words = "employee handbook visitors"
    answer = f"According to the {words}:\n- Wrong a is here.\n- Wrong b is here."
    body = f"The {words} say that visitors need a badge."
    result = await run(answer, "Wrong", evidence=evidence_text(sections(name, body)))
    assert result.text == f"According to the {words}."


@pytest.mark.parametrize("name", NAMES)
def test_a_number_only_in_a_file_name_is_still_reported_as_absent(name: str) -> None:
    message = build_user_message(
        ["Budget was 2025 dollars."], evidence_text(sections(name, "Budget grew.")), ""
    )
    assert "appear nowhere" in message and "2025" in message.split("appear nowhere")[1]


def test_a_number_in_the_passage_text_is_not_reported() -> None:
    message = build_user_message(
        ["Budget was 2025 dollars."],
        evidence_text(sections("x.txt", "Budget was 2025 dollars.")),
        "",
    )
    assert "appear nowhere" not in message


# --- D. citations -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (
            "Receipts are required. [source_1]\nWrong one is here. [source_2]",
            "Receipts are required. [source_1]",
        ),
        (
            "Wrong one is here.\n[source_1]\nReceipts are required.\n[source_2]",
            "Receipts are required.\n[source_2]",
        ),
        ("Wrong one is here. [source_1][source_2]", ""),
        (
            "Receipts are required. [source_1] [source_2]\nWrong one is here.",
            "Receipts are required. [source_1] [source_2]",
        ),
        (
            "[source_1]\nReceipts are required.\n\nWrong one is here.\n[source_2]",
            "[source_1]\nReceipts are required.",
        ),
    ],
)
async def test_a_marker_stays_with_surviving_text_and_goes_with_removed_text(
    answer: str, expected: str
) -> None:
    result = await run(answer, "Wrong")
    assert result.text == expected


def test_surviving_markers_are_renumbered_in_first_reference_order_and_unused_sources_drop() -> (
    None
):
    class C:
        def __init__(self, name: str) -> None:
            self.name = name

    survived = "First fact is here. [1]\nThird fact is here. [3]"  # the text citing [2] was removed
    text, kept = normalize_answer_citations(survived, [C("a"), C("b"), C("c")])
    assert text == "First fact is here. [1]\nThird fact is here. [2]"
    assert [c.name for c in kept] == ["a", "c"]


# --- E. safe fallback and fail-open -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "answer",
    [
        "Receipts are required.\n\n## Details\n- Wrong one is here.",
    ],
)
async def test_a_partly_supported_answer_is_never_replaced_by_the_fallback(answer: str) -> None:
    result = await run(answer, "Wrong")
    assert result.text.strip() and not result.nothing_left


@pytest.mark.parametrize(
    "failure",
    [TimeoutError(), RuntimeError("provider down"), ConnectionError("down"), ValueError("bad")],
)
async def test_a_failing_check_leaves_every_answer_exactly_as_written(failure: Exception) -> None:
    answer = f"{LEAD}\n- Wrong one is here.\n[source_1]"
    result = await enforce_claims(AsyncMock(side_effect=failure), answer, EVIDENCE, "q")
    assert result.text == answer and result.removed == 0 and not result.checked


@pytest.mark.parametrize(
    "raw", ["not json", "[]", '{"unsupported": "S1"}', '{"unsupported": ["S99"]}', "{}"]
)
async def test_an_unusable_reply_leaves_the_answer_as_written(raw: str) -> None:
    answer = f"{LEAD}\n- Wrong one is here."
    result = await enforce_claims(AsyncMock(return_value=raw), answer, EVIDENCE, "q")
    assert result.text == answer and not result.checked


async def test_a_slow_check_times_out_and_leaves_the_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    async def slow(*_: str) -> str:
        await asyncio.sleep(1)
        return '{"unsupported": ["S1"]}'

    monkeypatch.setattr(cc, "CLAIM_CHECK_TIMEOUT_SECONDS", 0.01)
    result = await enforce_claims(slow, "Receipts are required.", EVIDENCE, "q")
    assert result.text == "Receipts are required." and not result.checked


@pytest.mark.parametrize("evidence", ["", "   \n"])
async def test_empty_evidence_means_no_check_and_no_change(evidence: str) -> None:
    called = AsyncMock(return_value='{"unsupported": ["S1"]}')
    result = await enforce_claims(called, "Receipts are required.", evidence, "q")
    assert result.text == "Receipts are required." and not result.checked
    called.assert_not_called()


async def test_only_the_first_evidence_budget_is_sent_but_the_answer_is_still_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cc, "MAX_EVIDENCE_CHARS", 40)
    seen: list[str] = []

    async def spy(_: str, user: str) -> str:
        seen.append(user)
        return '{"unsupported": ["S2"]}'

    result = await enforce_claims(spy, "Receipts are required.\nWrong one is here.", EVIDENCE, "q")
    assert result.text == "Receipts are required."
    assert EVIDENCE[:40] in seen[0] and EVIDENCE[:60] not in seen[0]


def test_framing_agrees_with_lead_in_detection_about_list_prefixes() -> None:
    for text in (
        "Key findings:",
        "- Key findings:",
        "1. Next steps:",
        "**Key findings:**",
        "* Key findings:",
    ):
        assert is_framing(text), text
    for text in ("According to the handbook:", "- According to the handbook:"):
        assert not is_framing(text), text


# --- observability: the trace tells the truth after every kind of removal ---------------------------------


@pytest.mark.parametrize(
    ("answer", "flagged_fragment"),
    [
        ("Receipts are required.\nWrong one is here.\nThe north gate is priority one.", "Wrong"),
        (f"{LEAD}\n- Wrong one is here.\n- Wrong two is here.", "Wrong"),
        ("Here is what I found today:\n- Wrong one is here.\n[source_1]", "Wrong"),
        ("## Details\n\nWrong one is here.\n\nWrong two is here.", "Wrong"),
        ("Receipts are required. [source_1]\nWrong one is here. [source_2]", "Wrong"),
    ],
)
async def test_the_reported_count_matches_what_the_trace_observes(
    answer: str, flagged_fragment: str
) -> None:
    flagged = labels(answer, flagged_fragment)
    result = await run(answer, flagged_fragment)
    seen = attribute_removals(answer, split_statements(answer), flagged, result.text)
    assert not seen["flagged_not_removed"]
    if not seen["uncertain"] and not seen["unattributed_change"]:
        assert result.removed == len(seen["removed"]) + len(seen["collateral_removed"])


async def test_a_closed_lead_in_is_reported_as_an_unattributed_change_not_as_a_removal() -> None:
    answer = f"{LEAD}\n- Wrong one is here."
    flagged = labels(answer, "Wrong")
    result = await run(answer, "Wrong")
    seen = attribute_removals(answer, split_statements(answer), flagged, result.text)
    assert seen["unattributed_change"] and not seen["collateral_removed"]


async def test_repeated_statements_are_reported_as_uncertain_not_as_removed() -> None:
    answer = "Receipts are required.\nWrong one is here.\nWrong one is here."
    reply = json.dumps({"unsupported": ["S2"]})
    result = await enforce_claims(AsyncMock(return_value=reply), answer, EVIDENCE, "q")
    seen = attribute_removals(answer, split_statements(answer), ["S2"], result.text)
    assert seen["uncertain"] and not seen["removed"]


# --- invariants over generated answers ----------------------------------------------------------------------

BLOCKS = {
    "paragraph": "Receipts are required.",
    "lead_list": f"{LEAD}\n- Wrong one is here.\n- Wrong two is here.",
    "lead_blank_list": f"{LEAD}\n\n- Wrong three is here.\n- Wrong four is here.",
    "heading": "## Details\n- Wrong five is here.",
    "numbered": "Steps for these items:\n1. Wrong six is here.\n2. Wrong seven is here.",
    "cited": "The north gate is priority one. [source_1]\nWrong eight is here. [source_1]",
    "inline_lead": f"{LEAD} 1. Wrong nine is here. 2. Wrong ten is here.\n- Receipts are required.",
    "lead_para": f"{LEAD}\n\nWrong eleven is here.",
}


@pytest.mark.parametrize(
    "names", [c for r in (1, 2, 3) for c in itertools.combinations(BLOCKS, r)], ids="+".join
)
async def test_no_flagged_text_survives_and_no_supported_paragraph_is_lost(
    names: tuple[str, ...],
) -> None:
    answer = "\n\n".join(BLOCKS[n] for n in names)
    result = await run(answer, "Wrong")
    assert "Wrong" not in result.text
    for supported in ("Receipts are required.", "The north gate is priority one."):
        if supported in answer:
            assert supported in result.text
    if result.text.strip():  # a removal never leaves an introduction with nothing after it
        assert not result.text.rstrip().endswith((":", ";"))
    seen = attribute_removals(
        answer, split_statements(answer), labels(answer, "Wrong"), result.text
    )
    assert not seen["flagged_not_removed"]
    if not seen[
        "unattributed_change"
    ]:  # a closed lead-in is a documented change the trace cannot attribute
        assert not seen["uncertain"]


# --- P2-1: a lead-in sharing its line with removed list items, while later list lines survive ---------------


@pytest.mark.parametrize(
    ("answer", "expected", "removed"),
    [
        (  # the lead-in is structural, but its list survives: lead-in and colon stay
            "Try the following: 1. Check the setting. 2. Ensure the cable is connected to the TV.\n- Reboot it [1].",
            "Try the following:\n- Reboot it [1].",
            2,
        ),
        (
            f"{LEAD} 1. Wrong a is here.\n- Receipts are required.",
            f"{LEAD}\n- Receipts are required.",
            1,
        ),
        (
            "Refunds take 30 days for these items; 1. Wrong a is here.\n- Receipts are required.",
            "Refunds take 30 days for these items;\n- Receipts are required.",
            1,
        ),
        (
            f"{LEAD} 1. Wrong a is here. 2. Wrong b is here.\n- Receipts are required. [source_1]",
            f"{LEAD}\n- Receipts are required. [source_1]",
            2,
        ),
        (
            f"{LEAD} 1. Wrong a is here.\n  - Receipts are required.\n  - Wrong b is here.",
            f"{LEAD}\n  - Receipts are required.",
            2,
        ),
        (
            f"{LEAD} 1. Wrong a is here. 2. Wrong b is here.",
            CLOSED,
            2,
        ),  # nothing follows: closed as before
        (
            f"{LEAD} 1. Wrong a is here.\n\nReceipts are required.",
            f"{CLOSED}\n\nReceipts are required.",
            1,
        ),
        (
            "Try the following: 1. Wrong a is here. 2. Wrong b is here.",
            "",
            3,
        ),  # structural, nothing survives
    ],
)
async def test_an_inline_lead_in_keeps_its_colon_while_a_later_list_line_survives(
    answer: str, expected: str, removed: int
) -> None:
    flagged = ("Wrong", "Check the setting", "Ensure the cable")
    result = await run(answer, *flagged)
    assert result.text == expected
    assert result.removed == removed
    assert result.nothing_left == (expected == "")


# --- P2-2: a lead-in introduces the plain paragraph after it, not only a list ------------------------------


@pytest.mark.parametrize("gap", ["\n\n", "\n"])
@pytest.mark.parametrize("mark", [":", ";"])
async def test_a_lead_in_is_closed_when_the_paragraph_it_introduced_is_removed(
    gap: str, mark: str
) -> None:
    result = await run(
        f"Refunds take 30 days for these items{mark}{gap}Wrong claim is here.", "Wrong"
    )
    assert result.text == CLOSED
    assert result.removed == 1 and not result.nothing_left


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (
            f"{LEAD}\n\nReceipts are required.",
            f"{LEAD}\n\nReceipts are required.",
        ),  # paragraph survives
        (
            f"{LEAD}\n\nReceipts are required.\nWrong claim is here.",
            f"{LEAD}\n\nReceipts are required.",
        ),
        (
            f"{LEAD}\n\nWrong claim is here.\n\nThe north gate is priority one.",
            f"{CLOSED}\n\nThe north gate is priority one.",
        ),
        (
            f"{LEAD}\n\nWrong claim is here. [source_1]\n\nReceipts are required. [source_2]",
            f"{CLOSED}\n\nReceipts are required. [source_2]",
        ),
        (
            f"{LEAD}\n\nWrong claim is here.\n[source_1]\n\nReceipts are required.",
            f"{CLOSED}\n\nReceipts are required.",
        ),
        (
            "Receipts are required.\n\nHere is what I found today:\n\nWrong claim is here.",
            "Receipts are required.",
        ),
        (
            "Receipts are required.\n\nHere is what I found today;\nWrong claim is here.",
            "Receipts are required.",
        ),
        ("Here is what I found today:\n\nWrong claim is here.", ""),
        (
            f"{LEAD}\n\nWrong claim is here.\n\n## Details\nReceipts are required.",
            f"{CLOSED}\n\n## Details\nReceipts are required.",
        ),
        (
            f"- {LEAD}\n\n  Wrong claim is here.\n- Receipts are required.",
            f"- {CLOSED}\n\n- Receipts are required.",
        ),
    ],
)
async def test_the_paragraph_a_lead_in_introduced_is_handled_like_a_list(
    answer: str, expected: str
) -> None:
    result = await run(answer, "Wrong")
    assert result.text == expected
    assert result.nothing_left == (expected == "")


async def test_a_closed_paragraph_lead_in_is_traced_as_an_unattributed_change_with_the_true_count() -> (
    None
):
    answer = f"{LEAD}\n\nWrong claim is here.\n\nReceipts are required."
    result = await run(answer, "Wrong")
    seen = attribute_removals(
        answer, split_statements(answer), labels(answer, "Wrong"), result.text
    )
    assert result.removed == 1 and seen["unattributed_change"] and not seen["collateral_removed"]
    assert not seen["flagged_not_removed"]


async def test_a_lead_in_before_a_heading_is_not_given_the_next_sections_text() -> None:
    answer = f"{LEAD}\n\n## Details\n- Wrong one is here.\n- Receipts are required."
    assert (await run(answer, "Wrong")).text == f"{LEAD}\n\n## Details\n- Receipts are required."


async def test_a_lead_in_never_adopts_a_following_heading_section_as_its_paragraph() -> None:
    """Section boundaries: the heading and its list are judged by the heading rules, the lead-in is left as written."""
    result = await run(f"{LEAD}\n\n## Details\n- Wrong one is here.", "Wrong")
    assert (
        result.text == LEAD and result.removed == 2
    )  # the empty heading goes; the earlier lead-in is not touched
