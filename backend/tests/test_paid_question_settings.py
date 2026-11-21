"""M0-SEC ticket 05: the quota and execution-bound settings, validated together (no database)."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def make(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def test_defaults_are_accepted_and_match_the_owner_decision():
    s = make()
    assert (s.paid_question_hour_limit, s.paid_question_day_limit) == (20, 50)
    assert s.paid_question_concurrent_limit == 1
    assert (s.conversation_execution_seconds, s.conversation_generation_timeout) == (180, 120.0)
    assert s.chat_execution_seconds == 180
    assert s.paid_question_lease_seconds >= 180 + 60
    assert s.paid_question_retention_hours >= 25


def test_limits_are_configurable():
    s = make(
        paid_question_hour_limit=3, paid_question_day_limit=5, paid_question_concurrent_limit=2
    )
    assert (s.paid_question_hour_limit, s.paid_question_day_limit) == (3, 5)
    assert s.paid_question_concurrent_limit == 2


@pytest.mark.parametrize(
    "overrides",
    [
        {"paid_question_lease_seconds": 239},  # below 180 + 60
        {"paid_question_lease_seconds": 300, "conversation_execution_seconds": 300},
        {"paid_question_lease_seconds": 300, "chat_execution_seconds": 300},
        {"conversation_generation_timeout": 180.0},  # not below the execution bound
        {"conversation_generation_timeout": 121.0},  # above the generation ceiling
        {"conversation_execution_seconds": 601, "paid_question_lease_seconds": 900},
        {"paid_question_retention_hours": 24},
        {"paid_question_hour_limit": 0},
    ],
)
def test_invalid_combinations_are_rejected(overrides):
    with pytest.raises(ValidationError):
        make(**overrides)


def test_a_lease_exactly_at_the_margin_is_accepted():
    assert make(paid_question_lease_seconds=240).paid_question_lease_seconds == 240
    assert (
        make(
            conversation_execution_seconds=600, paid_question_lease_seconds=660
        ).paid_question_lease_seconds
        == 660
    )
