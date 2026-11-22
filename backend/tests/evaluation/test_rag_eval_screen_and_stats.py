"""The unseen-value screen (a screen, not a verdict) and the comparison statistics, on hand-made values."""

from typing import Any

import pytest

from evaluation.rag_eval.screen import screen
from evaluation.rag_eval.stats import (
    bootstrap_percentile,
    exact_sign_test,
    paired_comparison,
    percentile,
    repeat_stability,
)

SOURCES = [
    "Annual leave is 22 working days per calendar year. Contact Priya Nair about ticket INC-204, "
    "opened on 5 March 2026. A backup takes 2 hours. The budget is 1,300,000. We had five incidents. "
    "The file is employee_handbook.txt. The upload limit is 2 GB.",
    "How many days of leave?",
]


def flagged(reply: str, **kw: Any) -> list[str]:
    return list(screen(reply, SOURCES, **kw).flagged)


# ---- the screen ----------------------------------------------------------------------------------------


def test_values_found_in_a_source_are_not_flagged() -> None:
    assert (
        flagged("Employees get 22 working days. Ask Priya Nair, see employee_handbook.txt.") == []
    )


def test_an_unseen_number_name_identifier_and_date_are_each_flagged() -> None:
    assert flagged("You get 24 days.") == ["number:24"]
    assert flagged("Ask Zorbax about it.") == ["name:zorbax"]
    assert flagged("See ticket INC-999.") == ["id:inc-999"]
    assert flagged("It closed on 2026-04-01.") == ["date:2026-4-1"]


def test_reformatted_dates_number_formats_number_words_and_conversions_are_allowed() -> None:
    assert flagged("It opened on March 5, 2026, as INC-204.") == []
    assert flagged("It opened on 2026-03-05.") == []
    assert flagged("The budget is 1300000 (1.3 million).") == []  # separators and scales
    assert flagged("There were 5 incidents.") == []  # a number word in the source allows the digit
    assert flagged("A backup takes 120 minutes.") == []  # 2 hours
    assert flagged("The limit is 2000 MB.") == []  # 2 GB
    assert flagged("A backup takes 90 minutes.") == ["number:90"]  # not a conversion of anything


def test_list_numbers_and_sentence_initial_capitals_are_not_values() -> None:
    assert flagged("1. First point\n2) Second point\nThe answer follows.") == []
    assert flagged("Apparently so. Leave is 22 days.") == []


def test_a_computed_case_allows_every_number_but_not_other_values() -> None:
    assert flagged("The total is 99 days.", computed=True) == []
    assert flagged("Ask Zorbax, total 99.", computed=True) == ["name:zorbax"]


def test_an_impossible_date_is_flagged_even_if_its_parts_appear_in_a_source() -> None:
    assert flagged("It happened on 31 February 2026.") == ["date:2026-2-31"]


def test_blind_spots_are_real_a_wrong_value_that_appears_elsewhere_is_not_flagged() -> None:
    """Documented limit: the screen only asks whether a value occurs in the sources, not where."""
    assert flagged("Leave is 2 days.") == []  # 2 occurs (in "2 hours")
    assert flagged("The negation is not caught: leave is not 22 days.") == []


# ---- statistics -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("only_a", "only_b", "p"),
    [(0, 0, 1.0), (5, 0, 0.0625), (3, 1, 0.625), (4, 4, 1.0), (0, 10, 0.002)],
)
def test_the_exact_test_matches_hand_computed_binomial_values(
    only_a: int, only_b: int, p: float
) -> None:
    # 5/0: 2 * (1/32) = 0.0625.  3/1: 2 * (1+4)/16 = 0.625.  4/4: 2 * 163/256 > 1, capped at 1.
    # 0/10: 2 * 1/1024 = 0.00195.
    assert round(exact_sign_test(only_a, only_b), 3) == round(p, 3)


def rows(passes: list[bool | None], prefix: str = "c") -> list[dict[str, Any]]:
    return [
        {"id": f"{prefix}{i}", "overall": None if p is None else {"pass": p}}
        for i, p in enumerate(passes)
    ]


def passed(row: dict[str, Any]) -> bool | None:
    return None if row["overall"] is None else bool(row["overall"]["pass"])


def test_the_paired_comparison_counts_only_the_cases_that_differ() -> None:
    a = rows([True, True, False, False, True])
    b = rows([True, False, True, True, True])
    result = paired_comparison(a, b, passed)
    assert (result["both"], result["neither"], result["only_a"], result["only_b"]) == (2, 0, 1, 2)
    assert result["p_value"] == 1.0  # 2 * (1 + 3) / 8 = 1.0: three differences prove nothing
    assert result["excluded"] == 0


def test_a_comparison_with_different_cases_or_repeated_ids_refuses_to_run() -> None:
    with pytest.raises(ValueError, match="different cases"):
        paired_comparison(rows([True, False]), rows([True, False, True]), passed)
    with pytest.raises(ValueError, match="more than once"):
        paired_comparison(rows([True]) + rows([False]), rows([True]), passed)
    shifted = [{"id": "other", "overall": {"pass": True}}, *rows([True])[1:]]
    with pytest.raises(ValueError, match="different cases"):
        paired_comparison(rows([True, True]), shifted, passed)


def test_a_case_without_a_value_in_one_run_is_excluded_not_counted_as_a_failure() -> None:
    result = paired_comparison(rows([True, None, False]), rows([False, True, False]), passed)
    assert result["excluded"] == 1 and (result["only_a"], result["only_b"], result["neither"]) == (
        1,
        0,
        1,
    )


def test_repeat_statistics_give_pass_rate_flip_rate_and_the_flaky_share() -> None:
    runs = [
        rows([True, True, False, False]),
        rows([True, False, False, True]),
        rows([True, True, False, True]),
    ]
    result = repeat_stability(runs, passed)
    assert result["per_case"] == {
        "c0": {"pass_rate": 1.0, "flip_rate": 0.0},
        "c1": {"pass_rate": 0.667, "flip_rate": 1.0},  # T F T: two flips in two steps
        "c2": {"pass_rate": 0.0, "flip_rate": 0.0},
        "c3": {"pass_rate": 0.667, "flip_rate": 0.5},  # F T T: one flip in two steps
    }
    assert (result["flaky_cases"], result["flaky_share"]) == (2, 0.5)


def test_repeat_statistics_need_two_repeats_of_the_same_cases() -> None:
    with pytest.raises(ValueError, match="at least two"):
        repeat_stability([rows([True])], passed)
    with pytest.raises(ValueError, match="different cases"):
        repeat_stability([rows([True]), rows([True, False])], passed)


def test_the_percentile_rule_is_the_one_summarise_always_used() -> None:
    values = [float(i) for i in range(1, 11)]
    assert (percentile(values, 0.5), percentile(values, 0.9), percentile([], 0.5)) == (
        6.0,
        10.0,
        None,
    )


def test_the_bootstrap_interval_is_repeatable_and_collapses_for_equal_values() -> None:
    values = [float(i) for i in range(1, 21)]
    first = bootstrap_percentile(values, 0.5, seed=7)
    assert first == bootstrap_percentile(values, 0.5, seed=7)
    assert first is not None and first[0] <= percentile(values, 0.5) <= first[1]  # type: ignore[operator]
    assert bootstrap_percentile([5.0, 5.0, 5.0], 0.9) == (5.0, 5.0)
    assert bootstrap_percentile([5.0], 0.5) is None


# ---- fixes from the review ---------------------------------------------------------------------------------


def test_the_applications_citation_markers_and_sources_line_are_not_values() -> None:
    assert flagged("You get 22 days [2][3].") == []
    assert (
        flagged("Leave is 22 days.\n\nSources consulted: employee_handbook.txt [1]; other.txt [2]")
        == []
    )


def test_names_are_seen_through_markup_and_after_a_colon() -> None:
    for reply in (
        "The vendor is **Zorbax**.",
        "Vendor: Zorbax",
        "It is (Zorbax).",
        'Called "Zorbax".',
    ):
        assert flagged(reply) == ["name:zorbax"], reply


def test_the_products_own_words_in_a_refusal_are_not_names() -> None:
    assert flagged("I could not find that in your Google Drive Files.") == []
