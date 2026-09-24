"""Provider-free EXP-03 evaluation; Gold's single-turn runner remains unchanged."""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol

from app.core.config import get_settings
from app.evaluation.trace import EvalTraceCollector
from app.llm.base import ChatService
from app.retrieval.base import Retriever
from app.retrieval.conversation_intent import classify_conversation_reference
from app.retrieval.query_router import QueryRoute, classify_query
from app.retrieval.types import RetrievedChunk
from app.services.conversation_history import (
    HistorySelection,
    render_history_answer,
    select_history_turn,
)
from app.services.rag_service import RagResult, RagService
from app.db.session import SessionLocal
from evaluation.conversation_dataset import (
    ConversationEvalCase,
    ConversationEvalDataset,
    load_conversation_dataset,
)
from evaluation.runner import (
    DEFAULT_RESULTS_DIR,
    GitState,
    capture_git_state,
    configuration_snapshot,
    file_sha256,
    resolve_evaluation_user,
    write_result_atomically,
)

DATASET_PATH = Path(__file__).resolve().parent / "datasets/conversational_followup_v1.json"
JsonObject = dict[str, Any]


class ConversationService(Protocol):
    async def ask(
        self,
        question: str,
        user_id: uuid.UUID | None = None,
        *,
        trace: EvalTraceCollector | None = None,
        conversation_id: str | None = None,
        history: Sequence[Mapping[str, str]] = (),
        history_window_complete: bool = False,
    ) -> RagResult: ...


class _ForbiddenRetriever(Retriever):
    async def retrieve(self, question: str) -> list[RetrievedChunk]:
        raise AssertionError(f"EXP-03 attempted document retrieval: {question!r}")


class _ForbiddenChat(ChatService):
    @property
    def model_name(self) -> str:
        return "disabled-for-conversation-evaluation"

    async def generate_grounded_answer(
        self, question: str, chunks: list[RetrievedChunk], *, max_context_chars: int
    ) -> str:
        raise AssertionError("EXP-03 attempted grounded provider generation")

    async def generate_direct_answer(self, question: str) -> str:
        raise AssertionError("EXP-03 attempted direct provider generation")

    async def generate_inventory_answer(self, question: str, inventory_context: str) -> str:
        raise AssertionError("EXP-03 attempted inventory provider generation")

    async def generate_file_target_answer(
        self, question: str, chunks: list[RetrievedChunk], *, max_context_chars: int
    ) -> str:
        raise AssertionError("EXP-03 attempted file-target provider generation")


def require_conversation_clean_git(git: GitState) -> None:
    """Formal results must identify one committed, clean source tree."""
    if git.dirty:
        raise ValueError("Formal conversation evaluation requires a clean Git tree")


async def evaluate_conversation_case(
    case: ConversationEvalCase,
    *,
    service: ConversationService | None,
    user_id: uuid.UUID,
) -> JsonObject:
    """Exercise real service for history; stop document controls at the real router."""
    started = perf_counter()
    expected = case.expected
    route_rule = expected.route_rule
    failed: list[str] = []
    actual_route: str | None = None
    route_passed: bool | None = None
    actual_role: str | None = None
    actual_kind: str | None = None
    actual_outcome: str | None = None
    actual_index: int | None = None
    actual_text: str | None = None
    actual_retrieval_count: int | None = None
    actual_citation_count: int | None = None
    runtime_error: str | None = None
    selection: HistorySelection | None = None

    try:
        route = classify_query(case.question)
        actual_route = route.name
        route_passed = (
            route.name == route_rule.route
            if route_rule.mode == "exact"
            else route.name != route_rule.route
        )
        if not route_passed:
            failed.append("route")

        if route_rule.mode == "exact" and route_rule.route == QueryRoute.CONVERSATION_HISTORY.name:
            if route is not QueryRoute.CONVERSATION_HISTORY:
                raise ValueError(
                    "conversation case routed outside history; document path not executed"
                )
            decision = classify_conversation_reference(case.question)
            if decision is None:
                failed.append("reference_intent")
            else:
                actual_role = decision.target_role.value if decision.target_role else None
                actual_kind = decision.reference_kind.name
                selection = select_history_turn(
                    case.history,
                    target_role=decision.target_role,
                    reference_kind=decision.reference_kind,
                    history_window_complete=case.history_window_complete,
                )
                actual_outcome = selection.outcome.name
                actual_index = selection.index
                actual_text = selection.text
                if actual_role != expected.target_role:
                    failed.append("target_role")
                if actual_kind != expected.reference_kind:
                    failed.append("reference_kind")
                if actual_outcome != expected.selector_outcome:
                    failed.append("selector_outcome")
                if actual_index != expected.selected_history_index:
                    failed.append("selected_turn")
                if actual_text != expected.selected_text:
                    failed.append("selected_text")

            if service is None:
                raise ValueError("conversation case requires a real service")
            collector = EvalTraceCollector()
            result = await service.ask(
                case.question,
                user_id=user_id,
                trace=collector,
                conversation_id=case.conversation_id,
                history=[turn.model_dump() for turn in case.history],
                history_window_complete=case.history_window_complete,
            )
            if collector.trace.route != route:
                failed.append("service_route")
            if (
                collector.trace.attempts
                or collector.trace.rewrites
                or collector.trace.prompt_chunks
            ):
                failed.append("document_pipeline_used")
            if (
                decision is not None
                and selection is not None
                and result.answer != render_history_answer(selection, decision.target_role)
            ):
                failed.append("service_answer")
            actual_retrieval_count = result.retrieval_count
            actual_citation_count = len(result.citations)
            if actual_retrieval_count != 0:
                failed.append("retrieval_count")
            if actual_citation_count != 0:
                failed.append("citations")
            for other in case.other_conversations:
                if any(turn.text in result.answer for turn in other.history):
                    failed.append("conversation_isolation")
                    break
        # Document controls are route-only. Never invoke service/generation for them.
    except Exception as exc:  # noqa: BLE001 - record case failure without retrying
        runtime_error = f"{type(exc).__name__}: {exc}"
        failed.append("runtime_error")

    return {
        "case_id": case.id,
        "passed": not failed,
        "actual_route": actual_route,
        "route_expectation_mode": route_rule.mode,
        "route_expectation_route": route_rule.route,
        "route_passed": route_passed,
        "actual_target_role": actual_role,
        "actual_reference_kind": actual_kind,
        "actual_selector_outcome": actual_outcome,
        "actual_selected_index": actual_index,
        "actual_selected_text": actual_text,
        "actual_retrieval_count": actual_retrieval_count,
        "actual_citation_count": actual_citation_count,
        "runtime_error": runtime_error,
        "latency_ms": round((perf_counter() - started) * 1000, 3),
        "failed_checks": failed,
        "tags": list(case.tags),
    }


def aggregate_conversation_results(results: Sequence[Mapping[str, Any]]) -> JsonObject:
    """Small deterministic summary; latency is descriptive, not causal evidence."""
    total = len(results)
    passed = sum(result.get("passed") is True for result in results)
    history = [
        result for result in results if "negative_document_control" not in result.get("tags", ())
    ]
    negatives = [
        result for result in results if "negative_document_control" in result.get("tags", ())
    ]
    latencies = sorted(float(result["latency_ms"]) for result in results)
    p95_index = max(0, (95 * len(latencies) + 99) // 100 - 1) if latencies else 0
    failed_checks = Counter(
        check for result in results for check in result.get("failed_checks", ())
    )
    return {
        "cases_total": total,
        "cases_passed": passed,
        "overall_pass_rate": passed / total if total else None,
        "conversation_cases_passed": sum(result.get("passed") is True for result in history),
        "conversation_cases_total": len(history),
        "retrieval_bypass_rate": (
            sum(result.get("actual_retrieval_count") == 0 for result in history) / len(history)
            if history
            else None
        ),
        "zero_citation_rate": (
            sum(result.get("actual_citation_count") == 0 for result in history) / len(history)
            if history
            else None
        ),
        "document_negative_false_positive_count": sum(
            result.get("actual_route") == QueryRoute.CONVERSATION_HISTORY.name
            for result in negatives
        ),
        "runtime_error_count": sum(result.get("runtime_error") is not None for result in results),
        "failed_check_counts": dict(sorted(failed_checks.items())),
        "median_latency_ms": statistics.median(latencies) if latencies else None,
        "p95_latency_ms": latencies[p95_index] if latencies else None,
    }


def build_conversation_artifact(
    dataset: ConversationEvalDataset,
    results: Sequence[Mapping[str, Any]],
    *,
    dataset_sha256: str,
    git: GitState,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    configuration: Mapping[str, Any] | None = None,
) -> JsonObject:
    """Parallel artifact format; no Gold metric or corpus schema is reused."""
    return {
        "result_schema_version": "conversation-1.0",
        "run": {
            "started_at": (started_at or datetime.now(UTC)).astimezone(UTC).isoformat(),
            "finished_at": (finished_at or datetime.now(UTC)).astimezone(UTC).isoformat(),
            "dataset": {
                "dataset_id": dataset.dataset_id,
                "schema_version": dataset.schema_version,
                "case_count": dataset.case_count,
                "sha256": dataset_sha256,
            },
            "git": {"sha": git.sha, "branch": git.branch, "dirty": git.dirty},
            "configuration": dict(configuration or {}),
            "provider_policy": "forbidden; document controls are router-only",
        },
        "summary": aggregate_conversation_results(results),
        "cases": list(results),
    }


async def run_conversation_evaluation(
    dataset_path: Path = DATASET_PATH,
    output_dir: Path = DEFAULT_RESULTS_DIR,
    requested_user_id: uuid.UUID | None = None,
) -> Path:
    """Explicit formal entry point; never called by imports or tests implicitly."""
    git = capture_git_state()
    require_conversation_clean_git(git)
    dataset = load_conversation_dataset(dataset_path)
    dataset_sha256 = file_sha256(dataset_path)
    settings = get_settings()
    async with SessionLocal() as db:
        user_id = await resolve_evaluation_user(db, requested_user_id)

    started = datetime.now(UTC)
    results: list[JsonObject] = []
    for case in dataset.cases:
        route_rule = case.expected.route_rule
        if route_rule.mode != "exact" or route_rule.route != QueryRoute.CONVERSATION_HISTORY.name:
            results.append(await evaluate_conversation_case(case, service=None, user_id=user_id))
            continue
        async with SessionLocal() as db:
            service = RagService(
                db,
                settings,
                retriever=_ForbiddenRetriever(),
                chat_service=_ForbiddenChat(),
                persist_query_history=False,
            )
            results.append(await evaluate_conversation_case(case, service=service, user_id=user_id))
    finished = datetime.now(UTC)
    artifact = build_conversation_artifact(
        dataset,
        results,
        dataset_sha256=dataset_sha256,
        git=git,
        started_at=started,
        finished_at=finished,
        configuration=configuration_snapshot(settings),
    )
    timestamp = started.strftime("%Y%m%dT%H%M%SZ")
    filename = f"drivemind_{dataset.dataset_id}__{timestamp}__{git.sha[:8]}.json"
    return write_result_atomically(artifact, output_dir, filename)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run deterministic EXP-03 conversation evaluation")
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--user-id", type=uuid.UUID)
    parser.add_argument("--execute-conversation", action="store_true")
    args = parser.parse_args(argv)
    if not args.execute_conversation:
        parser.print_help(sys.stderr)
        print("\nRefusing to execute: pass --execute-conversation deliberately.", file=sys.stderr)
        return 2
    artifact = asyncio.run(run_conversation_evaluation(args.dataset, args.output_dir, args.user_id))
    print(json.dumps({"artifact": str(artifact)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
