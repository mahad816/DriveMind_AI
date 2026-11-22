"""Run the golden cases through a real RagService pipeline and score every case."""

import asyncio
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from app.agents.tool_rag.finalization import FILE_NOT_FOUND_TEXT
from app.core.config import Settings
from app.services.rag_service import RagService

from .anchors import load_chunks, load_file_chunks, map_case_anchors
from .corpus import CorpusFile
from .deep import Resolved, extend_rows
from .judge import judge
from .meter import BudgetExceeded, CostMeter, case_var, label_var
from .pools import pool_of
from .schema_v3 import gate_groups
from .score import Observed, answer_score, clean_score, evidence_score, summarise
from .target import EVAL_USER_ID, session_factory
from .trace import (
    CaseTrace,
    RecordingRetriever,
    execution_summary,
    trace_var,
    tracing_installed,
)

PIPELINES = {"tool_agent": True, "legacy": False}  # value = tool_rag_agent_enabled
JUDGED = {"not_found", "decline_or_not_found", "correct_premise", "chitchat", "partial", "clarify"}
REFUSALS = {"not_found", "decline_or_not_found", "correct_premise"}


def describe_error(exc: BaseException) -> str:
    """Class names along the cause chain, e.g. 'ChatError<-TimeoutError'. Never message text."""
    names = [type(exc).__name__]
    cause = exc.__cause__ or exc.__context__
    while cause is not None and len(names) < 4:
        names.append(type(cause).__name__)
        cause = cause.__cause__ or cause.__context__
    return "<-".join(names)


def prepare(text: str, total_files: int) -> str:
    return text.replace("{TOTAL_FILES}", str(total_files))


def prepare_case(case: dict[str, Any], total_files: int) -> dict[str, Any]:
    """Fill the corpus-size placeholder in both the question and the expected facts."""
    return {
        **case,
        "question": prepare(case["question"], total_files),
        "must_include": [
            [prepare(alt, total_files) for alt in group] for group in case["must_include"]
        ],
    }


def base_row(
    case: dict[str, Any],
    *,
    reply: str = "",
    cited_files: Sequence[str] = (),
    error: str | None = None,
    latency_s: float | None = None,
) -> dict[str, Any]:
    return {
        "id": case["id"],
        "category": case["category"],
        "split": case["split"],
        "pool": pool_of(case),
        "gates": sorted(gate_groups(case)),
        "language": case["language"],
        "expected_behavior": case["expected_behavior"],
        "question": case["question"],
        "reply": reply,
        "cited_files": list(cited_files),
        "error": error,
        "latency_s": latency_s,
    }


def stopped_row(row: dict[str, Any]) -> dict[str, Any]:
    """The spend cap ended this case: it has no verdict and is left out of every rate."""
    row.update(
        cap_stopped=True,
        error="cap_stopped",
        evidence=None,
        answer=None,
        clean=None,
        refusal=None,
        overall=None,
    )
    return row


async def answer_case(
    settings: Settings,
    case: dict[str, Any],
    by_name: dict[str, str],
    pipeline: str,
    sessions: Any,
) -> dict[str, Any]:
    """Ask the real question-answering service once and record the reply and what it cited."""
    label = label_var.set(pipeline)
    started = perf_counter()
    answer, error = "", None
    cited: tuple[str, ...] = ()
    citations: list[dict[str, Any]] = []
    try:
        history = case.get("history") or ()
        async with sessions() as db:
            # Only the retriever is injected: a chat service or agent here would silently remove the
            # intent gate and the claim check. The tool agent always searches through the hybrid retriever.
            retriever = (
                RecordingRetriever(db, settings)
                if settings.tool_rag_agent_enabled or settings.hybrid_retrieval_enabled
                else None
            )
            service = RagService(db, settings, persist_query_history=False, retriever=retriever)
            result = await service.ask(
                case["question"],
                EVAL_USER_ID,
                conversation_id=str(uuid.uuid4()) if history else None,
                history=history,
                history_window_complete=bool(history),
            )
        answer = result.answer
        cited = tuple(dict.fromkeys(by_name.get(c.filename, c.filename) for c in result.citations))
        citations = [
            {
                "chunk_id": str(c.chunk_id),
                "file": by_name.get(c.filename, c.filename),
                "score": c.score,
                "snippet": c.snippet,
            }
            for c in result.citations
        ]
    except Exception as exc:  # one failing case must not end the run; record the class only
        # (BudgetExceeded is a BaseException and passes through: the cap ends the run.)
        error = describe_error(exc)
    finally:
        label_var.reset(label)
    row = base_row(
        case,
        reply=answer,
        cited_files=cited,
        error=error,
        latency_s=round(perf_counter() - started, 2),
    )
    row["cited"] = citations
    return row


async def run_case(
    settings: Settings,
    case: dict[str, Any],
    files: Sequence[CorpusFile],
    pipeline: str,
    sessions: Any,
    meter: CostMeter | None = None,
) -> dict[str, Any]:
    by_name = {f.name: f.path for f in files}
    # A key unique to this attempt: the same case id recurs across pipelines and repeats.
    key = f"{pipeline}/{case['id']}/{uuid.uuid4().hex[:8]}"
    trace = CaseTrace()
    case_token, trace_token = case_var.set(key), trace_var.set(trace)
    try:
        row = await answer_case(settings, case, by_name, pipeline, sessions)
        row = await judge_row(settings, case, score_row(case, row))
    except BudgetExceeded:
        row = stopped_row(base_row(case))
    finally:
        case_var.reset(case_token)
        trace_var.reset(trace_token)
    row["execution"] = execution_summary(trace)
    row["trace"] = trace.as_dict()
    if meter is not None:
        row["accounting"] = meter.case_accounting(key)
        if key in meter.stopped_cases and not row.get("cap_stopped"):
            stopped_row(
                row
            )  # the cap error was swallowed on the way up: still not a product failure
    return row


def score_row(case: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    """Deterministic stages, recomputable from the stored reply and citations alone."""
    seen = Observed(answer=row["reply"], cited_files=tuple(row["cited_files"]), error=row["error"])
    row.update(
        evidence=evidence_score(case, seen),
        answer=answer_score(case, seen),
        clean=clean_score(case, seen),
        refusal=None,
    )
    return row


async def judge_row(
    settings: Settings, case: dict[str, Any], row: dict[str, Any]
) -> dict[str, Any]:
    """(Re)compute the judged stage and the overall verdict from an already recorded reply."""
    if case["expected_behavior"] in JUDGED:
        answer = row["reply"]
        if not answer:
            verdict = {"verdict": "fail", "reason": "no answer"}
        elif case["expected_behavior"] == "clarify" and "?" not in answer:
            # The reply to an ambiguous question is a question. Code can see its absence; the judge decides
            # whether it is one short question that picks no reading.
            verdict = {"verdict": "fail", "reason": "no clarifying question in the reply"}
        elif answer.strip() == FILE_NOT_FOUND_TEXT and not case.get("names_a_file"):
            # Wrong route (KI-025): the agent looked for a *file* of that name and never searched the
            # text. It says "not found", so a grader that only reads the words would pass it. A case
            # whose question really names a file (``names_a_file``) is the one place this reply is right.
            verdict = {
                "verdict": "fail",
                "reason": "wrong route: file-name lookup, no content search",
            }
        else:
            verdict = await judge(settings, case, answer)
        row["refusal"] = {"ok": verdict["verdict"] == "ok", "reason": verdict["reason"]}
    row["overall"] = {"pass": overall(row, case["expected_behavior"])}
    return row


def overall(row: dict[str, Any], behavior: str | None = None) -> bool:
    """A case passes when every applicable stage passes.

    ``clean`` (no citation attached) is part of the verdict for small talk and inventory, where the
    product promises no citations. For refusals it is reported separately as citation noise: the
    serious failure there is an invented answer, which the judge and must_not_include already catch.
    """
    if row["error"]:
        return False
    stages = ["answer", "evidence", "refusal"]
    if (behavior or row.get("expected_behavior")) not in REFUSALS:
        stages.append("clean")
    keys = {"answer": "correct", "evidence": "found", "refusal": "ok", "clean": "clean"}
    return all(row[k][keys[k]] for k in stages if row.get(k) is not None)


async def load_resolved(
    sessions: Any,
    cases: dict[str, dict[str, Any]],
    rows: Sequence[dict[str, Any]],
    files: Sequence[CorpusFile],
) -> Resolved:
    """Chunk texts for the anchors of these cases and for every chunk the rows cite, from the evaluation
    database. If the database cannot be reached the rows are still scored, without chunk-level fields
    (a paid run is never lost to a free step)."""
    names = {f.path: f.name for f in files}
    wanted = {
        names[a["file"]]
        for c in cases.values()
        for a in c.get("evidence_anchors", [])
        if a["file"] in names
    }
    cited = {e["chunk_id"] for row in rows for e in row.get("cited") or []}
    try:
        async with sessions() as db:
            by_file = await load_file_chunks(db, EVAL_USER_ID, wanted)
            chunks = await load_chunks(db, cited)
    except Exception:
        return Resolved(names=names)
    if wanted - by_file.keys():  # an empty or re-built index: its chunk ids are not the run's
        return Resolved(names=names)
    anchors = {cid: map_case_anchors(case, by_file, names) for cid, case in cases.items()}
    texts = {chunk_id: text for chunk_list in by_file.values() for chunk_id, text in chunk_list}
    return Resolved(str(EVAL_USER_ID), names, chunks, texts, anchors, database=True)


async def extend_all(
    sessions: Any,
    cases: dict[str, dict[str, Any]],
    rows: Sequence[dict[str, Any]],
    files: Sequence[CorpusFile],
) -> list[dict[str, Any]]:
    """The deterministic scores of ``deep.py`` for every row (free: database reads only)."""
    return extend_rows(cases, rows, await load_resolved(sessions, cases, rows, files))


def pipeline_settings(settings: Settings, pipeline: str) -> Settings:
    return settings.model_copy(update={"tool_rag_agent_enabled": PIPELINES[pipeline]})


async def run_pipeline(
    settings: Settings,
    cases: Sequence[dict[str, Any]],
    files: Sequence[CorpusFile],
    pipeline: str,
    *,
    concurrency: int = 3,
    repeat: int = 1,
    meter: CostMeter | None = None,
) -> dict[str, Any]:
    chosen = pipeline_settings(settings, pipeline)
    sessions = session_factory(chosen)
    gate = asyncio.Semaphore(concurrency)
    total = len(files)
    prepared = [prepare_case(c, total) for c in cases]

    async def one(case: dict[str, Any]) -> dict[str, Any]:
        async with gate:
            if meter is not None and meter.exhausted:  # the cap was reached: start nothing new
                row = stopped_row(base_row(case))
                return {**row, "accounting": None, "execution": None, "trace": None}
            return await run_case(chosen, case, files, pipeline, sessions, meter)

    started = datetime.now(UTC)
    tasks = [asyncio.ensure_future(one(c)) for c in prepared]
    try:
        with tracing_installed():
            rows = await asyncio.gather(*tasks)
    except BaseException:  # the spend cap (or Ctrl-C): stop the cases still waiting or running
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    for row in rows:
        row["repeat"] = repeat
    try:
        rows = await extend_all(sessions, {c["id"]: c for c in prepared}, rows, files)
    except Exception as exc:  # the answers are paid for: keep them, say the free scores are missing
        for row in rows:
            row["extend_error"] = describe_error(exc)
    return {
        "pipeline": pipeline,
        "model": settings.chat_model,
        "started": started.isoformat(),
        "summary": summarise(list(rows)),
        "rows": list(rows),
    }
