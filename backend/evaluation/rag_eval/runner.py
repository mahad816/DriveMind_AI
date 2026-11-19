"""Run the golden cases through a real RagService pipeline and score every case."""

import asyncio
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from app.core.config import Settings
from app.services.rag_service import RagService

from .corpus import CorpusFile
from .judge import judge
from .meter import BudgetExceeded, label_var
from .score import Observed, answer_score, clean_score, evidence_score, summarise
from .target import EVAL_USER_ID, session_factory

PIPELINES = {"tool_agent": True, "legacy": False}  # value = tool_rag_agent_enabled
JUDGED = {"not_found", "decline_or_not_found", "correct_premise", "chitchat", "partial"}
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


async def run_case(
    settings: Settings,
    case: dict[str, Any],
    files: Sequence[CorpusFile],
    pipeline: str,
    sessions: Any,
) -> dict[str, Any]:
    by_name = {f.name: f.path for f in files}
    label = label_var.set(pipeline)
    started = perf_counter()
    answer, error = "", None
    cited: tuple[str, ...] = ()
    try:
        history = case.get("history") or ()
        async with sessions() as db:
            service = RagService(db, settings, persist_query_history=False)
            result = await service.ask(
                case["question"],
                EVAL_USER_ID,
                conversation_id=str(uuid.uuid4()) if history else None,
                history=history,
                history_window_complete=bool(history),
            )
        answer = result.answer
        cited = tuple(dict.fromkeys(by_name.get(c.filename, c.filename) for c in result.citations))
    except BudgetExceeded:
        raise
    except Exception as exc:  # one failing case must not end the run; record the class only
        error = describe_error(exc)
    finally:
        label_var.reset(label)
    latency = perf_counter() - started
    row: dict[str, Any] = {
        "id": case["id"],
        "category": case["category"],
        "split": case["split"],
        "language": case["language"],
        "expected_behavior": case["expected_behavior"],
        "question": case["question"],
        "reply": answer,
        "cited_files": list(cited),
        "error": error,
        "latency_s": round(latency, 2),
    }
    return await judge_row(settings, case, score_row(case, row))


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
        verdict = (
            await judge(settings, case, answer)
            if answer
            else {"verdict": "fail", "reason": "no answer"}
        )
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


async def run_pipeline(
    settings: Settings,
    cases: Sequence[dict[str, Any]],
    files: Sequence[CorpusFile],
    pipeline: str,
    *,
    concurrency: int = 3,
) -> dict[str, Any]:
    pipeline_settings = settings.model_copy(update={"tool_rag_agent_enabled": PIPELINES[pipeline]})
    sessions = session_factory(pipeline_settings)
    gate = asyncio.Semaphore(concurrency)
    total = len(files)
    prepared = [prepare_case(c, total) for c in cases]

    async def one(case: dict[str, Any]) -> dict[str, Any]:
        async with gate:
            return await run_case(pipeline_settings, case, files, pipeline, sessions)

    started = datetime.now(UTC)
    rows = await asyncio.gather(*(one(c) for c in prepared))
    return {
        "pipeline": pipeline,
        "model": settings.chat_model,
        "started": started.isoformat(),
        "summary": summarise(list(rows)),
        "rows": list(rows),
    }
