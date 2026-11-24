"""A negation group in ``must_include`` ("not" or "no") accepts a contracted negation ("don’t", "isn't").

Found in the answer-quality pilot (case nep03): a correct refusal, "The documents I found don’t state that ...",
failed the deterministic answer stage because ``text.norm`` turns the typographic apostrophe into a space and the
match is whole-token, so neither "not" nor "no" was found. The correction lives in ``score.py`` for negation
groups only; ``text.contains`` / ``text.norm`` (shared by dataset validation and every other scorer) stay as they were.
"""

import pytest

from evaluation.rag_eval import text
from evaluation.rag_eval.score import Observed, answer_score, fact_recall

NEGATION = [["not", "no"]]


def premise_case(**kw):
    base = {
        "expected_behavior": "correct_premise",
        "expected_files": [],
        "must_include": NEGATION,
        "must_not_include": [],
        "category": "perturbed_unanswerable",
    }
    return {**base, **kw}


def scored(reply, **kw):
    seen = Observed(answer=reply, cited_files=(), error=None)
    return answer_score(premise_case(**kw), seen)


@pytest.mark.parametrize(
    "reply",
    [
        "The documents I found don’t state that the board rejected the plan.",  # typographic apostrophe (nep03)
        "The documents I found don't state that the board rejected the plan.",
        "The plan hasn’t been rejected; it is a draft.",
        "It wasn't rejected.",
        "I can’t confirm a rejection.",
        "They won’t decide before January.",
        "The board DOESN’T have a rejection on record.",
    ],
)
def test_a_contracted_negation_satisfies_a_negation_group(reply):
    result = scored(reply)
    assert result is not None and result["correct"] is True and result["missing"] == []


@pytest.mark.parametrize("reply", ["The board rejected the plan because of the berth depth.", ""])
def test_without_any_negation_the_group_is_still_missing(reply):
    result = scored(reply)
    assert result is not None
    assert result["correct"] is False and result["missing"] == ["not"]


def test_a_plain_not_or_no_still_passes():
    for reply in ("The plan has not been rejected.", "There is no rejection."):
        result = scored(reply)
        assert result is not None and result["correct"] is True


@pytest.mark.parametrize(
    "reply",
    [
        "The plan is nothing special.",  # "nothing" is not one of the accepted forms
        "A note was attached; we know the plan is a draft.",  # "note"/"know" contain "no" only inside a word
        "The board is rejecting it, and we cant tell why.",  # no apostrophe: not a contraction
        "On the contrary, it was rejected.",
    ],
)
def test_words_that_merely_contain_no_or_not_do_not_count(reply):
    result = scored(reply)
    assert result is not None and result["correct"] is False


def test_the_contraction_rule_applies_to_negation_groups_only():
    case = premise_case(must_include=[["300"]])
    assert answer_score(case, Observed("It isn’t 300 USD.", (), None)) == {
        "correct": True,
        "missing": [],
        "forbidden_present": [],
    }
    case = premise_case(must_include=[["500"]])
    result = answer_score(case, Observed("It isn’t 300 USD.", (), None))
    assert result is not None and result["correct"] is False  # a contraction supplies no other fact


def test_a_group_that_mixes_a_negation_with_a_fact_is_not_treated_as_a_negation_group():
    case = premise_case(must_include=[["not", "five"]])
    result = answer_score(case, Observed("It isn’t true.", (), None))
    assert result is not None and result["correct"] is False


def test_a_forbidden_claim_still_fails_a_reply_that_contains_a_negation():
    case = premise_case(must_not_include=["berth depth"])
    result = answer_score(
        case, Observed("They don’t say it, but it failed on the berth depth.", (), None)
    )
    assert result is not None
    assert result["correct"] is False and result["forbidden_present"] == ["berth depth"]


def test_an_error_still_fails_the_answer_stage():
    result = answer_score(premise_case(), Observed("It isn’t rejected.", (), "boom"))
    assert result is not None and result["correct"] is False


def test_fact_recall_agrees_with_the_answer_stage():
    seen = Observed("The documents don’t state that.", (), None)
    assert fact_recall(premise_case(), seen) == {"required": 1, "present": 1, "recall": 1.0}
    assert fact_recall(premise_case(), Observed("It was rejected.", (), None)) == {
        "required": 1,
        "present": 0,
        "recall": 0.0,
    }


def test_the_shared_text_matcher_is_unchanged():
    # Not a global normalisation change: validation and every other scorer still see the literal rule.
    assert text.contains("The documents don’t state that.", "not") is False
    assert text.contains("The documents do not state that.", "not") is True
    assert text.norm("don’t") == "don t"
