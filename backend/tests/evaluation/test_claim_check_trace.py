"""Evaluation-only claim-check diagnostics: what the draft was, what the checker saw, said and removed.

Everything is synthetic: the agent's model is a script and the checker's model is a fake ``complete_json``, so no
provider is called. The real adapter, graph and ``enforce_claims`` run underneath ``tracing_installed()``.
The diagnostics are off unless a case trace is created with ``claim_detail=True``; production never creates one.
"""

import asyncio
import json
import logging
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tool_rag import claim_check as claim_module
from app.agents.tool_rag import graph as graph_module
from app.agents.tool_rag.agent_models import AgentStepResult
from app.agents.tool_rag.agent_service import ToolRagAgentService
from app.llm.prompts import NO_EVIDENCE_ANSWER
from app.services.tool_agent_service import ToolAgentAdapter
from evaluation.rag_eval import claim_trace
from evaluation.rag_eval.trace import CaseTrace, trace_var, tracing_installed
from tests.agents.tool_rag.test_claim_check import make_settings
from tests.agents.tool_rag.test_agent_loop import InventoryDB, ScriptChat, call, chunk, file
from tests.agents.tool_rag.test_grounding_policy import SEARCH
from tests.agents.tool_rag.test_tool_execution import USER

FABRICATED = "Refunds are always approved within 90 days. [source_1]"
SUPPORTED = "Authoritative refund policy text. [source_1]"
MIXED = f"{SUPPORTED}\n{FABRICATED}"
SECRET = "Refunds are always approved within 90 days."


def fake_checker(reply: str | Exception) -> AsyncMock:
    if isinstance(reply, Exception):
        return AsyncMock(side_effect=reply)
    return AsyncMock(return_value=reply)


def flags(*labels: str) -> str:
    return json.dumps({"unsupported": list(labels)})


async def answer(draft: str, complete: AsyncMock, *, history: list[dict[str, str]] | None = None):
    steps = [call("search_knowledge", SEARCH), AgentStepResult(text=draft)]
    retriever = AsyncMock()
    retriever.retrieve.return_value = [chunk()]
    adapter = ToolAgentAdapter(
        cast(AsyncSession, InventoryDB([file()])),
        make_settings(),
        chat=ScriptChat(steps),
        retriever=retriever,
        claim_complete=complete,
    )
    return await adapter.answer(
        "Synthetic question", user_id=USER, history=history or [], history_window_complete=True
    )


async def traced(draft: str, complete: AsyncMock, *, history: list[dict[str, str]] | None = None):
    trace = CaseTrace(claim_detail=True)
    token = trace_var.set(trace)
    try:
        with tracing_installed():
            result = await answer(draft, complete, history=history)
    finally:
        trace_var.reset(token)
    return result, trace


def only(trace: CaseTrace) -> dict[str, Any]:
    assert len(trace.claim_checks) == 1
    return trace.claim_checks[0]


# --- what is captured -----------------------------------------------------------------------------


async def test_whole_answer_replacement_is_recorded_with_the_draft_and_the_raw_decision():
    result, trace = await traced(FABRICATED, fake_checker(flags("S1")))
    rec = only(trace)
    assert result.answer == NO_EVIDENCE_ANSWER
    assert rec["draft_answer"] == FABRICATED
    assert rec["statements"] == [FABRICATED]
    assert rec["checker"]["raw_reply"] == flags("S1") and rec["checker"]["model_called"] is True
    assert rec["decisions"]["raw_labels"] == ["S1"] and rec["decisions"]["flagged"] == ["S1"]
    out = rec["outcome"]
    assert out["result"] == "whole_answer_replaced" and out["replaced_entire_answer"] is True
    assert out["replacement_reason"] == "all_statements_removed"
    assert out["removed_statements"] == [{"label": "S1", "text": FABRICATED}]
    assert (
        out["remaining_answer"] == "" and out["checked"] is True and out["fail_open_reason"] is None
    )


async def test_partial_removal_separates_removed_from_remaining():
    result, trace = await traced(MIXED, fake_checker(flags("S2")))
    rec = only(trace)
    assert "90 days" not in result.answer
    assert rec["statements"] == [SUPPORTED, FABRICATED]
    out = rec["outcome"]
    assert out["result"] == "partial_removal" and out["replaced_entire_answer"] is False
    assert [r["label"] for r in out["removed_statements"]] == ["S2"]
    assert SUPPORTED in out["remaining_answer"] and "90 days" not in out["remaining_answer"]


async def test_no_removal_is_recorded_as_unchanged():
    _, trace = await traced(SUPPORTED, fake_checker(flags()))
    rec = only(trace)
    assert rec["decisions"]["raw_labels"] == [] and rec["outcome"]["result"] == "unchanged"
    assert rec["outcome"]["removed_statements"] == []
    assert rec["outcome"]["remaining_answer"] == SUPPORTED and rec["outcome"]["checked"] is True


async def test_a_flagged_framing_line_is_a_raw_decision_but_not_a_removal():
    draft = f"Key points:\n{SUPPORTED}"
    result, trace = await traced(draft, fake_checker(flags("S1")))
    rec = only(trace)
    assert rec["statements"][0] == "Key points:"
    assert rec["decisions"]["raw_labels"] == ["S1"]  # what the model said
    assert rec["decisions"]["flagged"] == [] and rec["decisions"]["framing_ignored"] == ["S1"]
    assert rec["outcome"]["result"] == "unchanged" and rec["outcome"]["removed_statements"] == []
    assert "Authoritative refund policy text." in result.answer


async def test_the_numbers_hint_the_checker_was_given_is_recorded():
    _, trace = await traced(FABRICATED, fake_checker(flags()))
    assert only(trace)["number_hints"] == {"S1": ["90"]}


async def test_the_conversation_context_given_to_the_checker_is_the_users_own_words():
    history = [
        {"role": "user", "text": "How long is the earlier thing?"},
        {"role": "assistant", "text": "An earlier assistant answer, never given to the checker."},
    ]
    _, trace = await traced(SUPPORTED, fake_checker(flags()), history=history)
    context = only(trace)["context"]["user_messages"]
    assert "How long is the earlier thing?" in context and "Synthetic question" in context
    assert "earlier assistant answer" not in context


async def test_the_evidence_the_checker_could_see_is_identified_by_chunk_not_copied():
    complete = fake_checker(flags())
    _, trace = await traced(SUPPORTED, complete)
    ev = only(trace)["evidence"]
    assert complete.await_args is not None
    sent_user_message = complete.await_args.args[1]
    assert ev["truncated"] is False and ev["chars_sent"] == ev["chars"] and ev["matches_sections"]
    (section,) = ev["sections"]
    (member,) = section["chunks"]
    assert uuid_like(member["chunk_id"]) and member["sent"] == "full"
    assert section["file"] and section["start"] < section["end"] <= ev["chars"]
    assert "Authoritative refund policy text." not in json.dumps(ev)  # no document text
    prompt = only(trace)["prompt"]
    assert prompt["user_message_chars"] == len(sent_user_message)
    assert prompt["user_message_sha256"] == sha(sent_user_message)
    assert prompt["system_sha256"] == sha(claim_module.SYSTEM_PROMPT)


async def test_truncated_evidence_says_which_chunk_was_cut(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(claim_module, "MAX_EVIDENCE_CHARS", 30)
    _, trace = await traced(SUPPORTED, fake_checker(flags()))
    ev = only(trace)["evidence"]
    assert ev["truncated"] is True and ev["chars_sent"] == 30 and ev["limit_chars"] == 30
    assert ev["chars"] > 30
    assert ev["sections"][0]["chunks"][0]["sent"] == "partial"


# --- failure and fail-open ------------------------------------------------------------------------


async def test_a_failing_checker_call_is_recorded_and_the_answer_is_unchanged():
    result, trace = await traced(FABRICATED, fake_checker(RuntimeError("provider down")))
    rec = only(trace)
    assert "90 days" in result.answer  # fail open: exactly the existing behaviour
    assert rec["checker"]["error"] == "RuntimeError" and rec["checker"]["raw_reply"] is None
    out = rec["outcome"]
    assert out["checked"] is False and out["fail_open_reason"] == "call_error:RuntimeError"
    assert out["result"] == "unchecked" and out["removed_statements"] == []
    assert "provider down" not in json.dumps(rec)  # the class name only


async def test_an_unusable_reply_is_kept_and_marked_unchecked():
    result, trace = await traced(FABRICATED, fake_checker("not json at all"))
    rec = only(trace)
    assert "90 days" in result.answer
    assert rec["checker"]["raw_reply"] == "not json at all"
    assert rec["decisions"]["raw_labels"] is None
    assert rec["outcome"]["fail_open_reason"] == "bad_reply" and rec["outcome"]["checked"] is False


async def test_a_timeout_is_recorded_as_a_call_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(claim_module, "CLAIM_CHECK_TIMEOUT_SECONDS", 0.01)

    async def slow(system: str, user: str) -> str:
        await asyncio.sleep(1)
        return flags()

    result, trace = await traced(FABRICATED, cast(AsyncMock, slow))
    rec = only(trace)
    assert "90 days" in result.answer
    assert rec["outcome"]["fail_open_reason"] == "call_error:TimeoutError"
    assert rec["outcome"]["checked"] is False


async def test_a_marker_only_draft_is_never_sent_and_says_why():
    complete = fake_checker(flags())
    _, trace = await traced("[source_1]", complete)
    rec = only(trace)
    complete.assert_not_called()
    assert rec["checker"]["model_called"] is False
    assert rec["outcome"]["fail_open_reason"] == "marker_only_answer"


async def test_a_checker_function_that_raises_is_recorded_and_still_fails_open(
    monkeypatch: pytest.MonkeyPatch,
):
    async def broken(*args: Any, **kwargs: Any):
        raise RuntimeError("bug in the checker")

    monkeypatch.setattr("app.services.tool_agent_service.enforce_claims", broken)
    result, trace = await traced(FABRICATED, fake_checker(flags("S1")))
    rec = only(trace)
    assert "90 days" in result.answer
    assert rec["outcome"]["checker_exception"] == "RuntimeError"
    assert rec["draft_answer"] == FABRICATED


# --- latency, model and metering ------------------------------------------------------------------


async def test_latency_is_recorded_and_the_model_name_is_taken_from_the_service_when_it_has_one():
    class Service:
        model_name = "checker-model-x"

        async def complete_json(self, system: str, user: str) -> str:
            return flags()

    _, trace = await traced(SUPPORTED, cast(AsyncMock, Service().complete_json))
    checker = only(trace)["checker"]
    assert checker["model"] == "checker-model-x"
    assert isinstance(checker["latency_ms"], float) and checker["latency_ms"] >= 0


def test_metering_of_the_case_is_attached_by_role_without_inventing_per_call_figures():
    trace = CaseTrace(claim_detail=True)
    trace.claim_checks.append({"index": 1})
    accounting = {
        "by_role": {"claim_check": {"calls": 1, "cost_usd": 0.0026, "input_tokens": 3418}}
    }
    claim_trace.attach_metering(trace, accounting)
    assert trace.as_dict()["claim_check_metering"] == {
        "case_totals_for_role": accounting["by_role"]["claim_check"],
        "checks_recorded": 1,
        "note": "Totals for every claim-check call of this case; per-call figures are not recorded.",
    }
    quiet = CaseTrace()
    claim_trace.attach_metering(quiet, accounting)
    assert "claim_check_metering" not in quiet.as_dict()


# --- privacy, isolation, behaviour ----------------------------------------------------------------


async def test_diagnostics_are_off_unless_the_case_asks_for_them():
    trace = CaseTrace()  # claim_detail defaults to False
    token = trace_var.set(trace)
    try:
        with tracing_installed():
            result = await answer(FABRICATED, fake_checker(flags("S1")))
    finally:
        trace_var.reset(token)
    assert result.answer == NO_EVIDENCE_ANSWER
    assert trace.claim_checks == [] and "claim_checks" not in trace.as_dict()
    assert SECRET not in json.dumps(trace.as_dict())
    # The existing, content-free event is still there.
    assert any(e.get("path") == "claim_check" for e in trace.events)


async def test_nothing_is_recorded_without_a_case_trace_or_outside_the_context():
    with tracing_installed():
        result = await answer(FABRICATED, fake_checker(flags("S1")))
    assert result.answer == NO_EVIDENCE_ANSWER
    assert trace_var.get() is None


def test_the_patches_are_removed_when_the_context_ends():
    originals = (
        ToolRagAgentService.__init__,
        claim_module.find_unsupported,
        getattr(graph_module, "evidence_text"),
    )
    with tracing_installed():
        assert ToolRagAgentService.__init__ is not originals[0]
    assert (
        ToolRagAgentService.__init__,
        claim_module.find_unsupported,
        getattr(graph_module, "evidence_text"),
    ) == originals


async def test_the_answer_is_identical_with_and_without_the_diagnostics():
    for draft, reply in ((FABRICATED, flags("S1")), (MIXED, flags("S2")), (SUPPORTED, flags())):
        plain = await answer(draft, fake_checker(reply))
        traced_result, _ = await traced(draft, fake_checker(reply))
        assert (plain.answer, plain.citations) == (traced_result.answer, traced_result.citations)


async def test_concurrent_cases_never_mix_their_diagnostics():
    async def one(draft: str, reply: str) -> CaseTrace:
        trace = CaseTrace(claim_detail=True)
        trace_var.set(trace)  # a task has its own copy of the context
        await answer(draft, fake_checker(reply))
        return trace

    with tracing_installed():
        first, second = await asyncio.gather(
            asyncio.create_task(one(FABRICATED, flags("S1"))),
            asyncio.create_task(one(SUPPORTED, flags())),
        )
    assert [r["draft_answer"] for r in first.claim_checks] == [FABRICATED]
    assert [r["draft_answer"] for r in second.claim_checks] == [SUPPORTED]


async def test_no_draft_or_statement_reaches_the_application_log(caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.DEBUG):
        await traced(FABRICATED, fake_checker(flags("S1")))
    assert SECRET not in caplog.text and "Authoritative" not in caplog.text


async def test_the_diagnostics_are_plain_json_and_hold_no_document_text():
    _, trace = await traced(MIXED, fake_checker(flags("S2")))
    dumped = json.dumps(trace.as_dict())
    assert json.loads(dumped)["claim_checks"][0]["index"] == 1
    # The draft is model output and is kept; the retrieved passage itself is only identified, never copied
    # (the draft here quotes the passage, so check the evidence block on its own).
    assert "Authoritative refund policy text." not in json.dumps(trace.claim_checks[0]["evidence"])


def sha(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode()).hexdigest()


def uuid_like(value: str) -> bool:
    import uuid

    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


# --- the explicit switch: run_case, run_pipeline and the CLI ----------------------------------------


class FakeMeter:
    stopped_cases: set[str] = set()

    def case_accounting(self, key: str) -> dict[str, Any]:
        return {"by_role": {"claim_check": {"calls": 1, "cost_usd": 0.0026, "models": ["m"]}}}


async def run_one_case(monkeypatch: pytest.MonkeyPatch, **kwargs: Any) -> dict[str, Any]:
    from evaluation.rag_eval import runner

    seen: dict[str, Any] = {}

    async def fake_answer(settings: Any, case: Any, by_name: Any, pipeline: Any, sessions: Any):
        trace = trace_var.get()
        assert trace is not None
        seen["claim_detail"] = trace.claim_detail
        if trace.claim_detail:
            trace.claim_checks.append({"index": 1, "draft_answer": "d"})
        return {"reply": "r", "id": "x"}

    async def fake_judge(settings: Any, case: Any, row: Any) -> Any:
        return row

    monkeypatch.setattr(runner, "answer_case", fake_answer)
    monkeypatch.setattr(runner, "score_row", lambda case, row: row)
    monkeypatch.setattr(runner, "judge_row", fake_judge)
    row = await runner.run_case(
        make_settings(),
        {"id": "x"},
        [],
        "tool_agent",
        None,
        cast(Any, FakeMeter()),
        **kwargs,
    )
    row["_seen"] = seen
    return row


async def test_run_case_records_the_diagnostics_only_when_asked(monkeypatch: pytest.MonkeyPatch):
    plain = await run_one_case(monkeypatch)
    assert plain["_seen"]["claim_detail"] is False
    assert "claim_checks" not in plain["trace"] and "claim_check_metering" not in plain["trace"]
    detailed = await run_one_case(monkeypatch, trace_claim_check=True)
    assert detailed["_seen"]["claim_detail"] is True
    assert detailed["trace"]["claim_checks"][0]["draft_answer"] == "d"
    metering = detailed["trace"]["claim_check_metering"]
    assert (
        metering["case_totals_for_role"]["cost_usd"] == 0.0026 and metering["checks_recorded"] == 1
    )


async def test_run_pipeline_passes_the_switch_only_when_set(monkeypatch: pytest.MonkeyPatch):
    from evaluation.rag_eval import runner, target

    received: list[dict[str, Any]] = []

    async def fake_case(settings: Any, case: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
        received.append(kwargs)
        return {
            "id": case["id"], "category": "x", "split": "dev", "language": "en",
            "expected_behavior": "answer", "question": "q", "reply": "", "cited_files": [],
            "error": None, "latency_s": 0.0, "overall": {"pass": False},
            "evidence": {"found": False}, "answer": {"correct": False},
            "clean": {"clean": True}, "refusal": None,
        }  # fmt: skip

    monkeypatch.setattr(runner, "run_case", fake_case)
    monkeypatch.setattr(runner, "session_factory", lambda settings: None)
    cases = [{"id": "a", "question": "q", "must_include": []}]
    plain = await runner.run_pipeline(target.eval_settings(), cases, [], "legacy")
    on = await runner.run_pipeline(
        target.eval_settings(), cases, [], "legacy", trace_claim_check=True
    )
    assert received == [{}, {"trace_claim_check": True}]
    assert "diagnostics" not in plain
    assert on["diagnostics"] == {"claim_check_trace": True, "contains_draft_answers": True}


def test_the_held_out_run_refuses_the_diagnostics_before_reading_anything(
    monkeypatch: pytest.MonkeyPatch,
):
    from evaluation.rag_eval import cli
    from tests.evaluation.test_f_dataset_and_heldout import run_args, stub_for_run

    events: list[str] = []
    stub_for_run(monkeypatch, events)
    monkeypatch.setattr(cli, "held_out_path", lambda: pytest.fail("the sealed path was looked up"))
    for plan in (False, True):
        with pytest.raises(SystemExit, match="held-out") as caught:
            asyncio.run(cli.run(run_args(trace_claim_check=True, plan=plan)))
        assert "--trace-claim-check" in str(caught.value)
    assert events == []


def test_the_diagnostics_stay_allowed_on_development_and_default_to_off(
    monkeypatch: pytest.MonkeyPatch,
):
    from evaluation.rag_eval import cli
    from tests.evaluation.test_f_dataset_and_heldout import run_args, stub_for_run

    stub_for_run(monkeypatch, [])
    monkeypatch.setattr(cli, "load_many", lambda _n: {"cases": []})
    monkeypatch.setattr(cli, "validate", lambda *_a, **_k: [])
    monkeypatch.setattr(cli, "files_to_check", lambda *_a: [])
    with pytest.raises(SystemExit, match="No cases selected"):  # got past the guard
        asyncio.run(cli.run(run_args(split="dev", trace_claim_check=True)))
    import sys

    monkeypatch.setattr(sys, "argv", ["cli", "run", "--cap", "0.25", "--plan"])
    captured: dict[str, Any] = {}

    async def spy(args: Any) -> None:
        captured["flag"] = args.trace_claim_check

    monkeypatch.setattr(cli, "run", spy)
    cli.main()
    assert captured["flag"] is False


def test_the_cli_passes_the_switch_to_run_pipeline_only_when_set(monkeypatch: pytest.MonkeyPatch):
    """The dev path of ``cli.run`` up to ``run_pipeline``, with everything paid or on disk replaced."""
    from evaluation.rag_eval import cli
    from tests.evaluation.test_f_dataset_and_heldout import run_args, stub_for_run

    case = {"id": "x", "category": "c", "expected_behavior": "answer", "must_include": []}
    stub_for_run(monkeypatch, [])
    monkeypatch.setattr(cli, "CostMeter", lambda *_a, **_k: StopMeter())
    monkeypatch.setattr(cli, "load_many", lambda _n: {"cases": [case]})
    monkeypatch.setattr(cli, "validate", lambda *_a, **_k: [])
    monkeypatch.setattr(cli, "files_to_check", lambda *_a: [])
    monkeypatch.setattr(cli, "select", lambda cases, _s: cases)
    monkeypatch.setattr(cli, "estimate_run", lambda *_a, **_k: {"estimated_usd": 0.0})
    monkeypatch.setattr(cli, "refuse_over_cap", lambda *_a: None)

    async def settings_stub(args: Any, chat_model: Any = None) -> Any:
        return make_settings()

    monkeypatch.setattr(cli, "run_settings", settings_stub)
    monkeypatch.setattr(cli, "require_prices", lambda *_a: None)
    calls: list[dict[str, Any]] = []

    async def fake_pipeline(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        raise SystemExit("stop after run_pipeline")

    monkeypatch.setattr(cli, "run_pipeline", fake_pipeline)
    for flag in (False, True):
        with pytest.raises(SystemExit, match="stop after run_pipeline"):
            asyncio.run(cli.run(run_args(split="dev", trace_claim_check=flag)))
    assert "trace_claim_check" not in calls[0] and calls[1]["trace_claim_check"] is True


class StopMeter:
    def installed(self) -> Any:
        from contextlib import nullcontext

        return nullcontext()


async def test_the_adapters_own_checker_path_is_traced_and_names_its_model(
    monkeypatch: pytest.MonkeyPatch,
):
    """The path the evaluation really uses: the adapter builds the checker on its own model."""
    from tests.agents.tool_rag.test_claim_check import fake_service_factory, owned_answer

    made: list[Any] = []
    base = fake_service_factory(made)

    class Named(base):  # type: ignore[valid-type, misc]
        @property
        def model_name(self) -> str:
            return self.model

    trace = CaseTrace(claim_detail=True)
    token = trace_var.set(trace)
    try:
        with tracing_installed():
            result = await owned_answer(monkeypatch, make_settings(), Named)
    finally:
        trace_var.reset(token)
    rec = only(trace)
    assert result.answer == NO_EVIDENCE_ANSWER  # the fake checker flags S1: behaviour as before
    assert rec["checker"]["model"] == "gpt-5.4-mini" and rec["checker"]["model_called"] is True
    assert rec["outcome"]["result"] == "whole_answer_replaced"


# --- flagged is not removed: the outcome follows the observed change of the text -------------------------


NUMBERED = "1. Authoritative refund policy text. Refunds take 90 days. [source_1]"


async def test_a_flagged_numbered_sentence_that_stays_in_the_answer_is_not_recorded_as_removed():
    """Reviewer's reproduced example. ``enforce_claims`` matches against ``sentences(line)``, which keeps the list
    number apart ("1."), so the flagged unit "1. Authoritative ..." is never found and nothing is dropped, while the
    application still counts one removal. The record must say what happened to the text."""
    result, trace = await traced(NUMBERED, fake_checker(flags("S1")))
    rec = only(trace)
    out = rec["outcome"]
    assert rec["statements"][0] == "1. Authoritative refund policy text."
    assert rec["decisions"]["flagged"] == ["S1"]  # what the checker decided is unchanged
    assert (
        out["remaining_answer"] == NUMBERED and "Authoritative refund policy text." in result.answer
    )
    assert out["result"] == "flagged_none_removed"
    assert out["removed_statements"] == []
    assert [s["label"] for s in out["flagged_not_removed"]] == ["S1"]
    assert out["reported_removed_count"] == 1 and out["observed_removed_count"] == 0
    assert out["counter_matches_observation"] is False
    assert out["replaced_entire_answer"] is False


async def test_a_flagged_sentence_after_a_list_number_is_removed_and_recorded():
    result, trace = await traced(NUMBERED, fake_checker(flags("S2")))
    out = only(trace)["outcome"]
    assert "90 days" not in result.answer
    assert out["result"] == "partial_removal"
    assert [s["label"] for s in out["removed_statements"]] == ["S2"]
    assert (
        out["flagged_not_removed"] == []
        and out["remaining_answer"] == "1. Authoritative refund policy text."
    )
    assert out["observed_removed_count"] == 1 and out["counter_matches_observation"] is True


async def test_one_sentence_cut_from_a_line_is_recorded_as_removed():
    draft = "Authoritative refund policy text. Refunds take 90 days. [source_1]"
    _, trace = await traced(draft, fake_checker(flags("S2")))
    out = only(trace)["outcome"]
    assert [s["label"] for s in out["removed_statements"]] == ["S2"]
    assert out["remaining_answer"] == "Authoritative refund policy text."
    assert out["collateral_removed"] == [] and out["counter_matches_observation"] is True


async def test_a_repeated_statement_is_removed_everywhere_and_the_extra_copy_is_reported():
    """The application drops every statement with the flagged text: the unflagged copy is collateral."""
    line = "Refunds take 90 days. [source_1]"
    draft = f"{line}\n{SUPPORTED}\n{line}"
    result, trace = await traced(draft, fake_checker(flags("S1")))
    rec = only(trace)
    out = rec["outcome"]
    assert rec["statements"] == [line, SUPPORTED, line]
    assert "90 days" not in result.answer
    assert [s["label"] for s in out["removed_statements"]] == ["S1"]
    assert [s["label"] for s in out["collateral_removed"]] == ["S3"]
    assert out["reported_removed_count"] == 1 and out["observed_removed_count"] == 2
    assert out["counter_matches_observation"] is False
    assert out["remaining_answer"] == SUPPORTED


async def test_whole_answer_replacement_is_still_recorded_when_every_statement_is_gone():
    _, trace = await traced(FABRICATED, fake_checker(flags("S1")))
    out = only(trace)["outcome"]
    assert out["result"] == "whole_answer_replaced" and out["replaced_entire_answer"] is True
    assert [s["label"] for s in out["removed_statements"]] == ["S1"]
    assert out["flagged_not_removed"] == [] and out["counter_matches_observation"] is True


async def test_a_checker_that_flags_nothing_leaves_every_new_field_empty():
    _, trace = await traced(SUPPORTED, fake_checker(flags()))
    out = only(trace)["outcome"]
    assert out["result"] == "unchanged"
    assert (out["removed_statements"], out["flagged_not_removed"], out["collateral_removed"]) == (
        [],
        [],
        [],
    )
    assert out["uncertain"] == [] and out["unattributed_change"] is False
    assert out["reported_removed_count"] == 0 and out["observed_removed_count"] == 0


def test_attribution_records_uncertainty_instead_of_inventing_a_removal():
    from evaluation.rag_eval.claim_trace import attribute_removals

    statements = ["Alpha is 1.", "Beta is 2.", "Alpha is 1."]
    draft = "Alpha is 1.\nBeta is 2.\nAlpha is 1."
    # One of the two identical copies is gone and the other remains: which one was removed cannot be told.
    got = attribute_removals(draft, statements, ["S1"], "Beta is 2.\nAlpha is 1.")
    assert [u["label"] for u in got["uncertain"]] == ["S1"]
    assert (
        got["removed"] == []
        and got["flagged_not_removed"] == []
        and got["collateral_removed"] == []
    )


def test_attribution_flags_a_change_no_statement_explains():
    from evaluation.rag_eval.claim_trace import attribute_removals

    got = attribute_removals(
        "Alpha is 1. Beta is 2.", ["Alpha is 1.", "Beta is 2."], [], "Alpha is 1. Beta is 3."
    )
    assert got["unattributed_change"] is True
    assert (
        got["removed"] == []
        and got["flagged_not_removed"] == []
        and got["collateral_removed"] == []
    )
    assert [u["label"] for u in got["uncertain"]] == ["S2"]


def test_a_text_that_only_lives_inside_a_removed_statement_is_not_collateral():
    from evaluation.rag_eval.claim_trace import attribute_removals

    statements = ["The fee is 5 USD.", "5 USD"]
    got = attribute_removals(
        "The fee is 5 USD.\n5 USD", statements, ["S1"], "5 USD"
    )  # "5 USD" still appears once: nothing of it was removed
    assert [r["label"] for r in got["removed"]] == ["S1"]
    assert got["collateral_removed"] == [] and got["uncertain"] == []


def test_whitespace_differences_between_draft_and_remaining_text_do_not_hide_a_removal():
    from evaluation.rag_eval.claim_trace import attribute_removals

    got = attribute_removals(
        "Alpha  is 1.\n\nBeta is 2.", ["Alpha  is 1.", "Beta is 2."], ["S2"], "Alpha is 1."
    )
    assert [r["label"] for r in got["removed"]] == ["S2"] and got["flagged_not_removed"] == []
