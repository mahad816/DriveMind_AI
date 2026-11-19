"""Scoring decides every reported number, so each stage and the interval maths are pinned here."""

import pytest

from evaluation.rag_eval.runner import overall, prepare
from evaluation.rag_eval.score import (
    Observed,
    answer_score,
    clean_score,
    evidence_score,
    rates,
    summarise,
    wilson,
)


def need(value):
    assert value is not None
    return value


def case(**kw):
    base = {
        "expected_behavior": "answer",
        "expected_files": ["synthetic/a.txt"],
        "citation_mode": "all",
        "must_include": [["22"]],
        "must_not_include": ["24 days"],
        "category": "x",
    }
    return {**base, **kw}


def test_wilson_interval_known_values():
    lo, hi = wilson(90, 100)
    assert (round(lo, 3), round(hi, 3)) == (0.826, 0.945)
    assert wilson(0, 0) == (0.0, 0.0)
    lo, hi = wilson(10, 10)
    assert hi == 1.0 and 0.70 < lo < 0.75  # 10/10 is not "100% certain"


def test_ninety_cases_leave_roughly_six_points_of_margin():
    lo, hi = wilson(81, 90)  # 90% observed
    assert 0.05 < (hi - lo) / 2 < 0.07


def test_evidence_all_vs_any_and_noise():
    seen = Observed("x", ("synthetic/a.txt", "public/z.pdf"))
    assert need(evidence_score(case(), seen)) == {
        "found": True,
        "expected": 1,
        "hit": 1,
        "noise_files": 1,
    }
    two = case(expected_files=["synthetic/a.txt", "synthetic/b.txt"])
    assert need(evidence_score(two, seen))["found"] is False
    assert need(evidence_score({**two, "citation_mode": "any"}, seen))["found"] is True
    assert evidence_score(case(expected_behavior="not_found", expected_files=[]), seen) is None


def test_answer_needs_every_fact_and_no_forbidden_claim():
    assert need(answer_score(case(), Observed("You get 22 working days.", ())))["correct"]
    assert not need(answer_score(case(), Observed("You get 21 days.", ())))["correct"]
    wrong = need(answer_score(case(), Observed("22 days, or maybe 24 days.", ())))
    assert not wrong["correct"] and wrong["forbidden_present"] == ["24 days"]
    assert not need(answer_score(case(), Observed("22", (), error="ChatError")))["correct"]


def test_number_matching_is_not_fooled_by_longer_numbers():
    assert not need(answer_score(case(), Observed("It is 122 days.", ())))["correct"]


def test_clean_means_no_citation_and_no_forbidden_claim_on_a_refusal():
    refusal = case(expected_behavior="not_found", expected_files=[], must_not_include=["500,000"])
    assert need(clean_score(refusal, Observed("I cannot find that.", ())))["clean"]
    assert not need(clean_score(refusal, Observed("I cannot find that.", ("synthetic/a.txt",))))[
        "clean"
    ]
    assert not need(clean_score(refusal, Observed("It is 500,000.", ())))["clean"]
    assert clean_score(case(), Observed("x", ())) is None


def test_overall_requires_all_applicable_stages():
    good = {
        "error": None,
        "answer": {"correct": True},
        "evidence": {"found": True},
        "refusal": None,
        "clean": None,
    }
    assert overall(good)
    assert not overall({**good, "evidence": {"found": False}})
    assert not overall({**good, "error": "ChatError"})
    refused = {
        "error": None,
        "answer": None,
        "evidence": None,
        "refusal": {"ok": True},
        "clean": {"clean": False},
    }
    assert not overall(refused)  # declined but still attached a citation


def test_rates_skip_inapplicable_rows_and_summary_splits_by_category():
    rows = [
        {"category": "a", "evidence": {"found": True}, "overall": {"pass": True}, "latency_s": 1.0},
        {"category": "a", "evidence": None, "overall": {"pass": False}, "latency_s": 3.0},
        {
            "category": "b",
            "evidence": {"found": False},
            "overall": {"pass": True},
            "latency_s": 2.0,
        },
    ]
    assert rates(rows, "evidence", "found")["n"] == 2
    summary = summarise(rows)
    assert summary["by_category"]["a"]["passed"] == 1 and summary["by_category"]["b"]["rate"] == 1.0
    assert summary["latency_s"]["max"] == 3.0


def test_inventory_placeholder_is_filled_with_the_real_corpus_size():
    assert prepare({"question": "I have {TOTAL_FILES} files?"}, 55) == "I have 55 files?"
    assert prepare({"question": "How many?"}, 55) == "How many?"


@pytest.mark.parametrize("n,k", [(10, 5), (90, 81), (31, 28)])
def test_interval_always_contains_the_observed_rate(n, k):
    lo, hi = wilson(k, n)
    assert lo <= k / n <= hi
