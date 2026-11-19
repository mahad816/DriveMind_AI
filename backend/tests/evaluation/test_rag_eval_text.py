"""The fact matcher decides every automatic score, so its edge cases are pinned here."""

import pytest

from evaluation.rag_eval.text import contains, norm, satisfies


@pytest.mark.parametrize(
    "answer,needle",
    [
        ("The limit is 4,200 USD per month.", "4200"),
        ("The limit is 4200 USD.", "4,200"),
        ("Availability is 99.95 percent.", "99.95"),
        ("Availability is 99.95%.", "99.95 percent"),
        ("The incident INC-219 was a bad deploy.", "inc-219"),
        ("See incident_report_2026_q2.txt for details", "incident_report_2026_q2"),
        ("Support opens at 08:00 UTC.", "08:00"),
        ("Announced on 15 September 2026.", "15 september"),
        ("Announced on September 15, 2026.", "september 15"),
        ("Total: 5 incidents.", "5"),
        ("Release 1.3 added sync.", "1.3"),
        ("Sara Khan (Engineering) was on call.", "sara khan"),
        ("A four-day week is only a proposal.", "four day"),
    ],
)
def test_matches_equivalent_surface_forms(answer, needle):
    assert contains(answer, needle)


@pytest.mark.parametrize(
    "answer,needle",
    [
        ("It took 15 minutes.", "5"),  # never inside a longer number
        ("The score was 5.5.", "5"),
        ("Patch 1.3.1 was rolled back.", "1.3"),  # a different version is not the same fact
        ("The limit is 4,200 USD.", "4,500"),
        ("Total was 970,000.", "97000"),
        ("Nothing here.", ""),
        ("INC-2190 happened.", "inc-219"),
    ],
)
def test_does_not_match_lookalikes(answer, needle):
    assert not contains(answer, needle)


def test_a_group_is_satisfied_by_any_alternative():
    assert satisfies("It lasted 3 hours 15 minutes.", ["195", "3 hours 15"])
    assert not satisfies("It lasted a while.", ["195", "3 hours 15"])


def test_norm_is_idempotent():
    text = "Meals: up to 40 USD/day (v2.0) - INC-204, 4,200 USD."
    assert norm(norm(text)) == norm(text)
