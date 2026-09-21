"""Synthetic-only tests for the evaluation runner infrastructure."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.enums import DriveFileStatus
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.evaluation.trace import (
    CandidateSnapshot,
    EvalTrace,
    EvalTraceCollector,
    EvidenceTrace,
    RetrievalAttemptTrace,
    RetrieverResultTrace,
    RewriteTrace,
    TraceOutcome,
)
from app.retrieval.query_router import QueryRoute
from app.services.rag_service import RagResult
from evaluation.dataset import EvaluationCase, EvaluationDataset
from evaluation.runner import (
    EvaluationPreflightError,
    GitState,
    VectorPayloadSnapshot,
    aggregate_results,
    configuration_snapshot,
    corpus_fingerprint,
    execute_cases,
    file_sha256,
    main,
    project_case_result,
    project_trace,
    require_clean_git,
    resolve_evaluation_user,
    verify_corpus,
    write_result_atomically,
)
from evaluation.runner import _verify_vector_points

USER_ID = uuid.uuid4()
DRIVE_FILE_ID = uuid.uuid4()
CHUNK_ID = uuid.uuid4()
NOW = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)


def _case(
    case_id: str = "synthetic_001",
    question: str = "Synthetic question one?",
    *,
    expected_route: str = "GROUNDED_RAG",
    expected_files: tuple[str, ...] = ("alpha.txt",),
    should_answer: bool = True,
) -> EvaluationCase:
    return EvaluationCase(
        id=case_id,
        question=question,
        expected_route=expected_route,
        expected_files=expected_files,
        should_answer=should_answer,
        reference_answer="Synthetic answer.",
        must_include=("Synthetic",),
        must_not_include=("Incorrect proposition",),
        evidence_anchors=("evidence",),
        tags=("synthetic",),
    )


def _dataset(cases: tuple[EvaluationCase, ...]) -> EvaluationDataset:
    return EvaluationDataset(
        dataset_id="synthetic_v1",
        schema_version="1.0",
        corpus_id="synthetic_corpus",
        case_count=len(cases),
        description="Synthetic runner fixture.",
        evaluation_notes=(),
        cases=cases,
    )


def _candidate(
    filename: str = "alpha.txt",
    *,
    rank: int = 1,
    score: float = 0.8,
    text: str = "Synthetic evidence text.",
) -> CandidateSnapshot:
    return CandidateSnapshot(
        chunk_id=uuid.uuid4(),
        drive_file_id=uuid.uuid4(),
        filename=filename,
        mime_type="text/plain",
        modified_at=NOW,
        chunk_index=rank - 1,
        rank=rank,
        score=score,
        primary_source="vector",
        source_scores=(("vector", score), ("keyword", score / 2)),
        text=text,
    )


def _trace_with_attempts() -> EvalTrace:
    first = _candidate("noise.txt", text="Unrelated material.")
    recovered = _candidate("alpha.txt", text="Recovered evidence anchor.")
    return EvalTrace(
        question="Synthetic question?",
        route=QueryRoute.GROUNDED_RAG,
        execution_path="langgraph",
        graph_intent="knowledge",
        retrieval_plan=("vector", "keyword"),
        attempts=[
            RetrievalAttemptTrace(
                attempt_number=1,
                working_query="original synthetic query",
                active_retrievers=("vector",),
                retriever_results=(RetrieverResultTrace("vector", (first,), 2.5),),
                merged_candidates=(first,),
                reranked_candidates=(first,),
                evidence=EvidenceTrace(False, "insufficient", ()),
                duration_ms=4.0,
            ),
            RetrievalAttemptTrace(
                attempt_number=2,
                working_query="rewritten synthetic query",
                active_retrievers=("vector", "keyword"),
                retriever_results=(
                    RetrieverResultTrace("vector", (recovered,), 2.0),
                    RetrieverResultTrace("keyword", (recovered,), 1.0),
                ),
                merged_candidates=(recovered,),
                reranked_candidates=(recovered,),
                evidence=EvidenceTrace(True, "sufficient", (recovered,)),
                duration_ms=5.0,
            ),
        ],
        rewrites=[
            RewriteTrace(
                after_attempt=1,
                input_query="original synthetic query",
                output_query="rewritten synthetic query",
                evidence_reason="insufficient",
                source="heuristic",
                duration_ms=0.5,
            )
        ],
        prompt_chunks=(recovered,),
        raw_answer="Synthetic answer [1].",
        final_answer="Synthetic answer [1].",
        outcome=TraceOutcome.ANSWERED,
        total_duration_ms=12.0,
        retrieval_duration_ms=9.0,
        generation_duration_ms=2.0,
    )


def test_default_cli_refuses_execution(capsys: pytest.CaptureFixture[str]) -> None:
    command = MagicMock()

    assert main([], command=command) == 2
    command.assert_not_called()
    assert "--execute-gold" in capsys.readouterr().err


def test_explicit_cli_opt_in_invokes_injected_command(tmp_path: Path) -> None:
    artifact = tmp_path / "synthetic.json"
    calls: list[dict[str, Any]] = []

    async def command(**kwargs: Any) -> Path:
        calls.append(kwargs)
        return artifact

    status = main(
        [
            "--execute-gold",
            "--dataset",
            str(tmp_path / "synthetic-dataset.json"),
            "--output-dir",
            str(tmp_path),
        ],
        command=command,
    )

    assert status == 0
    assert len(calls) == 1
    assert calls[0]["allow_dirty"] is False


def test_dirty_git_blocks_baseline_without_override() -> None:
    dirty = GitState(sha="abc123", branch="main", dirty=True)

    with pytest.raises(RuntimeError, match="dirty working tree"):
        require_clean_git(dirty)

    require_clean_git(dirty, allow_dirty=True)


def test_dataset_sha_uses_exact_bytes(tmp_path: Path) -> None:
    path = tmp_path / "dataset.json"
    path.write_bytes(b'{"synthetic": true}\n')

    assert file_sha256(path) == "729cd4435656683931ea719191f6786bbca51754bd7e573f413a655d71fdde49"


def test_configuration_snapshot_contains_rag_values_but_no_secrets() -> None:
    settings = Settings(
        openai_api_key="do-not-serialize",
        database_url="postgresql+asyncpg://secret",
        google_client_secret="also-secret",
        chat_model="synthetic-chat",
        embedding_model="synthetic-embedding",
        retrieval_top_k=7,
    )

    snapshot = configuration_snapshot(settings)
    serialized = json.dumps(snapshot)

    assert snapshot["chat_model"] == "synthetic-chat"
    assert snapshot["embedding_model"] == "synthetic-embedding"
    assert snapshot["retrieval_top_k"] == 7
    assert snapshot["chat_temperature"] is None
    assert "do-not-serialize" not in serialized
    assert "postgresql" not in serialized
    assert "also-secret" not in serialized


def test_corpus_fingerprint_is_deterministic_from_sorted_metadata() -> None:
    alpha = {"filename": "alpha.txt", "drive_file_id": "2", "chunk_count": 1}
    beta = {"filename": "beta.txt", "drive_file_id": "1", "chunk_count": 2}

    assert corpus_fingerprint([alpha, beta]) == corpus_fingerprint([beta, alpha])
    assert corpus_fingerprint([alpha]) != corpus_fingerprint([beta])


@pytest.mark.asyncio
async def test_corpus_preflight_verifies_indexed_document_chunks_and_qdrant() -> None:
    drive_file = DriveFile(
        id=DRIVE_FILE_ID,
        user_id=USER_ID,
        drive_file_id="google-alpha",
        name="alpha.txt",
        mime_type="text/plain",
        modified_at=NOW,
        indexed_at=NOW,
        status=DriveFileStatus.INDEXED,
    )
    document = Document(
        id=uuid.uuid4(),
        drive_file_id=DRIVE_FILE_ID,
        extracted_text="Controlled synthetic evidence.",
        extracted_text_hash="stored-hash",
    )
    chunk = Chunk(
        id=CHUNK_ID,
        document_id=document.id,
        chunk_index=0,
        text="Controlled synthetic evidence.",
        metadata_json={"extracted_text_hash": "stored-hash"},
    )
    db = AsyncMock()
    db.scalars = AsyncMock(
        side_effect=[
            _ScalarRows([drive_file]),
            _ScalarRows([document]),
            _ScalarRows([chunk]),
        ]
    )
    vector_reader = AsyncMock()
    vector_reader.points_for_drive_file = AsyncMock(
        return_value=(
            VectorPayloadSnapshot(
                point_id=str(CHUNK_ID),
                chunk_id=str(CHUNK_ID),
                drive_file_id=str(DRIVE_FILE_ID),
                filename="alpha.txt",
                extracted_text_hash="stored-hash",
            ),
        )
    )

    corpus = await verify_corpus(
        cast(AsyncSession, db),
        vector_reader,
        USER_ID,
        ["alpha.txt"],
    )

    assert len(corpus.manifest) == 1
    assert corpus.manifest[0]["status"] == "INDEXED"
    assert corpus.manifest[0]["chunk_count"] == 1
    assert "extracted_text" not in corpus.manifest[0]
    assert corpus.manifest[0]["qdrant_point_count"] == 1
    vector_reader.points_for_drive_file.assert_awaited_once_with(DRIVE_FILE_ID)


@pytest.mark.asyncio
async def test_corpus_preflight_rejects_missing_qdrant_point() -> None:
    drive_file = DriveFile(
        id=DRIVE_FILE_ID,
        user_id=USER_ID,
        drive_file_id="google-alpha",
        name="alpha.txt",
        mime_type="text/plain",
        modified_at=NOW,
        indexed_at=NOW,
        status=DriveFileStatus.INDEXED,
    )
    document = Document(
        id=uuid.uuid4(),
        drive_file_id=DRIVE_FILE_ID,
        extracted_text="Controlled synthetic evidence.",
        extracted_text_hash="stored-hash",
    )
    chunk = Chunk(
        id=CHUNK_ID,
        document_id=document.id,
        chunk_index=0,
        text="Controlled synthetic evidence.",
        metadata_json={"extracted_text_hash": "stored-hash"},
    )
    db = AsyncMock()
    db.scalars = AsyncMock(
        side_effect=[
            _ScalarRows([drive_file]),
            _ScalarRows([document]),
            _ScalarRows([chunk]),
        ]
    )
    vector_reader = AsyncMock()
    vector_reader.points_for_drive_file = AsyncMock(return_value=())

    with pytest.raises(EvaluationPreflightError, match="missing=1, extra=0"):
        await verify_corpus(
            cast(AsyncSession, db),
            vector_reader,
            USER_ID,
            ["alpha.txt"],
        )


@pytest.mark.parametrize(
    "points",
    [
        (
            VectorPayloadSnapshot(
                point_id=str(CHUNK_ID),
                chunk_id=str(CHUNK_ID),
                drive_file_id=str(uuid.uuid4()),
                filename="alpha.txt",
                extracted_text_hash="stored-hash",
            ),
        ),
        (
            VectorPayloadSnapshot(
                point_id=str(CHUNK_ID),
                chunk_id=str(CHUNK_ID),
                drive_file_id=str(DRIVE_FILE_ID),
                filename="alpha.txt",
                extracted_text_hash="stored-hash",
            ),
            VectorPayloadSnapshot(
                point_id=str(uuid.uuid4()),
                chunk_id=str(uuid.uuid4()),
                drive_file_id=str(DRIVE_FILE_ID),
                filename="alpha.txt",
                extracted_text_hash="stored-hash",
            ),
        ),
    ],
)
def test_corpus_preflight_rejects_wrong_identity_or_extra_points(
    points: tuple[VectorPayloadSnapshot, ...],
) -> None:
    drive_file = DriveFile(
        id=DRIVE_FILE_ID,
        user_id=USER_ID,
        drive_file_id="google-alpha",
        name="alpha.txt",
        mime_type="text/plain",
        modified_at=NOW,
        indexed_at=NOW,
        status=DriveFileStatus.INDEXED,
    )
    chunk = Chunk(
        id=CHUNK_ID,
        document_id=uuid.uuid4(),
        chunk_index=0,
        text="Controlled synthetic evidence.",
        metadata_json={"extracted_text_hash": "stored-hash"},
    )

    with pytest.raises(EvaluationPreflightError):
        _verify_vector_points(drive_file, [chunk], points)


@pytest.mark.asyncio
async def test_ambiguous_evaluation_user_requires_explicit_selection() -> None:
    db = AsyncMock()
    db.scalars = AsyncMock(return_value=_ScalarRows([uuid.uuid4(), uuid.uuid4()]))

    with pytest.raises(EvaluationPreflightError, match="provide --user-id"):
        await resolve_evaluation_user(cast(AsyncSession, db), None)


@pytest.mark.asyncio
async def test_executor_uses_fresh_isolation_sequential_order_and_continues_failures() -> None:
    cases = (
        _case("one", "Synthetic one?"),
        _case("failure", "Synthetic failure?"),
        _case("three", "Synthetic three?"),
    )
    sessions: list[object] = []
    services: list[object] = []
    collectors: list[EvalTraceCollector] = []
    call_order: list[str] = []

    @asynccontextmanager
    async def session_factory() -> AsyncIterator[AsyncSession]:
        session = object()
        sessions.append(session)
        yield cast(AsyncSession, session)

    class FakeService:
        async def ask(
            self,
            question: str,
            user_id: uuid.UUID | None = None,
            *,
            trace: EvalTraceCollector | None = None,
        ) -> RagResult:
            assert trace is not None
            call_order.append(question)
            trace.start(question)
            trace.record_route(QueryRoute.GROUNDED_RAG, "linear")
            if "failure" in question:
                raise RuntimeError("synthetic failure")
            trace.record_raw_generation("Synthetic answer.", [], duration_ms=1.0)
            trace.record_final("Synthetic answer.", [])
            trace.finish()
            return RagResult(uuid.uuid4(), USER_ID, question, "Synthetic answer.", [], 0)

    def service_factory(
        db: AsyncSession,
        settings: Settings,
        *,
        persist_query_history: bool,
    ) -> FakeService:
        assert db is sessions[-1]
        assert persist_query_history is False
        service = FakeService()
        services.append(service)
        return service

    def collector_factory() -> EvalTraceCollector:
        collector = EvalTraceCollector()
        collectors.append(collector)
        return collector

    results = await execute_cases(
        _dataset(cases),
        user_id=USER_ID,
        settings=Settings(),
        session_factory=session_factory,
        service_factory=service_factory,
        collector_factory=collector_factory,
    )

    assert call_order == [case.question for case in cases]
    assert len({id(value) for value in sessions}) == 3
    assert len({id(value) for value in services}) == 3
    assert len({id(value) for value in collectors}) == 3
    assert [result["status"] for result in results] == ["completed", "failed", "completed"]
    assert results[1]["error"] == {"type": "RuntimeError", "message": "synthetic failure"}


def test_trace_projection_omits_full_text_and_serializes_stable_types() -> None:
    trace = _trace_with_attempts()

    projected = project_trace(trace, ("evidence",))
    candidate = projected["attempts"][1]["retrievers"][0]["candidates"][0]

    assert "text" not in candidate
    assert candidate["text_length"] == len("Recovered evidence anchor.")
    assert len(candidate["text_sha256"]) == 64
    assert candidate["modified_at"] == NOW.isoformat()
    assert isinstance(candidate["chunk_id"], str)
    assert candidate["source_scores"] == [
        {"source": "vector", "score": 0.8},
        {"source": "keyword", "score": 0.4},
    ]
    assert projected["route"] == "GROUNDED_RAG"


def test_multi_attempt_projection_and_rewrite_recovery_stay_distinct() -> None:
    trace = _trace_with_attempts()
    case = _case()

    result = project_case_result(
        case,
        trace,
        result=None,
        caught=None,
        settings=Settings(retrieval_candidate_k=4, retrieval_top_k=2),
    )

    attempts = result["trace"]["attempts"]
    assert [attempt["attempt_number"] for attempt in attempts] == [1, 2]
    assert attempts[0]["working_query"] == "original synthetic query"
    assert attempts[1]["working_query"] == "rewritten synthetic query"
    assert result["metrics"]["rewrites"]["rewrite_recovered_expected_file"] is True
    assert result["trace"]["final_attempt"] == 2
    assert [
        attempt["attempt_number"] for attempt in result["metrics"]["retrieval"]["attempts"]
    ] == [1, 2]
    assert result["metrics"]["retrieval"]["stages"]["prompt"]["expected_file_recall"] == 1.0


def test_specialized_route_has_no_fabricated_retrieval_metrics() -> None:
    trace = EvalTrace(
        question="Hello",
        route=QueryRoute.CHITCHAT,
        execution_path="chitchat",
        raw_answer="Hello!",
        final_answer="Hello!",
        outcome=TraceOutcome.ANSWERED,
    )
    case = _case(
        "chitchat",
        "Hello",
        expected_route="CHITCHAT",
        expected_files=(),
    )

    result = project_case_result(case, trace, result=None, caught=None, settings=Settings())

    assert result["metrics"]["retrieval"] is None
    assert result["metrics"]["file_target"] is None
    assert result["metrics"]["expected_route_diagnostics_missing"] is False
    assert result["metrics"]["prompt"]["expected_file_recall"] is None
    assert result["trace"]["attempts"] == []


def test_wrong_route_keeps_missing_grounded_diagnostics_visible() -> None:
    trace = EvalTrace(
        question="Synthetic knowledge question",
        route=QueryRoute.CHITCHAT,
        execution_path="chitchat",
        final_answer="Synthetic answer.",
        outcome=TraceOutcome.ANSWERED,
    )

    result = project_case_result(
        _case(),
        trace,
        result=None,
        caught=None,
        settings=Settings(),
    )

    assert result["metrics"]["route_correct"] is False
    assert result["metrics"]["retrieval"] is None
    assert result["metrics"]["expected_route_diagnostics_missing"] is True


def test_multi_document_case_requires_all_expected_files() -> None:
    candidate = _candidate("alpha.txt")
    trace = EvalTrace(
        route=QueryRoute.GROUNDED_RAG,
        execution_path="linear",
        attempts=[
            RetrievalAttemptTrace(
                1,
                "synthetic",
                ("vector",),
                retriever_results=(RetrieverResultTrace("vector", (candidate,), 1.0),),
            )
        ],
        final_answer="Synthetic answer.",
        outcome=TraceOutcome.ANSWERED,
    )
    case = _case(expected_files=("alpha.txt", "beta.txt"))

    result = project_case_result(case, trace, result=None, caught=None, settings=Settings())
    raw_vector = result["metrics"]["retrieval"]["stages"]["raw_vector"]

    assert raw_vector["expected_file_recall"] == 0.5
    assert raw_vector["all_expected_files"] is False


def test_summary_excludes_not_applicable_values_and_calculates_latency() -> None:
    cases = [
        {
            "status": "completed",
            "expected": {"route": "CHITCHAT"},
            "trace": {"error": None},
            "metrics": {
                "observed_route": "CHITCHAT",
                "route_correct": True,
                "retrieval": None,
                "prompt": {"expected_file_recall": None},
                "answer": {
                    "must_include_coverage": None,
                    "all_must_include_present": None,
                    "must_not_flags": [],
                },
                "citations": {"expected_file_recall": None},
                "abstention": {
                    "outcome": "ANSWERED",
                    "false_pipeline_abstention": False,
                    "answered_when_should_answer_false": False,
                },
                "rewrites": {"count": 0},
                "latency_ms": {"total": 1.0},
            },
        },
        {
            "status": "completed",
            "expected": {"route": "GROUNDED_RAG"},
            "trace": {"error": None},
            "metrics": {
                "observed_route": "GROUNDED_RAG",
                "route_correct": True,
                "retrieval": None,
                "prompt": {"expected_file_recall": 0.5},
                "answer": {
                    "must_include_coverage": 1.0,
                    "all_must_include_present": True,
                    "must_not_flags": [{"phrase": "x", "matched": True}],
                },
                "citations": {"expected_file_recall": 0.5},
                "abstention": {
                    "outcome": "ANSWERED",
                    "false_pipeline_abstention": False,
                    "answered_when_should_answer_false": False,
                },
                "rewrites": {"count": 1},
                "latency_ms": {"total": 2.0},
            },
        },
        {
            "status": "failed",
            "expected": {"route": "GROUNDED_RAG"},
            "trace": {"error": {"stage": "generation", "component": "chat"}},
            "metrics": {"latency_ms": {"total": 100.0}},
        },
    ]

    summary = aggregate_results(cases)

    assert summary["status"] == "partial_failure"
    assert summary["route_accuracy"] == 1.0
    assert summary["prompt_expected_file_recall"] == 0.5
    assert summary["must_include_average_coverage"] == 1.0
    assert summary["citation_source_recall"] == 0.5
    assert summary["latency_ms"] == {"median": 2.0, "p95": 100.0}
    assert summary["errors_by_stage_component"] == [
        {"stage": "generation", "component": "chat", "count": 1}
    ]


def test_summary_counts_unobserved_completed_route_as_incorrect() -> None:
    case = {
        "status": "completed",
        "expected": {"route": "GROUNDED_RAG"},
        "trace": {"error": None},
        "metrics": {
            "observed_route": None,
            "route_correct": False,
            "retrieval": None,
            "prompt": {"expected_file_recall": None},
            "answer": {
                "must_include_coverage": None,
                "all_must_include_present": None,
                "must_not_flags": [],
            },
            "citations": {"expected_file_recall": None},
            "abstention": {
                "outcome": None,
                "false_pipeline_abstention": False,
                "answered_when_should_answer_false": False,
            },
            "rewrites": {"count": 0},
            "latency_ms": {"total": 1.0},
        },
    }

    summary = aggregate_results([case])

    assert summary["status"] == "completed"
    assert summary["route_accuracy"] == 0.0
    assert summary["route_counts"]["observed"] == {"UNOBSERVED": 1}
    assert summary["confusion_matrix"] == {"GROUNDED_RAG": {"UNOBSERVED": 1}}


def test_atomic_result_write_and_no_overwrite(tmp_path: Path) -> None:
    result = {"result_schema_version": "1.0", "cases": []}

    path = write_result_atomically(result, tmp_path, "result.json")

    assert json.loads(path.read_text(encoding="utf-8")) == result
    with pytest.raises(FileExistsError):
        write_result_atomically({"different": True}, tmp_path, "result.json")
    assert json.loads(path.read_text(encoding="utf-8")) == result


def test_gold_v1_bytes_remain_locked() -> None:
    path = Path(__file__).parents[2] / "evaluation" / "datasets" / "gold_v1.json"

    assert file_sha256(path) == "9f223c2143e452cea5d85d20d25d0ea6e081bfb92b09d8d13855f0630526e8a0"


class _ScalarRows:
    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def all(self) -> list[Any]:
        return self._values
