"""KI-035 (fixed; regression tests): the claim check can flag a statement, leave it in the answer, and still count a removal.

No network, no key, no database: the checker's model is a fake that returns a fixed JSON reply; everything else is
the real ``enforce_claims``. ``split_statements`` (the numbering the model sees) glues a list number onto the
sentence that follows it ("1. Text."), but the removal loop matches against ``sentences(line)``, which keeps the
number apart ("1.", "Text."). A flagged statement that starts with a list number is therefore never found in the
line, nothing is dropped, and the function still returns ``removed=1`` and logs ``REMOVED count=1``.

These were strict expected failures until removal was changed to work by statement index (the same units the
checker is shown). They are ordinary regression tests now. The tests state what a user would call correct: a statement the checker called unsupported is not published, and
the count (and the log line) says how many statements were really removed. The guards pin the neighbouring
behaviour a fix must keep: sentences without a list number are removed, a flagged later sentence of a numbered line
is removed, a clean check removes nothing.
"""

import json
import logging
import re
from unittest.mock import AsyncMock

import pytest

from app.agents.tool_rag.claim_check import enforce_claims, split_statements

EVIDENCE = "[policy.txt]\nAuthoritative refund policy text. Refunds take 30 days."
NUMBERED = "1. Authoritative refund policy text. Refunds take 90 days. [source_1]"
UNNUMBERED = "Authoritative refund policy text. Refunds take 90 days. [source_1]"
FIRST = "Authoritative refund policy text."


def checker(*labels: str) -> AsyncMock:
    return AsyncMock(return_value=json.dumps({"unsupported": list(labels)}))


async def test_a_flagged_numbered_statement_is_not_published() -> None:
    result = await enforce_claims(checker("S1"), NUMBERED, EVIDENCE, "question")
    assert FIRST not in result.text


async def test_the_removal_count_and_log_say_how_many_statements_really_went(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO):
        result = await enforce_claims(checker("S1"), NUMBERED, EVIDENCE, "question")
    really_gone = len(split_statements(NUMBERED)) - len(split_statements(result.text))
    logged = [int(m) for m in re.findall(r"outcome=REMOVED count=(\d+)", caplog.text)]
    assert result.removed == really_gone
    assert logged == [really_gone]


async def test_guard_a_flagged_sentence_without_a_list_number_is_removed_and_counted() -> None:
    result = await enforce_claims(checker("S2"), UNNUMBERED, EVIDENCE, "question")
    assert "90 days" not in result.text and FIRST in result.text
    assert result.removed == 1


async def test_guard_a_flagged_later_sentence_of_a_numbered_line_is_removed() -> None:
    result = await enforce_claims(checker("S2"), NUMBERED, EVIDENCE, "question")
    assert "90 days" not in result.text and FIRST in result.text
    assert result.removed == 1


async def test_guard_a_clean_check_removes_and_counts_nothing() -> None:
    result = await enforce_claims(checker(), NUMBERED, EVIDENCE, "question")
    assert result.text == NUMBERED and result.removed == 0 and result.checked is True
