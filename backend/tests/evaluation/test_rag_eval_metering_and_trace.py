"""M1 ticket 02: per-case, per-role metering and the trace of what the agent really did.

Everything here is free: no key, no network, no container. The OpenAI SDK methods are replaced by stubs
(under the real meter), and the database is a small fake that answers only what the tools ask of it.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from openai.resources.chat.completions import AsyncCompletions
from openai.resources.embeddings import AsyncEmbeddings

from app.agents.tool_rag.claim_check import SYSTEM_PROMPT as CLAIM_PROMPT
from app.agents.tool_rag.conversation import INTENT_SYSTEM_PROMPT
from app.agents.tool_rag.execution.context import EvidenceRecoveryBudget, ExecutionContext
from app.agents.tool_rag.execution.executor import ToolExecutor
from app.agents.tool_rag.handles import RuntimeHandleRegistry
from app.agents.tool_rag.prompts import AGENT_SYSTEM_PROMPT
from app.core.config import Settings
from app.llm.prompts import FOLLOWUP_REWRITE_SYSTEM_PROMPT, RAG_SYSTEM_PROMPT
from app.retrieval.grade import EvidenceGrade
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.types import RetrievedChunk
from app.routing.intent_frame.execution import RetrievalRequest
from app.routing.intent_frame.scope import EligibleCollectionScope, ResolvedFileScope
from app.services.tool_agent_service import ToolAgentAdapter
from evaluation.rag_eval import manifest, runner, score, target
from evaluation.rag_eval.meter import (
    BudgetExceeded,
    CostMeter,
    UnmeteredRequest,
    UnpricedModel,
    case_var,
    label_var,
)
from evaluation.rag_eval.trace import (
    CaseTrace,
    RecordingRetriever,
    execution_summary,
    trace_var,
    tracing_installed,
)

NANO = "gpt-5.4-nano"
MINI = "gpt-5.4-mini"


def usage(inp: int, out: int = 0, cached: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        prompt_tokens=inp,
        completion_tokens=out,
        prompt_tokens_details=SimpleNamespace(cached_tokens=cached),
    )


def chat_reply(model: str, text: str, inp: int, out: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        model=model,
        choices=[SimpleNamespace(message=SimpleNamespace(content=text, tool_calls=None))],
        usage=usage(inp, out),
    )


def system(prompt: str) -> list[dict[str, str]]:
    return [{"role": "system", "content": prompt}, {"role": "user", "content": "q"}]


async def sdk_chat(**kwargs: Any) -> Any:
    method: Any = AsyncCompletions.create
    return await method(SimpleNamespace(), **kwargs)


async def sdk_embed(**kwargs: Any) -> Any:
    method: Any = AsyncEmbeddings.create
    return await method(SimpleNamespace(), **kwargs)


# --- attribution by case and role ---------------------------------------------------------------


async def test_concurrent_cases_are_attributed_to_the_right_case_and_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Four interleaved cases, every role, and two roles (claim check, judge) on one model."""

    async def fake_chat(self: Any, *args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(0.001 * (hash(str(kwargs["messages"])) % 5))  # interleave the cases
        return chat_reply(kwargs["model"], "{}", kwargs["extra_headers"]["tokens"])

    async def fake_embed(self: Any, *args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(0.002)
        return SimpleNamespace(
            model="text-embedding-3-small", usage=SimpleNamespace(prompt_tokens=7, total_tokens=7)
        )

    monkeypatch.setattr(AsyncCompletions, "create", fake_chat)
    monkeypatch.setattr(AsyncEmbeddings, "create", fake_embed)
    meter = CostMeter(5.0)
    roles = {
        "intent_gate": (INTENT_SYSTEM_PROMPT, NANO),
        "agent_step": (AGENT_SYSTEM_PROMPT, NANO),
        "claim_check": (CLAIM_PROMPT, MINI),
        "followup_rewrite": (FOLLOWUP_REWRITE_SYSTEM_PROMPT, NANO),
        "answer_generation": (RAG_SYSTEM_PROMPT, NANO),
    }

    async def one_case(number: int) -> None:
        case_var.set(f"case-{number}")
        for index, (prompt, model) in enumerate(roles.values()):
            tokens = number * 1000 + index * 10
            await sdk_chat(model=model, messages=system(prompt), extra_headers={"tokens": tokens})
            await asyncio.sleep(0)
        label_var.set("judge")  # the judge has no system prompt: it labels itself
        await sdk_chat(
            model=MINI,
            messages=[{"role": "user", "content": "x"}],
            extra_headers={"tokens": number},
        )
        await sdk_embed(model="text-embedding-3-small", input=["a"])

    with meter.installed():
        await asyncio.gather(*(asyncio.create_task(one_case(n)) for n in range(1, 5)))

    for number in range(1, 5):
        accounting = meter.case_accounting(f"case-{number}")
        by_role = accounting["by_role"]
        assert set(by_role) == {*roles, "judge", "embedding"}
        for index, role in enumerate(roles):
            assert by_role[role]["calls"] == 1
            assert by_role[role]["input_tokens"] == number * 1000 + index * 10
        assert by_role["judge"]["input_tokens"] == number  # not mixed into claim_check (same model)
        assert by_role["claim_check"]["models"] == [MINI] == by_role["judge"]["models"]
        assert by_role["embedding"]["input_tokens"] == 7
        assert accounting["total"]["calls"] == 7
        assert accounting["usage_incomplete"] is False
    assert sum(r["calls"] for r in meter.summary()["by_label_and_model"]) == 28


async def test_failed_and_cancelled_calls_are_counted_and_an_unknown_model_still_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_chat(self: Any, *args: Any, **kwargs: Any) -> Any:
        if kwargs["model"] == "boom":
            raise TimeoutError("provider timed out")
        if kwargs["model"] == "slow":
            await asyncio.sleep(30)
        return chat_reply(kwargs["model"], "{}", 100)

    monkeypatch.setattr(AsyncCompletions, "create", fake_chat)
    meter = CostMeter(5.0)
    case_var.set("c1")
    with meter.installed():
        await sdk_chat(model=NANO, messages=system(AGENT_SYSTEM_PROMPT))
        with pytest.raises(TimeoutError):
            await sdk_chat(model="boom", messages=system(AGENT_SYSTEM_PROMPT))
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.01):
                await sdk_chat(model="slow", messages=system(CLAIM_PROMPT))
        with pytest.raises(UnpricedModel):
            await sdk_chat(model="gpt-99-imaginary", messages=system(AGENT_SYSTEM_PROMPT))
    accounting = meter.case_accounting("c1")["by_role"]
    assert (
        accounting["agent_step"]["calls"] == 2 + 0
    )  # one success, one failure; the unpriced one raised
    assert accounting["agent_step"]["failed_calls"] == 1
    assert accounting["claim_check"]["failed_calls"] == 1
    assert accounting["claim_check"]["cancelled_calls"] == 1
    assert meter.tripped and "c1" in meter.stopped_cases


async def test_a_response_without_usage_is_counted_and_flagged_not_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_chat(self: Any, *args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(model=None, usage=None)  # no usage block, no returned model

    monkeypatch.setattr(AsyncCompletions, "create", fake_chat)
    meter = CostMeter(5.0)
    case_var.set("c1")
    with meter.installed():
        await sdk_chat(model=NANO, messages=system(INTENT_SYSTEM_PROMPT))
    accounting = meter.case_accounting("c1")
    assert accounting["by_role"]["intent_gate"]["calls"] == 1
    assert accounting["by_role"]["intent_gate"]["missing_usage_calls"] == 1
    assert accounting["by_role"]["intent_gate"]["models"] == [NANO]  # the requested model stands in
    assert accounting["total"]["cost_usd"] == 0
    assert accounting["usage_incomplete"] is True  # the case cost is a lower bound
    assert meter.total == 0 and not meter.tripped


async def test_a_streamed_request_is_refused_and_stops_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reached = 0

    async def fake_chat(self: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal reached
        reached += 1
        return chat_reply(NANO, "{}", 1)

    monkeypatch.setattr(AsyncCompletions, "create", fake_chat)
    meter = CostMeter(5.0)
    with meter.installed():
        with pytest.raises(UnmeteredRequest):
            await sdk_chat(model=NANO, messages=system(AGENT_SYSTEM_PROMPT), stream=True)
    assert reached == 0 and meter.tripped
    assert not issubclass(UnmeteredRequest, Exception)  # application code cannot swallow it


def test_the_manifest_says_what_the_meter_cannot_see() -> None:
    from evaluation.rag_eval.meter import METERING_LIMITS

    text = json.dumps(METERING_LIMITS)
    assert "SDK automatic retries" in text and "streamed requests" in text
    built = manifest.build_manifest(
        target.eval_settings(),
        files=[],
        datasets=["rag_v2_cases.json"],
        with_messy=False,
        split="dev",
        concurrency=1,
        repeat_index=1,
        repeat_count=1,
        cap_usd=1.0,
    )
    assert built["metering"] == METERING_LIMITS


# --- the cap through the real tool-agent adapter -----------------------------------------------


class FakeSession:
    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


def sample_case(number: int) -> dict[str, Any]:
    return {
        "id": f"case-{number}",
        "category": "single",
        "split": "dev",
        "language": "en",
        "expected_behavior": "answer",
        "question": f"What is item {number}?",
        "must_include": [
            ["retrieved document evidence"]
        ],  # the application's reply to an unevidenced answer
        "must_not_include": [],
        "expected_files": [],
    }


@pytest.fixture
def agent_settings() -> Settings:
    return target.eval_settings().model_copy(update={"openai_api_key": "not-a-real-key"})


def real_adapter_service(seen: dict[str, Any]) -> type:
    """A stand-in for RagService that runs the REAL ToolAgentAdapter (intent gate, graph, claim wiring)."""

    class Service:
        def __init__(
            self, db: Any, settings: Settings, *, persist_query_history: bool, retriever: Any
        ) -> None:  # any chat_service or agent keyword here would be a TypeError
            seen["retriever"] = retriever
            self.db, self.settings, self.retriever = db, settings, retriever

        async def ask(self, question: str, user_id: Any, **kwargs: Any) -> Any:
            adapter = ToolAgentAdapter(self.db, self.settings, retriever=self.retriever)
            result = await adapter.answer(
                question,
                user_id=user_id,
                history=(),
                history_window_complete=False,
            )
            return SimpleNamespace(answer=result.answer, citations=list(result.citations))

    return Service


def stub_provider(monkeypatch: pytest.MonkeyPatch, calls: list[str], per_call_tokens: int) -> None:
    """Intent gate says 'document question'; the agent answers 'done' without tools."""

    async def fake_chat(self: Any, *args: Any, **kwargs: Any) -> Any:
        first = kwargs["messages"][0]["content"]
        calls.append("intent" if first == INTENT_SYSTEM_PROMPT else "agent")
        text = '{"intent": "document_question"}' if first == INTENT_SYSTEM_PROMPT else "done"
        return chat_reply(NANO, text, per_call_tokens)

    monkeypatch.setattr(AsyncCompletions, "create", fake_chat)


async def test_a_tripped_cap_stops_the_run_through_the_real_tool_agent_adapter(
    monkeypatch: pytest.MonkeyPatch, agent_settings: Settings
) -> None:
    calls: list[str] = []
    seen: dict[str, Any] = {}
    stub_provider(monkeypatch, calls, 1_000_000)  # $0.20 a call at the recorded nano price
    monkeypatch.setattr(runner, "RagService", real_adapter_service(seen))
    monkeypatch.setattr(runner, "session_factory", lambda settings: FakeSession)
    meter = CostMeter(0.50)
    cases = [sample_case(n) for n in range(1, 5)]
    with meter.installed():
        result = await runner.run_pipeline(
            agent_settings, cases, [], "tool_agent", concurrency=1, meter=meter
        )
    rows = {r["id"]: r for r in result["rows"]}
    # case 1 used two calls ($0.40); case 2's intent gate crossed the cap and its agent step was refused
    assert calls == ["intent", "agent", "intent"]
    assert rows["case-1"]["error"] is None and not rows["case-1"].get("cap_stopped")
    assert rows["case-1"]["overall"]["pass"] is True
    for stopped in ("case-2", "case-3", "case-4"):
        assert rows[stopped]["cap_stopped"] is True
        assert rows[stopped]["error"] == "cap_stopped"  # not an ordinary product error row
        assert rows[stopped]["overall"] is None
    summary = result["summary"]
    assert summary["incomplete"] is True and summary["cap_stopped"] == 3
    assert summary["overall_pass"]["n"] == 1  # excluded from every rate
    assert summary["errors"] == 0 and summary["cases"] == 4
    assert meter.tripped
    assert isinstance(seen["retriever"], RecordingRetriever)  # only the retriever is injected


async def test_a_cap_error_swallowed_by_the_service_still_ends_up_cap_stopped(
    monkeypatch: pytest.MonkeyPatch, agent_settings: Settings
) -> None:
    """Defence in depth: if some layer turned the cap into an ordinary error, the row is still cap_stopped."""
    stub_provider(monkeypatch, [], 1_000_000)
    inner = real_adapter_service({})

    class Swallowing(inner):  # type: ignore[valid-type, misc]
        async def ask(self, question: str, user_id: Any, **kwargs: Any) -> Any:
            try:
                return await super().ask(question, user_id, **kwargs)
            except BudgetExceeded:
                raise RuntimeError("provider error") from None

    monkeypatch.setattr(runner, "RagService", Swallowing)
    monkeypatch.setattr(runner, "session_factory", lambda settings: FakeSession)
    meter = CostMeter(0.30)
    with meter.installed():
        result = await runner.run_pipeline(
            agent_settings,
            [sample_case(1), sample_case(2)],
            [],
            "tool_agent",
            concurrency=1,
            meter=meter,
        )
    second = result["rows"][1]
    assert second["cap_stopped"] is True and second["error"] == "cap_stopped"
    assert result["summary"]["errors"] == 0 and result["summary"]["incomplete"] is True


async def test_rows_carry_accounting_trace_and_execution_and_old_rows_still_rescore(
    monkeypatch: pytest.MonkeyPatch, agent_settings: Settings
) -> None:
    stub_provider(monkeypatch, [], 1000)
    monkeypatch.setattr(runner, "RagService", real_adapter_service({}))
    monkeypatch.setattr(runner, "session_factory", lambda settings: FakeSession)
    meter = CostMeter(5.0)
    with meter.installed():
        result = await runner.run_pipeline(
            agent_settings, [sample_case(1)], [], "tool_agent", concurrency=1, meter=meter
        )
    row = result["rows"][0]
    for existing in ("id", "reply", "cited_files", "error", "latency_s", "evidence", "overall"):
        assert existing in row
    assert row["cited"] == []
    by_role = row["accounting"]["by_role"]
    assert by_role["intent_gate"]["calls"] == 1 and by_role["agent_step"]["calls"] == 1
    assert row["accounting"]["total"]["input_tokens"] == 2000
    assert row["trace"]["schema_version"] == 1 and row["trace"]["tool_calls"] == []
    execution = row["execution"]
    assert execution["path"] == "tool_agent" and execution["outcome"] == "COMPLETED"
    assert execution["agent_steps"] == 1 and execution["search_count"] == 0
    json.dumps(row)  # the row must serialise
    # rescoring recomputes the verdict from reply and citations and keeps the new fields
    rescored = runner.score_row(sample_case(1), dict(row))
    assert rescored["accounting"] == row["accounting"] and rescored["trace"] == row["trace"]
    assert rescored["answer"]["correct"] is True
    # a row from before this ticket has none of them and rescores the same way
    old = {k: row[k] for k in ("id", "reply", "cited_files", "error", "latency_s")}
    assert runner.score_row(sample_case(1), old)["answer"]["correct"] is True


def test_summary_leaves_cap_stopped_rows_out_of_rates_and_flags_the_run() -> None:
    ok = {"category": "a", "latency_s": 1.0, "error": None, "overall": {"pass": True}}
    stopped = {
        "category": "a",
        "latency_s": None,
        "error": "cap_stopped",
        "cap_stopped": True,
        "overall": None,
    }
    summary = score.summarise([ok, stopped, stopped])
    assert summary["incomplete"] is True and summary["cap_stopped"] == 2
    assert summary["overall_pass"]["n"] == 1 and summary["errors"] == 0
    assert score.summarise([ok])["incomplete"] is False


# --- the recording retriever -------------------------------------------------------------------


def chunk(index: int, score_value: float, name: str = "a.txt") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.UUID(int=index),
        document_id=uuid.UUID(int=100 + index),
        drive_file_id=uuid.UUID(int=200),
        filename=name,
        mime_type="text/plain",
        modified_at=datetime(2026, 1, 1, tzinfo=UTC),
        chunk_index=index,
        text=f"text {index}",
        score=score_value,
        source_scores={"vector": score_value, "keyword": 0.5},
        fusion_score=score_value / 2,
    )


async def test_the_recording_retriever_records_each_search_and_passes_results_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    grades = [
        EvidenceGrade(sufficient=True, reason="ok", chunks=[chunk(1, 0.9), chunk(2, 0.8)]),
        EvidenceGrade(sufficient=False, reason="weak", chunks=[]),
    ]

    async def inner(self: Any, request: Any, *, trace: Any = None) -> EvidenceGrade:
        return grades.pop(0)

    monkeypatch.setattr(HybridRetriever, "retrieve_with_grade", inner)
    retriever = RecordingRetriever(SimpleNamespace(), target.eval_settings())  # type: ignore[arg-type]
    user = uuid.uuid4()
    case = CaseTrace()
    trace_var.set(case)
    first = await retriever.retrieve(
        RetrievalRequest(
            user_id=user, query="vacation days", scope=EligibleCollectionScope(), candidate_limit=20
        )
    )
    second = await retriever.retrieve_with_grade(
        RetrievalRequest(
            user_id=user,
            query="in this file",
            scope=ResolvedFileScope(file_ids=(uuid.UUID(int=200),)),
            candidate_limit=5,
        )
    )
    assert [x.chunk_id for x in first] == [uuid.UUID(int=1), uuid.UUID(int=2)]  # unchanged
    assert second.reason == "weak" and second.chunks == []
    one, two = case.searches
    assert (one["query"], one["scope"], one["scope_files"]) == ("vacation days", "collection", None)
    assert [(c["rank"], c["chunk_id"], c["score"]) for c in one["chunks"]] == [
        (1, str(uuid.UUID(int=1)), 0.9),
        (2, str(uuid.UUID(int=2)), 0.8),
    ]
    assert one["chunks"][0]["sources"] == {"vector": 0.9, "keyword": 0.5}
    assert one["chunks"][0]["fusion_score"] == 0.45 and one["sufficient"] is True
    assert (two["scope"], two["scope_files"], two["candidate_limit"], two["chunks"]) == (
        "files",
        1,
        5,
        [],
    )


async def test_a_failing_search_is_recorded_and_the_error_still_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def inner(self: Any, request: Any, *, trace: Any = None) -> EvidenceGrade:
        raise ConnectionError("store down")

    monkeypatch.setattr(HybridRetriever, "retrieve_with_grade", inner)
    retriever = RecordingRetriever(SimpleNamespace(), target.eval_settings())  # type: ignore[arg-type]
    case = CaseTrace()
    trace_var.set(case)
    with pytest.raises(ConnectionError):
        await retriever.retrieve(
            RetrievalRequest(
                user_id=uuid.uuid4(), query="q", scope=EligibleCollectionScope(), candidate_limit=3
            )
        )
    assert case.searches[0]["error"] == "ConnectionError" and "chunks" not in case.searches[0]


# --- the executor wrapper ----------------------------------------------------------------------


class FakeDb:
    """Answers only what the tools ask: eligible-file lookups, listings and the whole-file read."""

    def __init__(self, files: list[Any], read_rows: list[tuple[Any, ...]], totals: tuple[int, int]):
        self.files, self.read_rows, self.totals = files, read_rows, totals

    async def scalars(self, statement: Any) -> Any:
        # ``select(DriveFile.id)`` is the ownership check; ``select(DriveFile)`` is the file listing
        ids = len(statement.selected_columns) == 1
        return SimpleNamespace(all=lambda: [f.id for f in self.files] if ids else self.files)

    async def execute(self, statement: Any) -> Any:
        rows, totals = self.read_rows, self.totals

        class Result:
            def one(self) -> tuple[int, int]:
                return totals

            def __iter__(self) -> Iterator[tuple[Any, ...]]:
                return iter(rows)

        return Result()


FILE_ID = uuid.UUID(int=200)
ALL = {"kind": "ALL_ELIGIBLE_INDEXED_FILES"}
ALL_FILES_LIST = json.dumps({"operation": "LIST", "scope": ALL})
ALL_FILES_COUNT = json.dumps({"operation": "COUNT", "scope": ALL})


def make_context(db: FakeDb, retriever: Any = None, budget: int = 12000) -> ExecutionContext:
    handles = RuntimeHandleRegistry()
    handles.register_file(FILE_ID, filename="policy.txt")
    return ExecutionContext(
        user_id=uuid.uuid4(),
        db=db,  # type: ignore[arg-type]
        handles=handles,
        retriever=retriever,
        max_context_chars=budget,
        recovery_budget=EvidenceRecoveryBudget(),
    )


def eligible_file() -> SimpleNamespace:
    return SimpleNamespace(id=FILE_ID, name="policy.txt", mime_type="text/plain")


def evidence_args(mode: str, query: str | None = None) -> str:
    return json.dumps(
        {"file_handle": {"kind": "FILE", "value": "file_1"}, "mode": mode, "query": query}
    )


async def test_the_executor_wrapper_records_a_file_listing() -> None:
    context = make_context(FakeDb([eligible_file()], [], (0, 0)))
    case = CaseTrace()
    trace_var.set(case)
    with tracing_installed():
        result = await ToolExecutor().execute("files_query", ALL_FILES_LIST, context)
    assert result.error is None
    (call,) = case.tool_calls
    assert call["tool"] == "files_query" and call["arguments"]["operation"] == "LIST"
    assert call["error"] is None and call["result"]["type"] == "FileListResult"
    assert call["result"]["returned"] == 1 and call["reads"] == [] and call["searches"] == []
    assert call["duration_ms"] >= 0 and execution_summary(case)["tool_names"] == ["files_query"]


async def test_the_executor_wrapper_records_a_whole_file_read_and_where_it_was_cut() -> None:
    chunks = [(uuid.UUID(int=i), uuid.UUID(int=300), i, "x" * 200, "policy.txt") for i in range(3)]
    context = make_context(FakeDb([eligible_file()], chunks, (3, 600)), budget=250)
    case = CaseTrace()
    trace_var.set(case)
    with tracing_installed():
        result = await ToolExecutor().execute(
            "file_evidence", evidence_args("FULL_DOCUMENT"), context
        )
    assert result.error is None, result.error.private_diagnostic if result.error else ""
    (call,) = case.tool_calls
    (read,) = call["reads"]
    assert read["trigger"] == "requested" and read["file"] == "policy.txt"
    assert [(r["chunk_index"], r["chars"]) for r in read["chunks_returned"]] == [(0, 200), (1, 50)]
    assert (
        read["chars_returned"] == 250 and read["total_chars"] == 600 and read["total_chunks"] == 3
    )
    assert (
        read["truncated"] is True
        and read["last_returned_chunk_index"] == 1
        and read["budget_chars"] == 250
    )
    assert call["result"]["mode"] == "FULL_DOCUMENT" and len(call["result"]["chunk_ids"]) == 2
    assert execution_summary(case)["whole_file_reads"] == 1


async def test_a_recovery_read_after_an_empty_focused_search_is_recorded_as_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def nothing(self: Any, request: Any, *, trace: Any = None) -> EvidenceGrade:
        return EvidenceGrade(sufficient=False, reason="none", chunks=[])

    monkeypatch.setattr(HybridRetriever, "retrieve_with_grade", nothing)
    rows = [(uuid.UUID(int=1), uuid.UUID(int=300), 0, "whole text", "policy.txt")]
    retriever = RecordingRetriever(SimpleNamespace(), target.eval_settings())  # type: ignore[arg-type]
    context = make_context(FakeDb([eligible_file()], rows, (1, 10)), retriever)
    case = CaseTrace()
    trace_var.set(case)
    with tracing_installed():
        await ToolExecutor().execute(
            "file_evidence", evidence_args("QUERY_FOCUSED", "late fees"), context
        )
    (call,) = case.tool_calls
    (read,) = call["reads"]
    assert read["trigger"] == "recovery" and read["truncated"] is False
    assert read["last_returned_chunk_index"] == 0
    (search,) = (
        case.searches
    )  # the bypassed read is not a search, but the focused search before it is
    assert search["query"] == "late fees" and search["scope"] == "files"
    assert search["tool_call"] == call["index"] == 1 and call["searches"] == [1]


async def test_a_search_tool_call_links_its_search_and_failures_are_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def found(self: Any, request: Any, *, trace: Any = None) -> EvidenceGrade:
        return EvidenceGrade(sufficient=True, reason="ok", chunks=[chunk(1, 0.7, "policy.txt")])

    monkeypatch.setattr(HybridRetriever, "retrieve_with_grade", found)
    retriever = RecordingRetriever(SimpleNamespace(), target.eval_settings())  # type: ignore[arg-type]
    context = make_context(FakeDb([eligible_file()], [], (0, 0)), retriever)
    case = CaseTrace()
    trace_var.set(case)
    with tracing_installed():
        ok = await ToolExecutor().execute(
            "search_knowledge",
            json.dumps({"query": "refund window", "scope": {"kind": "ALL_ELIGIBLE_INDEXED_FILES"}}),
            context,
        )
        bad = await ToolExecutor().execute("search_knowledge", "{not json", context)
        unknown = await ToolExecutor().execute("rm_rf", "{}", context)
    assert ok.error is None and bad.error is not None and unknown.error is not None
    first, second, third = case.tool_calls
    assert first["tool"] == "search_knowledge" and first["searches"] == [1]
    assert first["result"]["chunk_ids"] == [str(uuid.UUID(int=1))]
    assert second["arguments"] == {"unparsed": "{not json"} and second["error"] is not None
    assert third["tool"] == "UNKNOWN"
    assert case.searches[0]["chunks"][0]["filename"] == "policy.txt"
    assert execution_summary(case)["agent_queries"] == ["refund window"]


def test_the_wrapper_is_removed_after_the_run_and_never_nests_state() -> None:
    from app.agents.tool_rag.execution import executor as executor_module

    execute, read = ToolExecutor.execute, executor_module.full_document
    with tracing_installed():
        assert ToolExecutor.execute is not execute
    assert ToolExecutor.execute is execute and executor_module.full_document is read


async def test_concurrent_cases_keep_their_own_tool_calls_and_log_events() -> None:
    log = logging.getLogger("app.services.tool_agent_service")
    context = make_context(FakeDb([eligible_file()], [], (0, 0)))

    async def one(number: int) -> CaseTrace:
        case = CaseTrace()
        trace_var.set(case)
        for step in range(3):
            await asyncio.sleep(0.001 * ((number + step) % 3))
            await ToolExecutor().execute("files_query", ALL_FILES_COUNT, context)
            log.info("rag_execution %s", json.dumps({"path": "tool_agent", "llm_steps": number}))
        log.info("rag_execution path=claim_check outcome=REMOVED count=%d", number)
        return case

    with tracing_installed():
        cases = await asyncio.gather(*(asyncio.create_task(one(n)) for n in range(1, 5)))
    for number, case in zip(range(1, 5), cases, strict=True):
        assert [t["index"] for t in case.tool_calls] == [1, 2, 3]
        assert [e.get("llm_steps") for e in case.events if e["path"] == "tool_agent"] == [
            number
        ] * 3
        assert execution_summary(case)["claim_check_removed"] == number
        assert execution_summary(case)["agent_steps"] == number


async def test_log_lines_are_only_captured_while_installed_and_without_a_trace() -> None:
    log = logging.getLogger("app.agents.tool_rag.claim_check")
    case = CaseTrace()
    trace_var.set(case)
    log.info(
        "rag_execution path=claim_check outcome=CHECK_ERROR"
    )  # not installed: nothing recorded
    with tracing_installed():
        trace_var.set(None)
        log.info("rag_execution path=claim_check outcome=CHECK_ERROR")  # no case: nothing recorded
        trace_var.set(case)
        log.info("unrelated message")
        log.info("rag_execution path=claim_check outcome=CHECK_ERROR")
    assert case.events == [{"path": "claim_check", "outcome": "CHECK_ERROR"}]


async def test_after_an_unpriced_model_trips_the_meter_every_other_call_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spend is far below the cap, but a call that cannot be priced ends the whole run, not one case."""

    async def fake_chat(self: Any, *args: Any, **kwargs: Any) -> Any:
        return chat_reply(kwargs["model"], "{}", 10)

    monkeypatch.setattr(AsyncCompletions, "create", fake_chat)
    meter = CostMeter(5.0)
    case_var.set("a")
    with meter.installed():
        with pytest.raises(UnpricedModel):
            await sdk_chat(model="gpt-99-imaginary", messages=system(AGENT_SYSTEM_PROMPT))
        case_var.set("b")  # another case still in flight
        with pytest.raises(BudgetExceeded):
            await sdk_chat(model=NANO, messages=system(AGENT_SYSTEM_PROMPT))
    assert meter.exhausted and meter.total < 5.0 and {"a", "b"} <= meter.stopped_cases


def test_the_execution_summary_keeps_the_real_outcome_when_cleanup_fails_afterwards() -> None:
    case = CaseTrace(
        events=[
            {"path": "tool_agent", "outcome": "COMPLETED", "llm_steps": 2},
            {"path": "tool_agent", "outcome": "CLIENT_CLEANUP_ERROR"},
        ]
    )
    summary = execution_summary(case)
    assert summary["outcome"] == "COMPLETED" and summary["agent_steps"] == 2
    assert summary["cleanup_error"] is True


async def test_rescore_passes_cap_stopped_rows_through_without_judging_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    from types import SimpleNamespace as NS

    from evaluation.rag_eval import cli

    case = {**sample_case(1), "expected_behavior": "not_found", "must_include": []}
    row = runner.stopped_row(runner.base_row(case))
    path = tmp_path / "run.json"
    path.write_text(json.dumps({"model": NANO, "datasets": ["x.json"], "rows": [row]}))
    monkeypatch.setattr(cli, "corpus_files", lambda *, with_messy: [])
    monkeypatch.setattr(cli, "load_many", lambda names: {"cases": [case]})
    monkeypatch.setattr(cli, "eval_settings", lambda **kw: target.eval_settings())

    async def no_judge(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a cap-stopped row must not be judged")

    monkeypatch.setattr(runner, "judge", no_judge)
    args = NS(file=str(path), plan=False, cap=1.0, with_messy=False, dataset=["x.json"])
    await cli.rescore(args)
    out = json.loads((tmp_path / "run_rescored.json").read_text())
    assert out["rows"][0]["cap_stopped"] is True and out["rows"][0]["overall"] is None
    assert out["summary"]["incomplete"] is True and out["rescore_spend"]["estimated_total_usd"] == 0
