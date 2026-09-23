"""In-memory execution traces for controlled RAG evaluation.

These traces are intentionally internal: they are not logged, persisted, or exposed
through the public chat API.  A collector is single-use and is only constructed by
evaluation callers that explicitly request instrumentation.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from time import perf_counter
from typing import TYPE_CHECKING, Literal
import uuid

if TYPE_CHECKING:
    from app.retrieval.query_router import QueryRoute
    from app.retrieval.types import RetrievedChunk
    from app.schemas.query import CitationItem

ExecutionPath = Literal[
    "conversation_history", "chitchat", "file_inventory", "file_target", "linear", "langgraph"
]


class TraceOutcome(StrEnum):
    """Terminal outcome of a traced question."""

    ANSWERED = "answered"
    ABSTAINED = "abstained"
    FAILED = "failed"


class AbstentionReason(StrEnum):
    """Explicit non-answer categories already present in production behavior."""

    NO_RETRIEVAL_EVIDENCE = "no_retrieval_evidence"
    EVIDENCE_REJECTED = "evidence_rejected"
    FILE_NOT_FOUND = "file_not_found"
    FILE_NOT_INDEXED = "file_not_indexed"


@dataclass(frozen=True)
class CandidateSnapshot:
    """Immutable, stage-specific view of one retrieved chunk."""

    chunk_id: uuid.UUID
    drive_file_id: uuid.UUID
    filename: str
    mime_type: str
    modified_at: datetime
    chunk_index: int
    rank: int
    score: float
    primary_source: str
    source_scores: tuple[tuple[str, float], ...]
    text: str
    text_truncated: bool = False


@dataclass(frozen=True)
class RetrieverResultTrace:
    """Ordered output and duration for one retriever invocation."""

    retriever: str
    candidates: tuple[CandidateSnapshot, ...]
    duration_ms: float


@dataclass(frozen=True)
class EvidenceTrace:
    """Evidence decision and the candidates accepted by that decision."""

    sufficient: bool
    reason: str
    accepted_candidates: tuple[CandidateSnapshot, ...]


@dataclass(frozen=True)
class RetrievalAttemptTrace:
    """One retrieval pass for an original or rewritten query."""

    attempt_number: int
    working_query: str
    active_retrievers: tuple[str, ...]
    retriever_results: tuple[RetrieverResultTrace, ...] = ()
    merged_candidates: tuple[CandidateSnapshot, ...] = ()
    reranked_candidates: tuple[CandidateSnapshot, ...] = ()
    evidence: EvidenceTrace | None = None
    duration_ms: float | None = None


@dataclass(frozen=True)
class RewriteTrace:
    """A query rewrite between two retrieval attempts."""

    after_attempt: int
    input_query: str
    output_query: str
    evidence_reason: str
    source: str
    duration_ms: float


@dataclass(frozen=True)
class CitationSnapshot:
    """Immutable citation payload before or after normalization."""

    chunk_id: uuid.UUID
    drive_file_id: uuid.UUID
    filename: str
    snippet: str
    score: float | None


@dataclass(frozen=True)
class FileSnapshot:
    """Minimal route-level file identity."""

    file_id: str
    filename: str
    status: str | None = None


@dataclass(frozen=True)
class ErrorTrace:
    """First fatal error observed during a traced call."""

    stage: str
    exception_type: str
    message: str
    component: str | None = None


@dataclass
class EvalTrace:
    """Collected facts for one production RagService execution."""

    question: str = ""
    route: QueryRoute | None = None
    execution_path: ExecutionPath | None = None
    graph_intent: str | None = None
    retrieval_plan: tuple[str, ...] = ()
    attempts: list[RetrievalAttemptTrace] = field(default_factory=list)
    rewrites: list[RewriteTrace] = field(default_factory=list)

    inventory_total_count: int | None = None
    inventory_files: tuple[FileSnapshot, ...] = ()
    inventory_context: str | None = None
    file_targets: tuple[str, ...] = ()
    resolved_target_files: tuple[FileSnapshot, ...] = ()
    loaded_target_chunks: tuple[CandidateSnapshot, ...] = ()

    prompt_chunks: tuple[CandidateSnapshot, ...] = ()
    raw_answer: str | None = None
    pre_normalization_citations: tuple[CitationSnapshot, ...] = ()
    final_answer: str | None = None
    final_citations: tuple[CitationSnapshot, ...] = ()

    outcome: TraceOutcome | None = None
    abstention_reason: AbstentionReason | None = None
    total_duration_ms: float | None = None
    retrieval_duration_ms: float = 0.0
    generation_duration_ms: float = 0.0
    error: ErrorTrace | None = None


def snapshot_candidates(
    chunks: list[RetrievedChunk],
    *,
    original_chunks: list[RetrievedChunk] | None = None,
) -> tuple[CandidateSnapshot, ...]:
    """Copy chunks immediately so later stages cannot change their interpretation."""
    original_text = (
        {chunk.chunk_id: chunk.text for chunk in original_chunks}
        if original_chunks is not None
        else {}
    )
    return tuple(
        CandidateSnapshot(
            chunk_id=chunk.chunk_id,
            drive_file_id=chunk.drive_file_id,
            filename=chunk.filename,
            mime_type=chunk.mime_type,
            modified_at=chunk.modified_at,
            chunk_index=chunk.chunk_index,
            rank=rank,
            score=float(chunk.score),
            primary_source=chunk.primary_source,
            source_scores=tuple(
                sorted((str(source), float(score)) for source, score in chunk.source_scores.items())
            ),
            text=chunk.text,
            text_truncated=(
                chunk.chunk_id in original_text and chunk.text != original_text[chunk.chunk_id]
            ),
        )
        for rank, chunk in enumerate(chunks, start=1)
    )


def snapshot_citations(citations: list[CitationItem]) -> tuple[CitationSnapshot, ...]:
    """Copy citation models into immutable evaluation values."""
    return tuple(
        CitationSnapshot(
            chunk_id=citation.chunk_id,
            drive_file_id=citation.drive_file_id,
            filename=citation.filename,
            snippet=citation.snippet,
            score=citation.score,
        )
        for citation in citations
    )


class EvalTraceCollector:
    """Single-use recorder for one explicitly traced RagService call."""

    def __init__(self) -> None:
        self.trace = EvalTrace()
        self._started_at: float | None = None
        self._attempt_started_at: dict[int, float] = {}
        self._finished = False
        self._current_stage = "initialization"

    def start(self, question: str) -> None:
        if self._started_at is not None:
            raise RuntimeError("EvalTraceCollector is single-use")
        self.trace.question = question
        self._started_at = perf_counter()

    def set_stage(self, stage: str) -> None:
        self._ensure_open()
        self._current_stage = stage

    def record_route(self, route: QueryRoute, path: ExecutionPath) -> None:
        self.trace.route = route
        self.trace.execution_path = path

    def record_graph_plan(self, *, intent: str, retrievers: tuple[str, ...]) -> None:
        self.trace.graph_intent = intent
        self.trace.retrieval_plan = retrievers

    def record_inventory(
        self,
        *,
        total_count: int,
        files: tuple[FileSnapshot, ...],
        context: str,
    ) -> None:
        self.trace.inventory_total_count = total_count
        self.trace.inventory_files = files
        self.trace.inventory_context = context

    def record_file_target(
        self,
        *,
        targets: tuple[str, ...],
        files: tuple[FileSnapshot, ...],
        chunks: list[RetrievedChunk],
    ) -> None:
        self.trace.file_targets = targets
        self.trace.resolved_target_files = files
        self.trace.loaded_target_chunks = snapshot_candidates(chunks)

    def begin_attempt(
        self,
        *,
        attempt_number: int,
        working_query: str,
        active_retrievers: tuple[str, ...],
    ) -> None:
        attempt = RetrievalAttemptTrace(
            attempt_number=attempt_number,
            working_query=working_query,
            active_retrievers=active_retrievers,
        )
        self.trace.attempts.append(attempt)
        self._attempt_started_at[attempt_number] = perf_counter()

    def record_retriever_result(
        self,
        attempt_number: int,
        retriever: str,
        chunks: list[RetrievedChunk],
        duration_ms: float,
    ) -> None:
        attempt = self._attempt(attempt_number)
        result = RetrieverResultTrace(
            retriever=retriever,
            candidates=snapshot_candidates(chunks),
            duration_ms=duration_ms,
        )
        self._replace_attempt(
            attempt_number,
            replace(attempt, retriever_results=attempt.retriever_results + (result,)),
        )

    def record_merged(self, attempt_number: int, chunks: list[RetrievedChunk]) -> None:
        attempt = self._attempt(attempt_number)
        self._replace_attempt(
            attempt_number,
            replace(attempt, merged_candidates=snapshot_candidates(chunks)),
        )

    def record_reranked(self, attempt_number: int, chunks: list[RetrievedChunk]) -> None:
        attempt = self._attempt(attempt_number)
        self._replace_attempt(
            attempt_number,
            replace(attempt, reranked_candidates=snapshot_candidates(chunks)),
        )

    def record_evidence(
        self,
        attempt_number: int,
        *,
        sufficient: bool,
        reason: str,
        chunks: list[RetrievedChunk],
    ) -> None:
        attempt = self._attempt(attempt_number)
        evidence = EvidenceTrace(
            sufficient=sufficient,
            reason=reason,
            accepted_candidates=snapshot_candidates(chunks),
        )
        self._replace_attempt(attempt_number, replace(attempt, evidence=evidence))

    def finish_attempt(self, attempt_number: int) -> None:
        started_at = self._attempt_started_at.pop(attempt_number)
        duration_ms = _elapsed_ms(started_at)
        attempt = self._attempt(attempt_number)
        self._replace_attempt(attempt_number, replace(attempt, duration_ms=duration_ms))
        self.trace.retrieval_duration_ms += duration_ms

    def record_rewrite(
        self,
        *,
        after_attempt: int,
        input_query: str,
        output_query: str,
        evidence_reason: str,
        source: str,
        duration_ms: float,
    ) -> None:
        self.trace.rewrites.append(
            RewriteTrace(
                after_attempt=after_attempt,
                input_query=input_query,
                output_query=output_query,
                evidence_reason=evidence_reason,
                source=source,
                duration_ms=duration_ms,
            )
        )

    def record_prompt_chunks(
        self,
        chunks: list[RetrievedChunk],
        *,
        original_chunks: list[RetrievedChunk],
    ) -> None:
        self.trace.prompt_chunks = snapshot_candidates(chunks, original_chunks=original_chunks)

    def record_raw_generation(
        self,
        answer: str,
        citations: list[CitationItem],
        *,
        duration_ms: float,
    ) -> None:
        self.trace.raw_answer = answer
        self.trace.pre_normalization_citations = snapshot_citations(citations)
        self.trace.generation_duration_ms += duration_ms

    def record_final(
        self,
        answer: str,
        citations: list[CitationItem],
        *,
        outcome: TraceOutcome = TraceOutcome.ANSWERED,
    ) -> None:
        self.trace.final_answer = answer
        self.trace.final_citations = snapshot_citations(citations)
        self.trace.outcome = outcome

    def record_abstention(self, reason: AbstentionReason, answer: str) -> None:
        self.trace.abstention_reason = reason
        self.record_final(answer, [], outcome=TraceOutcome.ABSTAINED)

    def record_error(
        self,
        exc: Exception,
        *,
        stage: str | None = None,
        component: str | None = None,
    ) -> None:
        if self.trace.error is None:
            self.trace.error = ErrorTrace(
                stage=stage or self._current_stage,
                exception_type=type(exc).__name__,
                message=str(exc),
                component=component,
            )
        self.trace.outcome = TraceOutcome.FAILED

    def add_retrieval_duration(self, duration_ms: float) -> None:
        self.trace.retrieval_duration_ms += duration_ms

    def finish(self) -> None:
        if self._finished:
            return
        if self._started_at is not None:
            self.trace.total_duration_ms = _elapsed_ms(self._started_at)
        self._finished = True

    def _attempt(self, attempt_number: int) -> RetrievalAttemptTrace:
        for attempt in self.trace.attempts:
            if attempt.attempt_number == attempt_number:
                return attempt
        raise ValueError(f"Unknown retrieval attempt: {attempt_number}")

    def _replace_attempt(
        self,
        attempt_number: int,
        updated: RetrievalAttemptTrace,
    ) -> None:
        for index, attempt in enumerate(self.trace.attempts):
            if attempt.attempt_number == attempt_number:
                self.trace.attempts[index] = updated
                return
        raise ValueError(f"Unknown retrieval attempt: {attempt_number}")

    def _ensure_open(self) -> None:
        if self._finished:
            raise RuntimeError("EvalTraceCollector has already finished")


def elapsed_ms(started_at: float) -> float:
    """Return elapsed monotonic time in milliseconds."""
    return _elapsed_ms(started_at)


def _elapsed_ms(started_at: float) -> float:
    return (perf_counter() - started_at) * 1000.0
