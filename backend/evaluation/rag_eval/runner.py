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
JUDGED = {"not_found", "decline_or_not_found", "correct_premise", "chitchat"}


def prepare(case: dict[str, Any], total_files: int) -> str:
    return str(case["question"]).replace("{TOTAL_FILES}", str(total_files))


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
        error = type(exc).__name__
    finally:
        label_var.reset(label)
    latency = perf_counter() - started
    seen = Observed(answer=answer, cited_files=cited, error=error)
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
        "evidence": evidence_score(case, seen),
        "answer": answer_score(case, seen),
        "refusal": None,
    }
    row["clean"] = clean_score(case, seen)
    if case["expected_behavior"] in JUDGED:
        verdict = (
            await judge(settings, case, answer)
            if answer
            else {"verdict": "fail", "reason": "no answer"}
        )
        row["refusal"] = {"ok": verdict["verdict"] == "ok", "reason": verdict["reason"]}
    row["overall"] = {"pass": overall(row)}
    return row


def overall(row: dict[str, Any]) -> bool:
    if row["error"]:
        return False
    parts = [
        row[k][
            "correct"
            if k == "answer"
            else "found"
            if k == "evidence"
            else "ok"
            if k == "refusal"
            else "clean"
        ]
        for k in ("answer", "evidence", "refusal", "clean")
        if row.get(k) is not None
    ]
    return all(parts)


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
    prepared = [{**c, "question": prepare(c, total)} for c in cases]

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
