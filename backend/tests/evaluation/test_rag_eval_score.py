"""Scoring decides every reported number, so each stage and the interval maths are pinned here."""

import pytest

from evaluation.rag_eval.runner import describe_error, overall, prepare, prepare_case, score_row
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


def test_inventory_placeholder_is_filled_in_question_and_expected_facts():
    assert prepare("I have {TOTAL_FILES} files?", 55) == "I have 55 files?"
    inventory = case(
        question="How many files?", must_include=[["{TOTAL_FILES}"]], expected_behavior="inventory"
    )
    ready = prepare_case(inventory, 55)
    assert ready["must_include"] == [["55"]] and inventory["must_include"] == [
        ["{TOTAL_FILES}"]
    ]  # original untouched
    assert need(answer_score(ready, Observed("Indexed files: 55.", ())))["correct"]


def test_score_row_recomputes_every_deterministic_stage_from_the_stored_reply():
    stored = {"reply": "You get 22 days.", "cited_files": ["synthetic/a.txt"], "error": None}
    row = score_row(case(), dict(stored))
    assert row["evidence"]["found"] and row["answer"]["correct"] and row["refusal"] is None
    # same stored reply, stricter gold: the verdict follows the gold, nothing is re-asked
    row = score_row(case(expected_files=["synthetic/b.txt"]), dict(stored))
    assert not row["evidence"]["found"]


@pytest.mark.parametrize("n,k", [(10, 5), (90, 81), (31, 28)])
def test_interval_always_contains_the_observed_rate(n, k):
    lo, hi = wilson(k, n)
    assert lo <= k / n <= hi


def test_describe_error_keeps_class_names_only():
    try:
        try:
            raise TimeoutError("secret-looking text sk-123")
        except TimeoutError as inner:
            raise RuntimeError("outer secret") from inner
    except RuntimeError as exc:
        text = describe_error(exc)
    assert text == "RuntimeError<-TimeoutError" and "secret" not in text


# --- the "partial" behaviour: known part checked by text, missing part by the judge --------------

PARTIAL = {
    "expected_behavior": "partial",
    "expected_files": ["synthetic/faq_support.txt"],
    "citation_mode": "all",
    "must_include": [["299"]],
    "must_not_include": [],
}


def test_partial_case_is_scored_for_evidence_and_known_fact_but_not_for_citation_noise():
    seen = Observed(
        "Premium costs 299 USD per month; no yearly price is stated.",
        ("synthetic/faq_support.txt",),
    )
    assert evidence_score(PARTIAL, seen) == {
        "found": True,
        "expected": 1,
        "hit": 1,
        "noise_files": 0,
    }
    assert need(answer_score(PARTIAL, seen))["correct"] is True
    assert clean_score(PARTIAL, seen) is None  # it is allowed, and expected, to cite its source


def test_partial_case_fails_when_the_known_part_is_missing_or_unsourced():
    refused = Observed("I could not find that.", ())
    assert need(answer_score(PARTIAL, refused))["correct"] is False
    assert need(evidence_score(PARTIAL, refused))["found"] is False


def test_partial_case_passes_only_when_the_judge_agrees_nothing_was_invented():
    row = {
        "error": None,
        "expected_behavior": "partial",
        "answer": {"correct": True},
        "evidence": {"found": True},
        "clean": None,
    }
    assert overall({**row, "refusal": {"ok": True}}) is True
    assert overall({**row, "refusal": {"ok": False}}) is False  # invented the missing part


async def test_the_judge_is_told_what_is_missing_from_the_files(monkeypatch):
    import evaluation.rag_eval.judge as judge_module
    from types import SimpleNamespace
    from typing import cast

    from app.core.config import Settings

    sent = {}

    class Reply:
        choices = [
            type(
                "C",
                (),
                {"message": type("M", (), {"content": '{"verdict": "ok", "reason": "fine"}'})},
            )
        ]

    class FakeClient:
        def __init__(self, **_):
            self.chat = type("Chat", (), {"completions": self})

        async def create(self, **kwargs):
            sent.update(kwargs)
            return Reply()

        async def close(self):
            return None

    monkeypatch.setattr(judge_module, "AsyncOpenAI", FakeClient)
    trap = {
        "question": "Price per year?",
        "expected_behavior": "partial",
        "judge_note": "Missing part: annual price.",
    }
    verdict = await judge_module.judge(
        cast(Settings, SimpleNamespace(openai_api_key="test")), trap, "299 per month."
    )
    prompt = sent["messages"][0]["content"]
    assert verdict["verdict"] == "ok"
    assert "Missing part: annual price." in prompt and "PART of the question" in prompt
