"""What the agent really did for one case: its searches, tool calls, whole-file reads and log events.

Three recorders feed one ``CaseTrace`` per case, found through a context variable so that concurrent
cases never mix:

* ``RecordingRetriever`` (a ``HybridRetriever`` passed to ``RagService``) sees every hybrid search.
  It does NOT see whole-file reads, file listing or file-name lookup: those never call the retriever.
* ``tracing_installed()`` wraps the tool executor's entry and its whole-file read from outside, the way the
  meter wraps the SDK. That is where tool calls, their arguments and the cut of a whole-file read show up.
* One global log handler copies the application's ``rag_execution`` lines (steps, tool names, outcome,
  claim-check removals) onto the trace of the case whose task emitted them.

Nothing here changes what the application does, and nothing calls a provider.
"""

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from app.agents.tool_rag import contracts as c
from app.agents.tool_rag.execution import executor as executor_module
from app.agents.tool_rag.execution.context import ExecutionContext
from app.agents.tool_rag.execution.executor import ToolExecutionResult, ToolExecutor
from app.evaluation.trace import EvalTraceCollector
from app.retrieval.grade import EvidenceGrade
from app.retrieval.hybrid import HybridRetriever
from app.routing.intent_frame.execution import RetrievalRequest
from app.routing.intent_frame.scope import ResolvedFileScope

TRACE_SCHEMA_VERSION = 1
KNOWN_TOOLS = frozenset({"files_query", "resolve_file", "search_knowledge", "file_evidence"})
LOG_PREFIX = "rag_execution"


@dataclass
class CaseTrace:
    searches: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    current_tool: dict[str, Any] | None = None  # tools of one case run one after another

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": TRACE_SCHEMA_VERSION,
            "searches": self.searches,
            "tool_calls": self.tool_calls,
            "events": self.events,
        }


trace_var: ContextVar[CaseTrace | None] = ContextVar("case_trace", default=None)


def chunk_entry(rank: int, chunk: Any) -> dict[str, Any]:
    return {
        "rank": rank,
        "chunk_id": str(chunk.chunk_id),
        "filename": chunk.filename,
        "chunk_index": chunk.chunk_index,
        "score": round(chunk.score, 4),
        "fusion_score": None if chunk.fusion_score is None else round(chunk.fusion_score, 4),
        "sources": {name: round(value, 4) for name, value in chunk.source_scores.items()},
    }


class RecordingRetriever(HybridRetriever):
    """A hybrid retriever that notes each search and returns exactly what the real one returns.

    ``retrieve`` delegates to ``retrieve_with_grade``, and the legacy paths call that one directly, so it
    is the single place every search passes through.
    """

    async def retrieve_with_grade(
        self, request: RetrievalRequest, *, trace: EvalTraceCollector | None = None
    ) -> EvidenceGrade:
        record: dict[str, Any] = {
            "query": request.query,
            "scope": "files" if isinstance(request.scope, ResolvedFileScope) else "collection",
            "scope_files": len(request.scope.file_ids)
            if isinstance(request.scope, ResolvedFileScope)
            else None,
            "candidate_limit": request.candidate_limit,
        }
        case = trace_var.get()
        if case is not None:
            record["tool_call"] = case.current_tool["index"] if case.current_tool else None
            case.searches.append(record)
            if case.current_tool is not None:
                case.current_tool["searches"].append(len(case.searches))
        started = perf_counter()
        try:
            grade = await super().retrieve_with_grade(request, trace=trace)
        except Exception as exc:
            record.update(error=type(exc).__name__, duration_ms=_ms(started))
            raise
        record.update(
            duration_ms=_ms(started),
            sufficient=grade.sufficient,
            reason=grade.reason,
            chunks=[chunk_entry(rank, chunk) for rank, chunk in enumerate(grade.chunks, 1)],
        )
        return grade


def _ms(started: float) -> float:
    return round((perf_counter() - started) * 1000, 1)


def summarise_result(result: Any) -> dict[str, Any] | None:
    """The shape of what a tool returned: counts and chunk identifiers, never document text."""
    if isinstance(result, c.FilesQueryResult):
        value = result.result
        summary: dict[str, Any] = {"type": type(value).__name__}
        for name in ("count", "total_count"):
            if getattr(value, name, None) is not None:
                summary[name] = getattr(value, name)
        if hasattr(value, "items"):
            summary["returned"] = len(value.items)
        return summary
    if isinstance(result, c.ResolveFileResult):
        found = result.result
        summary = {"type": type(found).__name__}
        if hasattr(found, "candidates"):
            summary["candidates"] = len(found.candidates)
        return summary
    if isinstance(result, (c.SearchKnowledgeResult, c.FileEvidenceResult)):
        ids = [str(m.chunk_id) for s in result.sections for m in s.members]
        summary = {
            "type": type(result).__name__,
            "sections": len(result.sections),
            "chunk_ids": ids,
        }
        if isinstance(result, c.FileEvidenceResult):
            summary["mode"] = result.mode.value
        return summary
    return None


@contextmanager
def tracing_installed() -> Iterator[None]:
    """Wrap the tool executor and its whole-file read, and capture ``rag_execution`` log lines."""
    original_execute = ToolExecutor.execute
    original_read = executor_module.full_document

    async def execute(
        self: ToolExecutor, name: str, arguments_json: str, context: ExecutionContext
    ) -> ToolExecutionResult:
        case = trace_var.get()
        if case is None:
            return await original_execute(self, name, arguments_json, context)
        record: dict[str, Any] = {
            "index": len(case.tool_calls) + 1,
            "tool": name if name in KNOWN_TOOLS else "UNKNOWN",
            "arguments": _arguments(arguments_json),
            "searches": [],
            "reads": [],
        }
        case.tool_calls.append(record)
        case.current_tool = record
        started = perf_counter()
        try:
            result = await original_execute(self, name, arguments_json, context)
        finally:
            record["duration_ms"] = _ms(started)
            case.current_tool = None
        record["error"] = result.error.code.name if result.error else None
        if result.error and result.error.private_diagnostic:
            record["diagnostic"] = result.error.private_diagnostic[:300]
        record["result"] = summarise_result(result.internal_result)
        return result

    async def full_document(file_id: Any, context: ExecutionContext) -> c.FileEvidenceResult:
        result: c.FileEvidenceResult = await original_read(file_id, context)
        case = trace_var.get()
        if case is not None and case.current_tool is not None:
            case.current_tool["reads"].append(
                read_entry(case.current_tool, result, context.max_context_chars)
            )
        return result

    ToolExecutor.execute = execute  # type: ignore[method-assign]
    executor_module.full_document = full_document
    handler = _ExecutionLog()
    app_logger = logging.getLogger("app")
    level = app_logger.level
    if app_logger.getEffectiveLevel() > logging.INFO:
        app_logger.setLevel(logging.INFO)
    app_logger.addHandler(handler)
    try:
        yield
    finally:
        app_logger.removeHandler(handler)
        app_logger.setLevel(level)
        ToolExecutor.execute = original_execute  # type: ignore[method-assign]
        executor_module.full_document = original_read


def _arguments(arguments_json: str) -> Any:
    try:
        return json.loads(arguments_json)
    except ValueError:
        return {"unparsed": arguments_json[:200]}


def read_entry(tool: dict[str, Any], result: c.FileEvidenceResult, budget: int) -> dict[str, Any]:
    """One whole-file read: which chunks came back, how much, and where it was cut."""
    chunks = [m for section in result.sections for m in section.members]
    chars = sum(len(m.text) for m in chunks)
    coverage = result.coverage
    total_chars = coverage.total_chars if coverage else None
    truncated = total_chars is not None and chars < total_chars
    arguments = tool["arguments"]
    requested = (
        isinstance(arguments, dict) and arguments.get("mode") == c.EvidenceMode.FULL_DOCUMENT
    )
    return {
        "trigger": "requested" if requested else "recovery",
        "file": chunks[0].filename if chunks else None,
        "chunks_returned": [
            {"chunk_id": str(m.chunk_id), "chunk_index": m.chunk_index, "chars": len(m.text)}
            for m in chunks
        ],
        "chars_returned": chars,
        "total_chunks": coverage.total_chunks if coverage else None,
        "total_chars": total_chars,
        "truncated": truncated,
        # The prefix is clipped to the context budget, so the cut usually falls INSIDE this last chunk.
        "budget_chars": budget,
        "last_returned_chunk_index": chunks[-1].chunk_index if chunks else None,
    }


class _ExecutionLog(logging.Handler):
    """Copy ``rag_execution`` lines onto the trace of the case that logged them."""

    def emit(self, record: logging.LogRecord) -> None:
        case = trace_var.get()
        message = record.getMessage()
        if case is not None and message.startswith(LOG_PREFIX):
            case.events.append(parse_event(message[len(LOG_PREFIX) :].strip()))


def parse_event(body: str) -> dict[str, Any]:
    """``{"path": ...}`` JSON or ``key=value`` pairs, as the application writes them."""
    if body.startswith("{"):
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                return parsed
        except ValueError:
            pass
    return dict(pair.split("=", 1) for pair in body.split() if "=" in pair)


def execution_summary(trace: CaseTrace) -> dict[str, Any]:
    """Flat figures for scoring and optimisation, derived from the trace alone."""
    main = [e for e in trace.events if e.get("path") in {"tool_agent", "intent", "legacy"}]
    # a cleanup failure is logged after the real outcome and must not replace it
    final = next((e for e in reversed(main) if e.get("outcome") != "CLIENT_CLEANUP_ERROR"), {})
    removed = sum(int(e.get("count", 0)) for e in trace.events if e.get("path") == "claim_check")
    return {
        "path": final.get("path"),
        "outcome": final.get("outcome")
        or ("INTENT_REPLY" if final.get("path") == "intent" else None),
        "agent_steps": final.get("llm_steps"),
        "search_count": len(trace.searches),
        "agent_queries": [s["query"] for s in trace.searches],
        "tool_names": [t["tool"] for t in trace.tool_calls],
        "whole_file_reads": sum(len(t["reads"]) for t in trace.tool_calls),
        "claim_check_removed": removed,
        "cleanup_error": any(e.get("outcome") == "CLIENT_CLEANUP_ERROR" for e in main),
    }
