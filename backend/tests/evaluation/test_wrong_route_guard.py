"""A "not found" that comes from the file-name lookup is not a correct answer to a content question (KI-025)."""

from __future__ import annotations

from typing import Any

import pytest

from app.agents.tool_rag.finalization import FILE_NOT_FOUND_TEXT
from evaluation.rag_eval import runner
from evaluation.rag_eval.runner import judge_row


def row(reply: str | None) -> dict[str, Any]:
    return {
        "reply": reply,
        "error": None,
        "answer": None,
        "evidence": None,
        "clean": {"clean": False, "citations": 0, "forbidden_present": []},
        "refusal": None,
    }


CASE = {"expected_behavior": "not_found", "question": "What is the VAT registration number?"}


@pytest.fixture
def judged(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    async def fake(settings: object, case: dict[str, Any], answer: str) -> dict[str, str]:
        calls.append(answer)
        return {"verdict": "ok", "reason": "fake"}

    monkeypatch.setattr(runner, "judge", fake)
    return calls


async def test_the_file_lookup_failure_text_fails_a_not_found_case_without_calling_the_judge(
    judged: list[str],
):
    result = await judge_row(object(), CASE, row(FILE_NOT_FOUND_TEXT))  # type: ignore[arg-type]
    assert result["refusal"] == {
        "ok": False,
        "reason": "wrong route: file-name lookup, no content search",
    }
    assert result["overall"] == {"pass": False}
    assert judged == []


async def test_a_real_not_in_the_files_reply_still_goes_to_the_judge(judged: list[str]):
    reply = "The invoice shows the VAT amount but no registration number."
    result = await judge_row(object(), CASE, row(reply))  # type: ignore[arg-type]
    assert result["refusal"]["ok"] is True
    assert judged == [reply]


async def test_an_empty_reply_still_fails_as_no_answer(judged: list[str]):
    result = await judge_row(object(), CASE, row(""))  # type: ignore[arg-type]
    assert result["refusal"] == {"ok": False, "reason": "no answer"}
    assert judged == []


async def test_a_case_that_names_a_missing_file_may_get_the_file_lookup_failure_text(
    judged: list[str],
):
    case = {**CASE, "names_a_file": True}
    result = await judge_row(object(), case, row(FILE_NOT_FOUND_TEXT))  # type: ignore[arg-type]
    assert result["refusal"]["ok"] is True  # the judge decides, as for any other reply
    assert judged == [FILE_NOT_FOUND_TEXT]
