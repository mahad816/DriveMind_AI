"""Tests for file-target retrieval and routing."""

from __future__ import annotations

import pytest

from app.retrieval.filename_targets import extract_filename_targets, is_file_about_question
from app.retrieval.query_router import QueryRoute, classify_query


def test_extract_short_quoted_filename() -> None:
    assert extract_filename_targets('Tell me about "HI"') == ["HI"]


def test_is_file_about_question_with_quote() -> None:
    assert is_file_about_question('Tell me about "HI"') is True


def test_tell_me_about_hi_routes_to_file_target() -> None:
    assert classify_query('Tell me about "HI"') is QueryRoute.FILE_TARGET


def test_tell_me_about_far611_routes_to_file_target() -> None:
    assert classify_query('Tell me about "Far611"') is QueryRoute.FILE_TARGET


def test_tell_me_about_hi_with_followup_routes_to_file_target() -> None:
    q = 'Tell me about "HI" content what boy is named'
    assert classify_query(q) is QueryRoute.FILE_TARGET


def test_bare_hi_still_chitchat() -> None:
    assert classify_query("hi") is QueryRoute.CHITCHAT


@pytest.mark.parametrize(
    "question",
    [
        "how many files do I have",
        "find all resume files",
    ],
)
def test_inventory_not_file_target(question: str) -> None:
    route = classify_query(question)
    assert route is QueryRoute.FILE_INVENTORY
    assert route is not QueryRoute.FILE_TARGET
