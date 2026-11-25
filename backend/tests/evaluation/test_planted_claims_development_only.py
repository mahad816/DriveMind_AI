"""The checker controls and the prepared validation (ticket backend-stabilization/03) use development cases only.

Free tests, no model. ``planted_claims`` must fail closed: a regression or held-out case is never built into a
control item and is never accepted through ``--ids``; the ids written in the ticket are checked against the
committed case files, not against a copy kept in the test.
"""

import re
from pathlib import Path

import pytest

from evaluation.rag_eval import planted_claims as pc
from evaluation.rag_eval.dataset import HELD_OUT_SPLIT, corpus_texts, load_cases, load_many
from evaluation.rag_eval.corpus import synthetic_files
from evaluation.rag_eval.pools import pool_of

TICKET = (
    Path(__file__).resolve().parents[3]
    / "docs/tickets/backend-stabilization/03-bounded-real-model-validation.md"
)
TEXTS = {"v1/handbook.txt": "Annual leave is 22 working days per year."}


def case(case_id: str, split: str | None) -> dict:
    row = {
        "id": case_id,
        "question": "How many days of leave?",
        "expected_behavior": "answer",
        "computed": False,
        "category": "single_fact",
        "reference_answer": "Annual leave is 22 working days.",
        "expected_files": ["v1/handbook.txt"],
    }
    if split is not None:
        row["split"] = split
    return row


def test_only_development_cases_become_control_items() -> None:
    items = pc.build_items(
        {"cases": [case("d1", "dev"), case("r1", "test"), case("h1", HELD_OUT_SPLIT)]}, TEXTS
    )
    assert [i["id"] for i in items] == ["d1"]


def test_a_case_with_no_split_is_left_out_not_assumed_to_be_development() -> None:
    assert pc.build_items({"cases": [case("n1", None)]}, TEXTS) == []


def test_computed_controls_are_development_only_too() -> None:
    computed = {**case("c1", "test"), "computed": True}
    dev_computed = {**case("c2", "dev"), "computed": True}
    items = pc.build_items({"cases": [computed, dev_computed]}, TEXTS)
    assert [i["id"] for i in items] == ["c2"]


def test_ids_naming_a_regression_case_are_refused_before_anything_is_spent() -> None:
    items = pc.build_items({"cases": [case("d1", "dev"), case("r1", "test")]}, TEXTS)
    with pytest.raises(SystemExit, match="r1"):
        pc.select_ids(items, ["d1", "r1"])


def _ticket_ids(pattern: str) -> list[str]:
    match = re.search(pattern, TICKET.read_text(encoding="utf-8"))
    assert match, f"ticket 03 no longer shows {pattern!r}"
    return match.group(1).split()


def test_the_ticket_control_ids_are_ten_distinct_development_cases_in_the_default_dataset() -> None:
    ids = _ticket_ids(r"planted_claims --model \S+ --cap \S+ \\\n\s+--ids ([a-z0-9 ]+?) \\?\n")
    assert len(ids) == 10 and len(set(ids)) == 10
    dataset = load_cases()
    by_id = {c["id"]: c for c in dataset["cases"]}
    assert all(i in by_id for i in ids)
    assert {pool_of(by_id[i]) for i in ids} == {"development"}
    built = pc.build_items(dataset, corpus_texts(synthetic_files()))
    assert set(ids) <= {i["id"] for i in built}, "an id in the ticket would be refused by the run"


def test_the_ticket_end_to_end_ids_are_fourteen_distinct_development_cases() -> None:
    ids = _ticket_ids(r"IDS=\(([a-z0-9 ]+)\)")
    assert len(ids) == 14 and len(set(ids)) == 14
    files = [
        "rag_v2_cases.json",
        "rag_v2_messy_cases.json",
        "rag_v2_identifier_cases.json",
        "rag_v3_dev_cases.json",
    ]
    cases = load_many(files)["cases"]  # refuses any file holding held-out cases
    splits = {c["id"]: c["split"] for c in cases}
    assert all(i in splits for i in ids)
    assert {splits[i] for i in ids} == {"dev"}
    all_ids = [c["id"] for c in cases]
    assert all_ids.count(ids[0]) == 1 and all(all_ids.count(i) == 1 for i in ids)


def test_the_documented_selection_never_names_a_held_out_case() -> None:
    cases = load_many(["rag_v2_cases.json"])["cases"]
    assert all(c["split"] != HELD_OUT_SPLIT for c in cases)
