"""Rule-built absence controls for the claim checker in ``planted_claims`` (free; no model is called).

``absence_supported`` is a true statement about what the documents lack and must be spared; ``absence_false`` says
the documents do not state what they do state and must be flagged. The paid run is prepared, not authorized.
"""

from evaluation.rag_eval import planted_claims as pc

CASE = {
    "id": "t01",
    "split": "dev",
    "question": "How many days of leave?",
    "expected_behavior": "answer",
    "computed": False,
    "category": "plain_fact",
    "reference_answer": "Annual leave is 22 working days.",
    "expected_files": ["v1/handbook.txt"],
}
TEXTS = {"v1/handbook.txt": "Annual leave is 22 working days per year."}


def items(*cases: dict) -> list[dict]:
    return pc.build_items({"cases": list(cases)}, TEXTS)


def test_each_answerable_case_gets_both_absence_variants_built_from_its_clean_answer() -> None:
    (item,) = items(CASE)
    variants = item["variants"]
    assert variants["clean"] == CASE["reference_answer"]
    assert variants["absence_supported"] == f"{CASE['reference_answer']} {pc.ABSENCE_SUPPORTED}"
    assert variants["absence_false"] == f"{CASE['reference_answer']} {pc.ABSENCE_FALSE}"


def test_the_two_absence_sentences_differ_and_assert_nothing_with_a_number() -> None:
    assert pc.ABSENCE_SUPPORTED != pc.ABSENCE_FALSE
    assert not any(ch.isdigit() for ch in pc.ABSENCE_SUPPORTED + pc.ABSENCE_FALSE)


def test_ids_filter_keeps_only_the_named_cases() -> None:
    other = {**CASE, "id": "t02"}
    kept = pc.select_ids(items(CASE, other), ["t02"])
    assert [i["id"] for i in kept] == ["t02"]
    assert [i["id"] for i in pc.select_ids(items(CASE, other), None)] == ["t01", "t02"]


def test_an_unknown_id_is_an_error_not_a_silently_smaller_paid_run() -> None:
    import pytest

    with pytest.raises(SystemExit, match="t99"):
        pc.select_ids(items(CASE), ["t01", "t99"])
