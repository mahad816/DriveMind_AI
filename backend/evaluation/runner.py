"""Sequential production-pipeline runner for controlled DriveMind evaluation.

The module is safe on import and requires an explicit ``--execute-gold`` CLI flag
before any real dataset execution. Tests exercise the orchestration with synthetic
services and traces; importing this module never contacts a provider or datastore.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import statistics
import subprocess
import sys
import tempfile
import uuid
from collections import Counter
from collections.abc import Callable, Coroutine, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, AsyncContextManager, Protocol

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.enums import DriveFileStatus
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.db.models.google_oauth_token import GoogleOAuthToken
from app.db.models.user import User
from app.db.session import SessionLocal
from app.evaluation.trace import (
    CandidateSnapshot,
    CitationSnapshot,
    EvalTrace,
    EvalTraceCollector,
    RetrievalAttemptTrace,
    TraceOutcome,
)
from app.ingestion.hash_util import compute_extracted_text_hash
from app.services.rag_service import RagResult, RagService
from evaluation.dataset import EvaluationCase, EvaluationDataset, load_dataset
from evaluation.metrics import (
    FileRankingMetrics,
    PhraseMatch,
    all_expected_files_at_k,
    citation_metrics,
    expected_file_stage_survival,
    file_hit_at_k,
    file_ranking_metrics,
    file_recall_at_k,
    must_include_metrics,
    must_not_phrase_flags,
    phrase_matches,
    prompt_source_metrics,
    route_matches,
)

RESULT_SCHEMA_VERSION = "1.0"
BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
DEFAULT_DATASET_PATH = BACKEND_ROOT / "evaluation" / "datasets" / "gold_v1.json"
DEFAULT_RESULTS_DIR = BACKEND_ROOT / "evaluation" / "results"

JsonObject = dict[str, Any]


class EvaluationPreflightError(RuntimeError):
    """Raised before case execution when the baseline environment is unsafe."""


class EvaluationService(Protocol):
    """Narrow production-service contract used by the sequential executor."""

    async def ask(
        self,
        question: str,
        user_id: uuid.UUID | None = None,
        *,
        trace: EvalTraceCollector | None = None,
    ) -> RagResult: ...


class ServiceFactory(Protocol):
    """Factory shape that keeps query-history suppression explicit and testable."""

    def __call__(
        self,
        db: AsyncSession,
        settings: Settings,
        *,
        persist_query_history: bool,
    ) -> EvaluationService: ...


class CorpusVectorReader(Protocol):
    """Read-only Qdrant contract required by corpus preflight."""

    async def points_for_drive_file(
        self, drive_file_id: uuid.UUID
    ) -> tuple["VectorPayloadSnapshot", ...]: ...


SessionFactory = Callable[[], AsyncContextManager[AsyncSession]]
CollectorFactory = Callable[[], EvalTraceCollector]
BaselineCommand = Callable[..., Coroutine[Any, Any, Path]]


@dataclass(frozen=True)
class GitState:
    """Repository identity attached to an evaluation run."""

    sha: str
    branch: str
    dirty: bool


@dataclass(frozen=True)
class CorpusPreflight:
    """Read-only verified corpus manifest and fingerprint."""

    user_id: uuid.UUID
    manifest: tuple[JsonObject, ...]
    fingerprint_sha256: str


@dataclass(frozen=True)
class RunPreflight:
    """All metadata validated before production RAG is invoked."""

    dataset: EvaluationDataset
    dataset_path: Path
    dataset_sha256: str
    git: GitState
    configuration: JsonObject
    corpus: CorpusPreflight


@dataclass(frozen=True)
class VectorPayloadSnapshot:
    """Identity fields read from one Qdrant point and its payload."""

    point_id: str
    chunk_id: str | None
    drive_file_id: str | None
    filename: str | None
    extracted_text_hash: str | None


class QdrantCorpusReader:
    """Read Qdrant payload identities without exposing mutation operations."""

    def __init__(self, client: AsyncQdrantClient, collection_name: str) -> None:
        self.client = client
        self.collection_name = collection_name

    async def points_for_drive_file(
        self, drive_file_id: uuid.UUID
    ) -> tuple[VectorPayloadSnapshot, ...]:
        points: list[VectorPayloadSnapshot] = []
        offset: Any = None
        while True:
            records, offset = await self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=Filter(
                    must=[
                        FieldCondition(
                            key="drive_file_id",
                            match=MatchValue(value=str(drive_file_id)),
                        )
                    ]
                ),
                limit=100,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for record in records:
                payload = record.payload or {}
                points.append(
                    VectorPayloadSnapshot(
                        point_id=str(record.id),
                        chunk_id=_optional_string(payload.get("chunk_id")),
                        drive_file_id=_optional_string(payload.get("drive_file_id")),
                        filename=_optional_string(payload.get("filename")),
                        extracted_text_hash=_optional_string(payload.get("extracted_text_hash")),
                    )
                )
            if offset is None:
                break
        return tuple(sorted(points, key=lambda point: point.point_id))


def file_sha256(path: str | Path) -> str:
    """Return SHA-256 for the exact bytes of a file."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def capture_git_state(repo_root: Path = REPO_ROOT) -> GitState:
    """Read current SHA, branch, and dirty state without changing Git."""
    sha = _git_output(repo_root, "rev-parse", "HEAD")
    branch = _git_output(repo_root, "branch", "--show-current") or "DETACHED"
    dirty = bool(_git_output(repo_root, "status", "--porcelain"))
    return GitState(sha=sha, branch=branch, dirty=dirty)


def require_clean_git(git: GitState, *, allow_dirty: bool = False) -> None:
    """Reject a dirty baseline unless an explicitly unsafe override is supplied."""
    if git.dirty and not allow_dirty:
        raise EvaluationPreflightError(
            "Refusing to execute a baseline from a dirty working tree. "
            "Use --allow-dirty only for deliberate debug runs."
        )


def configuration_snapshot(settings: Settings) -> JsonObject:
    """Return only non-secret RAG settings that can affect evaluation behavior."""
    return {
        "chat_model": settings.chat_model,
        "chat_temperature": None,
        "embedding_model": settings.embedding_model,
        "hybrid_retrieval_enabled": settings.hybrid_retrieval_enabled,
        "agent_graph_enabled": settings.agent_graph_enabled,
        "retrieval_candidate_k": settings.retrieval_candidate_k,
        "retrieval_top_k": settings.retrieval_top_k,
        "retrieval_score_threshold": settings.retrieval_score_threshold,
        "hybrid_rrf_k": settings.hybrid_rrf_k,
        "hybrid_weight_vector": settings.hybrid_weight_vector,
        "hybrid_weight_keyword": settings.hybrid_weight_keyword,
        "hybrid_weight_metadata": settings.hybrid_weight_metadata,
        "evidence_min_fusion_score": settings.evidence_min_fusion_score,
        "rag_max_context_chars": settings.rag_max_context_chars,
        "agent_max_rewrite_attempts": settings.agent_max_rewrite_attempts,
        "rewrite_temperature": 0.1,
        "qdrant_collection": settings.qdrant_collection,
        "fts_language": settings.fts_language,
    }


def corpus_fingerprint(manifest: Sequence[Mapping[str, Any]]) -> str:
    """Hash a canonical, filename/ID-sorted corpus manifest."""
    ordered = sorted(
        (dict(entry) for entry in manifest),
        key=lambda entry: (str(entry.get("filename", "")), str(entry.get("drive_file_id", ""))),
    )
    payload = json.dumps(ordered, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def build_preflight(
    dataset_path: str | Path,
    *,
    settings: Settings,
    allow_dirty: bool = False,
    requested_user_id: uuid.UUID | None = None,
    session_factory: SessionFactory = SessionLocal,
    vector_reader_factory: Callable[[Settings], CorpusVectorReader] | None = None,
    git_state: GitState | None = None,
) -> RunPreflight:
    """Validate Git, dataset, user, PostgreSQL corpus, and Qdrant before generation."""
    path = Path(dataset_path).resolve()
    dataset = load_dataset(path)
    git = git_state or capture_git_state()
    require_clean_git(git, allow_dirty=allow_dirty)

    async with session_factory() as db:
        user_id = await resolve_evaluation_user(db, requested_user_id)
        expected_filenames = tuple(
            sorted({filename for case in dataset.cases for filename in case.expected_files})
        )
        if vector_reader_factory is not None:
            reader = vector_reader_factory(settings)
            corpus = await verify_corpus(db, reader, user_id, expected_filenames)
        else:
            client = AsyncQdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
            try:
                reader = QdrantCorpusReader(client, settings.qdrant_collection)
                corpus = await verify_corpus(db, reader, user_id, expected_filenames)
            finally:
                await client.close()

    return RunPreflight(
        dataset=dataset,
        dataset_path=path,
        dataset_sha256=file_sha256(path),
        git=git,
        configuration=configuration_snapshot(settings),
        corpus=corpus,
    )


async def resolve_evaluation_user(
    db: AsyncSession,
    requested_user_id: uuid.UUID | None,
) -> uuid.UUID:
    """Resolve exactly one OAuth-linked user, or validate an explicit selection."""
    statement = select(User.id).join(GoogleOAuthToken, GoogleOAuthToken.user_id == User.id)
    if requested_user_id is not None:
        selected = await db.scalar(statement.where(User.id == requested_user_id))
        if selected is None:
            raise EvaluationPreflightError("Requested evaluation user is not OAuth-connected")
        return selected

    user_ids = list((await db.scalars(statement.order_by(User.id))).all())
    if not user_ids:
        raise EvaluationPreflightError("No OAuth-connected evaluation user exists")
    if len(user_ids) != 1:
        raise EvaluationPreflightError(
            "Multiple OAuth-connected users exist; provide --user-id explicitly"
        )
    return user_ids[0]


async def verify_corpus(
    db: AsyncSession,
    vector_reader: CorpusVectorReader,
    user_id: uuid.UUID,
    expected_filenames: Sequence[str],
) -> CorpusPreflight:
    """Verify each gold source is uniquely indexed with PostgreSQL and Qdrant data."""
    if not expected_filenames:
        return CorpusPreflight(
            user_id=user_id, manifest=(), fingerprint_sha256=corpus_fingerprint(())
        )

    rows = list(
        (
            await db.scalars(
                select(DriveFile)
                .where(
                    DriveFile.user_id == user_id,
                    DriveFile.name.in_(expected_filenames),
                )
                .order_by(DriveFile.name, DriveFile.id)
            )
        ).all()
    )
    by_name: dict[str, list[DriveFile]] = {}
    for row in rows:
        by_name.setdefault(row.name, []).append(row)

    manifest: list[JsonObject] = []
    for filename in expected_filenames:
        matches = by_name.get(filename, [])
        if len(matches) != 1:
            raise EvaluationPreflightError(
                f"Expected exactly one DriveFile named {filename!r}; found {len(matches)}"
            )
        drive_file = matches[0]
        if drive_file.status is not DriveFileStatus.INDEXED:
            raise EvaluationPreflightError(
                f"Corpus file {filename!r} is {drive_file.status.name}, not INDEXED"
            )

        documents = list(
            (
                await db.scalars(
                    select(Document)
                    .where(Document.drive_file_id == drive_file.id)
                    .order_by(Document.id)
                )
            ).all()
        )
        if len(documents) != 1:
            raise EvaluationPreflightError(
                f"Expected one Document for {filename!r}; found {len(documents)}"
            )
        document = documents[0]
        if not document.extracted_text or not document.extracted_text.strip():
            raise EvaluationPreflightError(
                f"Corpus file {filename!r} has empty extracted document text"
            )
        computed_text_hash = compute_extracted_text_hash(document.extracted_text)
        if document.extracted_text_hash != computed_text_hash:
            raise EvaluationPreflightError(
                f"Stored Document hash is stale for corpus file {filename!r}"
            )
        chunks = list(
            (
                await db.scalars(
                    select(Chunk)
                    .where(Chunk.document_id == document.id)
                    .order_by(Chunk.chunk_index, Chunk.id)
                )
            ).all()
        )
        if not chunks:
            raise EvaluationPreflightError(f"Corpus file {filename!r} has no chunks")
        for chunk in chunks:
            chunk_text_hash = chunk.metadata_json.get("extracted_text_hash")
            if chunk_text_hash != document.extracted_text_hash:
                raise EvaluationPreflightError(
                    f"Chunk source hash is stale for corpus file {filename!r} chunk {chunk.id}"
                )

        chunk_entries = [
            {
                "id": str(chunk.id),
                "chunk_index": chunk.chunk_index,
                "text_sha256": _text_sha256(chunk.text),
            }
            for chunk in chunks
        ]
        points = await vector_reader.points_for_drive_file(drive_file.id)
        _verify_vector_points(drive_file, chunks, points)
        manifest.append(
            {
                "drive_file_id": str(drive_file.id),
                "google_drive_id": drive_file.drive_file_id,
                "filename": drive_file.name,
                "mime_type": drive_file.mime_type,
                "status": drive_file.status.name,
                "modified_at": drive_file.modified_at.isoformat(),
                "indexed_at": drive_file.indexed_at.isoformat() if drive_file.indexed_at else None,
                "document_id": str(document.id),
                "extracted_text_sha256": computed_text_hash,
                "stored_extracted_text_hash": document.extracted_text_hash,
                "chunk_count": len(chunks),
                "qdrant_point_count": len(points),
                "chunks": chunk_entries,
            }
        )

    stable_manifest = tuple(
        sorted(manifest, key=lambda entry: (entry["filename"], entry["drive_file_id"]))
    )
    return CorpusPreflight(
        user_id=user_id,
        manifest=stable_manifest,
        fingerprint_sha256=corpus_fingerprint(stable_manifest),
    )


async def execute_cases(
    dataset: EvaluationDataset,
    *,
    user_id: uuid.UUID,
    settings: Settings,
    session_factory: SessionFactory = SessionLocal,
    service_factory: ServiceFactory = RagService,
    collector_factory: CollectorFactory = EvalTraceCollector,
) -> list[JsonObject]:
    """Execute cases sequentially with fresh sessions, services, and collectors."""
    results: list[JsonObject] = []
    for case in dataset.cases:
        collector = collector_factory()
        result: RagResult | None = None
        caught: Exception | None = None
        try:
            async with session_factory() as db:
                service = service_factory(
                    db,
                    settings,
                    persist_query_history=False,
                )
                result = await service.ask(case.question, user_id=user_id, trace=collector)
        except Exception as exc:  # noqa: BLE001 - failures are evaluation results
            caught = exc
            if collector.trace.error is None:
                collector.record_error(exc, stage="runner_case")
            collector.finish()
        results.append(
            project_case_result(
                case, collector.trace, result=result, caught=caught, settings=settings
            )
        )
    return results


def project_case_result(
    case: EvaluationCase,
    trace: EvalTrace,
    *,
    result: RagResult | None,
    caught: Exception | None,
    settings: Settings,
) -> JsonObject:
    """Project one trace into compact JSON-safe diagnostics and deterministic metrics."""
    trace_record = project_trace(trace, case.evidence_anchors)
    observed_route = trace.route.name if trace.route is not None else None
    answer = (
        trace.final_answer if trace.final_answer is not None else (result.answer if result else "")
    )
    include = must_include_metrics(answer, case.must_include)
    prohibited = must_not_phrase_flags(answer, case.must_not_include)
    citations = citation_metrics(
        answer,
        [citation.filename for citation in trace.final_citations],
        case.expected_files,
    )

    attempts = tuple(trace.attempts)
    final_attempt = attempts[-1] if attempts else None
    attempt_metrics = [
        _attempt_metrics(
            attempt,
            case.expected_files,
            settings,
            prompt_filenames=(
                [candidate.filename for candidate in trace.prompt_chunks]
                if attempt is final_attempt
                else None
            ),
        )
        for attempt in attempts
    ]
    retrieval_metrics = (
        {
            "final_attempt": final_attempt.attempt_number,
            "attempts": attempt_metrics,
            "stages": attempt_metrics[-1]["stages"],
        }
        if final_attempt is not None
        else None
    )
    prompt_ranking = file_ranking_metrics(
        [candidate.filename for candidate in trace.prompt_chunks], case.expected_files
    )
    prompt_sources = prompt_source_metrics(
        [candidate.filename for candidate in trace.prompt_chunks], case.expected_files
    )
    prompt_anchor_matches = phrase_matches(
        "\n".join(candidate.text for candidate in trace.prompt_chunks),
        case.evidence_anchors,
    )
    attempt_expected_presence = [
        _attempt_has_expected_file(attempt, case.expected_files) for attempt in attempts
    ]
    file_target_metrics = (
        _ranking_to_json(
            file_ranking_metrics(
                [file.filename for file in trace.resolved_target_files],
                case.expected_files,
            )
        )
        if case.expected_route == "FILE_TARGET" or observed_route == "FILE_TARGET"
        else None
    )
    expected_route_diagnostics_missing = (
        (case.expected_route == "GROUNDED_RAG" and not attempts)
        or (
            case.expected_route == "FILE_TARGET"
            and not trace.resolved_target_files
            and not trace.loaded_target_chunks
        )
        or (case.expected_route == "FILE_INVENTORY" and trace.inventory_total_count is None)
    )

    return {
        "id": case.id,
        "question": case.question,
        "expected": {
            "route": case.expected_route,
            "files": list(case.expected_files),
            "should_answer": case.should_answer,
            "reference_answer": case.reference_answer,
            "must_include": list(case.must_include),
            "must_not_include": list(case.must_not_include),
            "evidence_anchors": list(case.evidence_anchors),
            "tags": list(case.tags),
        },
        "status": "failed" if caught is not None else "completed",
        "trace": trace_record,
        "metrics": {
            "observed_route": observed_route,
            "route_correct": route_matches(case.expected_route, trace.route),
            "expected_route_diagnostics_missing": expected_route_diagnostics_missing,
            "retrieval": retrieval_metrics,
            "file_target": file_target_metrics,
            "prompt": {
                **_ranking_to_json(prompt_ranking),
                "prompt_expected_source_precision": prompt_sources.precision,
                "unexpected_prompt_source_count": prompt_sources.unexpected_count,
                "unexpected_prompt_sources": list(prompt_sources.unexpected_sources),
                "evidence_anchor_matches": _phrase_matches_to_json(prompt_anchor_matches),
                "evidence_anchor_coverage": _match_coverage(prompt_anchor_matches),
            },
            "answer": {
                "non_empty": bool(answer.strip()),
                "must_include_matches": _phrase_matches_to_json(include.matches),
                "must_include_coverage": include.coverage,
                "all_must_include_present": include.all_present,
                "must_not_flags": _phrase_matches_to_json(prohibited),
            },
            "citations": {
                "citation_count": citations.citation_count,
                "marker_count": citations.marker_count,
                "marker_indices": list(citations.marker_indices),
                "markers_valid": citations.markers_valid,
                "resolved_cited_filenames": list(citations.cited_filenames),
                "expected_file_recall": citations.expected_file_recall,
                "all_expected_files_cited": citations.all_expected_files_cited,
                "unexpected_cited_files": list(citations.unexpected_cited_files),
            },
            "abstention": {
                "outcome": trace.outcome.name if trace.outcome is not None else None,
                "reason": trace.abstention_reason.name if trace.abstention_reason else None,
                "false_pipeline_abstention": (
                    case.should_answer and trace.outcome is TraceOutcome.ABSTAINED
                ),
                "answered_when_should_answer_false": (
                    not case.should_answer and trace.outcome is TraceOutcome.ANSWERED
                ),
            },
            "rewrites": {
                "count": len(trace.rewrites),
                "expected_evidence_in_any_attempt": any(attempt_expected_presence),
                "rewrite_recovered_expected_file": (
                    bool(attempt_expected_presence)
                    and not attempt_expected_presence[0]
                    and any(attempt_expected_presence[1:])
                ),
            },
            "latency_ms": {
                "total": trace.total_duration_ms,
                "retrieval": trace.retrieval_duration_ms,
                "generation": trace.generation_duration_ms,
                "rewrite_total": sum(rewrite.duration_ms for rewrite in trace.rewrites),
            },
        },
        "error": (
            {
                "type": type(caught).__name__,
                "message": str(caught),
            }
            if caught is not None
            else None
        ),
    }


def project_trace(trace: EvalTrace, evidence_anchors: Sequence[str]) -> JsonObject:
    """Serialize trace diagnostics without persisting candidate or prompt text."""
    return {
        "route": trace.route.name if trace.route is not None else None,
        "execution_path": trace.execution_path,
        "graph_intent": trace.graph_intent,
        "retrieval_plan": list(trace.retrieval_plan),
        "attempts": [_project_attempt(attempt, evidence_anchors) for attempt in trace.attempts],
        "rewrites": [
            {
                "after_attempt": rewrite.after_attempt,
                "input_query": rewrite.input_query,
                "output_query": rewrite.output_query,
                "evidence_reason": rewrite.evidence_reason,
                "source": rewrite.source,
                "duration_ms": rewrite.duration_ms,
            }
            for rewrite in trace.rewrites
        ],
        "final_attempt": trace.attempts[-1].attempt_number if trace.attempts else None,
        "inventory": {
            "total_count": trace.inventory_total_count,
            "files": [_project_file(file) for file in trace.inventory_files],
        },
        "file_target": {
            "targets": list(trace.file_targets),
            "resolved_files": [_project_file(file) for file in trace.resolved_target_files],
            "loaded_chunks": [
                _project_candidate(candidate, evidence_anchors)
                for candidate in trace.loaded_target_chunks
            ],
        },
        "prompt_chunks": [
            _project_candidate(candidate, evidence_anchors) for candidate in trace.prompt_chunks
        ],
        "raw_answer": trace.raw_answer,
        "pre_normalization_citations": [
            _project_citation(citation, index)
            for index, citation in enumerate(trace.pre_normalization_citations, start=1)
        ],
        "final_answer": trace.final_answer,
        "final_citations": [
            _project_citation(citation, index)
            for index, citation in enumerate(trace.final_citations, start=1)
        ],
        "outcome": trace.outcome.name if trace.outcome is not None else None,
        "abstention_reason": trace.abstention_reason.name if trace.abstention_reason else None,
        "timings_ms": {
            "total": trace.total_duration_ms,
            "retrieval": trace.retrieval_duration_ms,
            "generation": trace.generation_duration_ms,
        },
        "error": (
            {
                "stage": trace.error.stage,
                "component": trace.error.component,
                "type": trace.error.exception_type,
                "message": trace.error.message,
            }
            if trace.error is not None
            else None
        ),
    }


def aggregate_results(cases: Sequence[Mapping[str, Any]]) -> JsonObject:
    """Aggregate completed case records while excluding not-applicable values."""
    completed = [case for case in cases if case.get("status") == "completed"]
    failed = [case for case in cases if case.get("status") == "failed"]
    route_pairs = [
        (
            str(_nested(case, "expected", "route")),
            _nested(case, "metrics", "observed_route"),
            _nested(case, "metrics", "route_correct"),
        )
        for case in completed
    ]
    confusion: dict[str, Counter[str]] = {}
    for expected, observed, _ in route_pairs:
        confusion.setdefault(expected, Counter())[str(observed or "UNOBSERVED")] += 1

    stage_values: dict[str, list[Mapping[str, Any]]] = {}
    for case in completed:
        retrieval = _nested(case, "metrics", "retrieval")
        if not isinstance(retrieval, Mapping):
            continue
        for stage, values in retrieval.get("stages", {}).items():
            if isinstance(values, Mapping):
                stage_values.setdefault(str(stage), []).append(values)

    latencies = _numeric_values(cases, "metrics", "latency_ms", "total")
    error_counts = Counter(
        (
            str(_nested(case, "trace", "error", "stage") or "unknown"),
            str(_nested(case, "trace", "error", "component") or "unknown"),
        )
        for case in failed
    )
    must_include_coverages = _numeric_values(
        completed, "metrics", "answer", "must_include_coverage"
    )
    citation_recalls = _numeric_values(completed, "metrics", "citations", "expected_file_recall")
    prompt_recalls = _numeric_values(completed, "metrics", "prompt", "expected_file_recall")
    prompt_precisions = _numeric_values(
        completed, "metrics", "prompt", "prompt_expected_source_precision"
    )
    unexpected_prompt_source_counts = _numeric_values(
        completed, "metrics", "prompt", "unexpected_prompt_source_count"
    )
    run_status = "completed" if not failed else ("partial_failure" if completed else "failed")

    return {
        "status": run_status,
        "cases_total": len(cases),
        "completed": len(completed),
        "failed": len(failed),
        "route_accuracy": _mean([bool(pair[2]) for pair in route_pairs]),
        "route_counts": {
            "expected": dict(sorted(Counter(pair[0] for pair in route_pairs).items())),
            "observed": dict(
                sorted(Counter(str(pair[1] or "UNOBSERVED") for pair in route_pairs).items())
            ),
        },
        "confusion_matrix": {
            expected: dict(sorted(observed.items()))
            for expected, observed in sorted(confusion.items())
        },
        "expected_route_diagnostics_missing_count": sum(
            _nested(case, "metrics", "expected_route_diagnostics_missing") is True
            for case in completed
        ),
        "retrieval_by_stage": {
            stage: {
                "applicable_cases": len(values),
                "mean_expected_file_recall": _mean(
                    [
                        float(value["expected_file_recall"])
                        for value in values
                        if value.get("expected_file_recall") is not None
                    ]
                ),
                "all_expected_files_count": sum(
                    value.get("all_expected_files") is True for value in values
                ),
                "at_k": _aggregate_at_k(values),
            }
            for stage, values in sorted(stage_values.items())
        },
        "prompt_expected_file_recall": _mean(prompt_recalls),
        "macro_prompt_expected_source_precision": _mean(prompt_precisions),
        "mean_unexpected_prompt_sources": _mean(unexpected_prompt_source_counts),
        "must_include_average_coverage": _mean(must_include_coverages),
        "all_must_include_pass_count": sum(
            _nested(case, "metrics", "answer", "all_must_include_present") is True
            for case in completed
        ),
        "must_not_diagnostic_flag_count": sum(
            match.get("matched") is True
            for case in completed
            for match in (_nested(case, "metrics", "answer", "must_not_flags") or [])
        ),
        "citation_source_recall": _mean(citation_recalls),
        "pipeline_abstention_count": sum(
            _nested(case, "metrics", "abstention", "outcome") == "ABSTAINED" for case in completed
        ),
        "false_pipeline_abstention_count": sum(
            _nested(case, "metrics", "abstention", "false_pipeline_abstention") is True
            for case in completed
        ),
        "answered_when_should_answer_false_count": sum(
            _nested(case, "metrics", "abstention", "answered_when_should_answer_false") is True
            for case in completed
        ),
        "rewrite_case_count": sum(
            int(_nested(case, "metrics", "rewrites", "count") or 0) > 0 for case in completed
        ),
        "rewrite_total_count": sum(
            int(_nested(case, "metrics", "rewrites", "count") or 0) for case in completed
        ),
        "errors_by_stage_component": [
            {"stage": stage, "component": component, "count": count}
            for (stage, component), count in sorted(error_counts.items())
        ],
        "latency_ms": {
            "median": statistics.median(latencies) if latencies else None,
            "p95": _nearest_rank_percentile(latencies, 0.95),
        },
    }


def build_result_document(
    preflight: RunPreflight,
    cases: Sequence[JsonObject],
    *,
    started_at: datetime,
    finished_at: datetime,
) -> JsonObject:
    """Build the machine-readable run artifact without corpus passages or secrets."""
    return {
        "result_schema_version": RESULT_SCHEMA_VERSION,
        "run": {
            "started_at": started_at.astimezone(UTC).isoformat(),
            "finished_at": finished_at.astimezone(UTC).isoformat(),
            "dataset": {
                "path": str(preflight.dataset_path),
                "dataset_id": preflight.dataset.dataset_id,
                "schema_version": preflight.dataset.schema_version,
                "corpus_id": preflight.dataset.corpus_id,
                "case_count": preflight.dataset.case_count,
                "sha256": preflight.dataset_sha256,
            },
            "git": {
                "sha": preflight.git.sha,
                "branch": preflight.git.branch,
                "dirty": preflight.git.dirty,
            },
            "configuration": preflight.configuration,
            "corpus": {
                "fingerprint_sha256": preflight.corpus.fingerprint_sha256,
                "file_count": len(preflight.corpus.manifest),
                "manifest": list(preflight.corpus.manifest),
            },
            "evaluation_user_id": str(preflight.corpus.user_id),
        },
        "summary": aggregate_results(cases),
        "cases": list(cases),
    }


def write_result_atomically(
    result: Mapping[str, Any],
    output_dir: str | Path,
    filename: str,
) -> Path:
    """Atomically publish a new JSON result and refuse to overwrite an existing file."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / filename
    if destination.exists():
        raise FileExistsError(f"Evaluation result already exists: {destination}")

    encoded = (json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".eval-", delete=False) as handle:
            temporary_path = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary_path, destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return destination


async def run_baseline(
    *,
    dataset_path: Path,
    output_dir: Path,
    allow_dirty: bool,
    requested_user_id: uuid.UUID | None,
) -> Path:
    """Preflight and execute the real sequential production RAG baseline."""
    settings = get_settings()
    preflight = await build_preflight(
        dataset_path,
        settings=settings,
        allow_dirty=allow_dirty,
        requested_user_id=requested_user_id,
    )
    print(json.dumps(_preflight_display(preflight), indent=2, sort_keys=True))

    started_at = datetime.now(UTC)
    cases = await execute_cases(
        preflight.dataset,
        user_id=preflight.corpus.user_id,
        settings=settings,
    )
    finished_at = datetime.now(UTC)
    result = build_result_document(
        preflight,
        cases,
        started_at=started_at,
        finished_at=finished_at,
    )
    timestamp = started_at.strftime("%Y%m%dT%H%M%SZ")
    safe_dataset_id = "".join(
        character if character.isalnum() or character in {"-", "_"} else "_"
        for character in preflight.dataset.dataset_id
    )
    filename = f"{safe_dataset_id}__{timestamp}__{preflight.git.sha[:8]}.json"
    return write_result_atomically(result, output_dir, filename)


def main(argv: Sequence[str] | None = None, *, command: BaselineCommand = run_baseline) -> int:
    """CLI entry point; explicit Gold execution authorization is mandatory."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not args.execute_gold:
        parser.print_help(sys.stderr)
        print("\nRefusing to execute: pass --execute-gold deliberately.", file=sys.stderr)
        return 2

    requested_user_id = uuid.UUID(args.user_id) if args.user_id else None
    artifact = asyncio.run(
        command(
            dataset_path=Path(args.dataset),
            output_dir=Path(args.output_dir),
            allow_dirty=args.allow_dirty,
            requested_user_id=requested_user_id,
        )
    )
    print(f"Evaluation result written to {artifact}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run DriveMind evaluation sequentially")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_RESULTS_DIR))
    parser.add_argument("--user-id", help="Explicit OAuth-linked user UUID")
    parser.add_argument(
        "--execute-gold",
        action="store_true",
        help="explicitly authorize real dataset execution and provider calls",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="UNSAFE: allow a debug run from a dirty Git worktree",
    )
    return parser


def _project_attempt(
    attempt: RetrievalAttemptTrace,
    evidence_anchors: Sequence[str],
) -> JsonObject:
    return {
        "attempt_number": attempt.attempt_number,
        "working_query": attempt.working_query,
        "active_retrievers": list(attempt.active_retrievers),
        "retrievers": [
            {
                "name": result.retriever,
                "duration_ms": result.duration_ms,
                "candidates": [
                    _project_candidate(candidate, evidence_anchors)
                    for candidate in result.candidates
                ],
            }
            for result in attempt.retriever_results
        ],
        "rrf_candidates": [
            _project_candidate(candidate, evidence_anchors)
            for candidate in attempt.merged_candidates
        ],
        "reranked_candidates": [
            _project_candidate(candidate, evidence_anchors)
            for candidate in attempt.reranked_candidates
        ],
        "evidence": (
            {
                "sufficient": attempt.evidence.sufficient,
                "reason": attempt.evidence.reason,
                "accepted_candidates": [
                    _project_candidate(candidate, evidence_anchors)
                    for candidate in attempt.evidence.accepted_candidates
                ],
            }
            if attempt.evidence is not None
            else None
        ),
        "duration_ms": attempt.duration_ms,
    }


def _project_candidate(
    candidate: CandidateSnapshot,
    evidence_anchors: Sequence[str],
) -> JsonObject:
    return {
        "chunk_id": str(candidate.chunk_id),
        "drive_file_id": str(candidate.drive_file_id),
        "filename": candidate.filename,
        "mime_type": candidate.mime_type,
        "modified_at": candidate.modified_at.isoformat(),
        "chunk_index": candidate.chunk_index,
        "rank": candidate.rank,
        "score": candidate.score,
        "primary_source": candidate.primary_source,
        "source_scores": [
            {"source": source, "score": score} for source, score in candidate.source_scores
        ],
        "text_length": len(candidate.text),
        "text_sha256": _text_sha256(candidate.text),
        "text_truncated": candidate.text_truncated,
        "evidence_anchor_matches": _phrase_matches_to_json(
            phrase_matches(candidate.text, evidence_anchors)
        ),
    }


def _project_citation(citation: CitationSnapshot, marker_index: int) -> JsonObject:
    return {
        "marker_index": marker_index,
        "chunk_id": str(citation.chunk_id),
        "drive_file_id": str(citation.drive_file_id),
        "filename": citation.filename,
        "score": citation.score,
        "snippet_length": len(citation.snippet),
        "snippet_sha256": _text_sha256(citation.snippet),
    }


def _project_file(file: Any) -> JsonObject:
    return {"file_id": file.file_id, "filename": file.filename, "status": file.status}


def _attempt_metrics(
    attempt: RetrievalAttemptTrace,
    expected_files: Sequence[str],
    settings: Settings,
    *,
    prompt_filenames: Sequence[str] | None = None,
) -> JsonObject:
    stages: dict[str, Sequence[str]] = {}
    for result in attempt.retriever_results:
        stages[f"raw_{result.retriever}"] = [candidate.filename for candidate in result.candidates]
    if attempt.merged_candidates:
        stages["rrf"] = [candidate.filename for candidate in attempt.merged_candidates]
    if attempt.reranked_candidates:
        stages["rerank"] = [candidate.filename for candidate in attempt.reranked_candidates]
    if attempt.evidence is not None:
        stages["evidence"] = [
            candidate.filename for candidate in attempt.evidence.accepted_candidates
        ]
    if prompt_filenames is not None:
        stages["prompt"] = prompt_filenames

    k_values = sorted({1, 3, settings.retrieval_top_k, settings.retrieval_candidate_k})
    survival = expected_file_stage_survival(stages, expected_files)
    return {
        "attempt_number": attempt.attempt_number,
        "stages": {
            stage.stage: {
                **_ranking_to_json(file_ranking_metrics(stages[stage.stage], expected_files)),
                "present_expected_files": list(stage.present_expected_files),
                "at_k": {
                    str(k): {
                        "hit": file_hit_at_k(stages[stage.stage], expected_files, k),
                        "recall": file_recall_at_k(stages[stage.stage], expected_files, k),
                        "all_expected_files": all_expected_files_at_k(
                            stages[stage.stage], expected_files, k
                        ),
                    }
                    for k in k_values
                },
            }
            for stage in survival
        },
    }


def _ranking_to_json(metrics: FileRankingMetrics) -> JsonObject:
    return {
        "any_expected_file": metrics.any_expected_file,
        "expected_file_recall": metrics.expected_file_recall,
        "all_expected_files": metrics.all_expected_files,
        "first_relevant_reciprocal_rank": metrics.first_relevant_reciprocal_rank,
        "reciprocal_rank_by_file": [
            {"filename": filename, "reciprocal_rank": rank}
            for filename, rank in metrics.reciprocal_rank_by_file
        ],
        "mean_expected_file_reciprocal_rank": metrics.mean_expected_file_reciprocal_rank,
    }


def _attempt_has_expected_file(
    attempt: RetrievalAttemptTrace,
    expected_files: Sequence[str],
) -> bool:
    expected = set(expected_files)
    if not expected:
        return False
    candidates = [
        candidate for result in attempt.retriever_results for candidate in result.candidates
    ]
    candidates.extend(attempt.merged_candidates)
    candidates.extend(attempt.reranked_candidates)
    if attempt.evidence is not None:
        candidates.extend(attempt.evidence.accepted_candidates)
    return any(candidate.filename in expected for candidate in candidates)


def _verify_vector_points(
    drive_file: DriveFile,
    chunks: Sequence[Chunk],
    points: Sequence[VectorPayloadSnapshot],
) -> None:
    expected_ids = {str(chunk.id) for chunk in chunks}
    point_ids = {point.point_id for point in points}
    if len(point_ids) != len(points):
        raise EvaluationPreflightError(
            f"Qdrant returned duplicate point IDs for corpus file {drive_file.name!r}"
        )
    missing = sorted(expected_ids - point_ids)
    extra = sorted(point_ids - expected_ids)
    if missing or extra:
        raise EvaluationPreflightError(
            f"Qdrant points for {drive_file.name!r} do not match current PostgreSQL chunks "
            f"(missing={len(missing)}, extra={len(extra)})"
        )

    chunks_by_id = {str(chunk.id): chunk for chunk in chunks}
    for point in points:
        chunk = chunks_by_id[point.point_id]
        expected_hash = chunk.metadata_json.get("extracted_text_hash")
        if point.chunk_id != point.point_id:
            raise EvaluationPreflightError(
                f"Qdrant payload chunk ID does not match point ID for {drive_file.name!r}"
            )
        if point.drive_file_id != str(drive_file.id):
            raise EvaluationPreflightError(
                f"Qdrant payload DriveFile ID is incorrect for {drive_file.name!r}"
            )
        if point.filename != drive_file.name:
            raise EvaluationPreflightError(
                f"Qdrant payload filename is incorrect for {drive_file.name!r}"
            )
        if not isinstance(expected_hash, str) or point.extracted_text_hash != expected_hash:
            raise EvaluationPreflightError(
                f"Qdrant payload hash is stale for {drive_file.name!r} chunk {chunk.id}"
            )


def _phrase_matches_to_json(matches: Sequence[PhraseMatch]) -> list[JsonObject]:
    return [{"phrase": match.phrase, "matched": match.matched} for match in matches]


def _match_coverage(matches: Sequence[PhraseMatch]) -> float | None:
    if not matches:
        return None
    return sum(match.matched for match in matches) / len(matches)


def _aggregate_at_k(values: Sequence[Mapping[str, Any]]) -> JsonObject:
    keys = sorted(
        {
            str(key)
            for value in values
            for key in (value.get("at_k", {}) if isinstance(value.get("at_k"), Mapping) else {})
        },
        key=int,
    )
    aggregated: JsonObject = {}
    for key in keys:
        entries = [
            value["at_k"][key]
            for value in values
            if isinstance(value.get("at_k"), Mapping) and key in value["at_k"]
        ]
        recalls = [float(entry["recall"]) for entry in entries if entry.get("recall") is not None]
        hits = [bool(entry["hit"]) for entry in entries if entry.get("hit") is not None]
        aggregated[key] = {
            "applicable_cases": len(recalls),
            "mean_recall": _mean(recalls),
            "hit_rate": _mean(hits),
            "all_expected_files_count": sum(
                entry.get("all_expected_files") is True for entry in entries
            ),
        }
    return aggregated


def _numeric_values(cases: Sequence[Mapping[str, Any]], *path: str) -> list[float]:
    values: list[float] = []
    for case in cases:
        value = _nested(case, *path)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            values.append(float(value))
    return values


def _nested(value: Mapping[str, Any], *path: str) -> Any:
    current: Any = value
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _mean(values: Sequence[float | bool]) -> float | None:
    return sum(float(value) for value in values) / len(values) if values else None


def _nearest_rank_percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _git_output(repo_root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _preflight_display(preflight: RunPreflight) -> JsonObject:
    return {
        "dataset_id": preflight.dataset.dataset_id,
        "case_count": preflight.dataset.case_count,
        "dataset_sha256": preflight.dataset_sha256,
        "git": {
            "sha": preflight.git.sha,
            "branch": preflight.git.branch,
            "dirty": preflight.git.dirty,
        },
        "corpus_fingerprint": preflight.corpus.fingerprint_sha256,
        "corpus_file_count": len(preflight.corpus.manifest),
        "evaluation_user_id": str(preflight.corpus.user_id),
        "configuration": preflight.configuration,
    }


if __name__ == "__main__":
    raise SystemExit(main())
