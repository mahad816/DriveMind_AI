"""Synthetic, provider-free tests for the separate EXP-03 evaluation path."""

from __future__ import annotations

import json
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import Settings
from app.db.models.user import User
from app.retrieval.query_router import QueryRoute
from app.services.rag_service import RagResult, RagService
from evaluation.conversation_dataset import ConversationDatasetError, load_conversation_dataset
from evaluation.conversation_runner import (
    aggregate_conversation_results,
    build_conversation_artifact,
    evaluate_conversation_case,
    main,
    require_conversation_clean_git,
)
from evaluation.runner import GitState

DATASET_PATH = Path(__file__).parents[2] / "evaluation/datasets/conversational_followup_v1.json"


def _raw_dataset() -> dict[str, Any]:
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))


def _write(tmp_path: Path, value: dict[str, Any]) -> Path:
    path = tmp_path / "conversation.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _case(case_id: str):
    return next(
        case for case in load_conversation_dataset(DATASET_PATH).cases if case.id == case_id
    )


def test_loader_accepts_typed_conversational_dataset() -> None:
    dataset = load_conversation_dataset(DATASET_PATH)
    assert dataset.case_count == len(dataset.cases) == 20
    assert dataset.cases[0].history[0].role == "user"
    assert dataset.cases[0].expected.selected_text == "Good morning"
    assert dataset.cases[16].other_conversations[0].conversation_id == "chat-a"


def _v2_document_control() -> dict[str, Any]:
    value = deepcopy(_raw_dataset())
    value["dataset_id"] = "conversational_followup_v2"
    control = next(case for case in value["cases"] if case["id"] == "document_latest_pdf")
    control["expected"].pop("route")
    control["expected"]["route_expectation"] = {
        "mode": "exclude",
        "route": "CONVERSATION_HISTORY",
    }
    return value


def test_loader_accepts_distinct_v2_identity(tmp_path: Path) -> None:
    value = deepcopy(_raw_dataset())
    value["dataset_id"] = "conversational_followup_v2"

    assert load_conversation_dataset(_write(tmp_path, value)).dataset_id == value["dataset_id"]


def test_loader_rejects_unsupported_conversation_identity(tmp_path: Path) -> None:
    value = deepcopy(_raw_dataset())
    value["dataset_id"] = "conversational_followup_v3"

    with pytest.raises(ConversationDatasetError, match="identity|dataset_id"):
        load_conversation_dataset(_write(tmp_path, value))


def test_legacy_v1_route_remains_an_exact_expectation() -> None:
    expected = _case("document_latest_pdf").expected

    assert expected.route == "GROUNDED_RAG"
    assert expected.route_expectation is None


def test_loader_accepts_explicit_exact_route_expectation(tmp_path: Path) -> None:
    value = deepcopy(_raw_dataset())
    value["dataset_id"] = "conversational_followup_v2"
    control = next(case for case in value["cases"] if case["id"] == "document_latest_pdf")
    control["expected"].pop("route")
    control["expected"]["route_expectation"] = {"mode": "exact", "route": "GROUNDED_RAG"}

    expected = next(
        case.expected
        for case in load_conversation_dataset(_write(tmp_path, value)).cases
        if case.id == "document_latest_pdf"
    )
    assert expected.route_expectation is not None
    assert expected.route_expectation.mode == "exact"
    assert expected.route_expectation.route == "GROUNDED_RAG"


def test_v2_history_case_accepts_explicit_exact_history_route(tmp_path: Path) -> None:
    value = deepcopy(_raw_dataset())
    value["dataset_id"] = "conversational_followup_v2"
    expected = value["cases"][0]["expected"]
    expected.pop("route")
    expected["route_expectation"] = {"mode": "exact", "route": "CONVERSATION_HISTORY"}

    case = load_conversation_dataset(_write(tmp_path, value)).cases[0]
    assert case.expected.route_rule.mode == "exact"
    assert case.expected.route_rule.route == "CONVERSATION_HISTORY"
    assert case.expected.target_role == "user"


def test_v1_identity_cannot_change_to_new_route_expectation_semantics(tmp_path: Path) -> None:
    value = _v2_document_control()
    value["dataset_id"] = "conversational_followup_v1"

    with pytest.raises(ConversationDatasetError, match="v1|legacy"):
        load_conversation_dataset(_write(tmp_path, value))


def test_loader_accepts_history_route_exclusion_for_v2(tmp_path: Path) -> None:
    dataset = load_conversation_dataset(_write(tmp_path, _v2_document_control()))
    control = next(case for case in dataset.cases if case.id == "document_latest_pdf")

    assert control.expected.route_expectation is not None
    assert control.expected.route_expectation.mode == "exclude"
    assert control.expected.route_expectation.route == "CONVERSATION_HISTORY"


@pytest.mark.parametrize(
    ("change", "error"),
    [
        (lambda e: e.update(route="GROUNDED_RAG"), "both|exactly one"),
        (lambda e: e["route_expectation"].update(mode="unknown"), "mode"),
        (lambda e: e["route_expectation"].update(route="UNKNOWN"), "route"),
        (lambda e: e["route_expectation"].update(route="FILE_INVENTORY"), "CONVERSATION_HISTORY"),
    ],
)
def test_loader_rejects_invalid_or_contradictory_route_expectations(
    tmp_path: Path, change: Any, error: str
) -> None:
    value = _v2_document_control()
    expected = next(
        case["expected"] for case in value["cases"] if case["id"] == "document_latest_pdf"
    )
    change(expected)

    with pytest.raises(ConversationDatasetError, match=error):
        load_conversation_dataset(_write(tmp_path, value))


@pytest.mark.asyncio
@pytest.mark.parametrize("actual_route", [QueryRoute.FILE_INVENTORY, QueryRoute.GROUNDED_RAG])
async def test_exclusion_control_accepts_nonhistory_routes_without_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, actual_route: QueryRoute
) -> None:
    from evaluation import conversation_runner

    case = next(
        case
        for case in load_conversation_dataset(_write(tmp_path, _v2_document_control())).cases
        if case.id == "document_latest_pdf"
    )
    monkeypatch.setattr(conversation_runner, "classify_query", lambda question: actual_route)
    service = MagicMock()
    service.ask = AsyncMock(side_effect=AssertionError("service/provider called"))

    result = await evaluate_conversation_case(case, service=service, user_id=uuid.uuid4())

    assert result["passed"] is True
    assert result["actual_route"] == actual_route.name
    assert result["route_expectation_mode"] == "exclude"
    assert result["route_expectation_route"] == "CONVERSATION_HISTORY"
    assert result["route_passed"] is True
    service.ask.assert_not_awaited()


@pytest.mark.asyncio
async def test_exclusion_control_rejects_history_route_without_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from evaluation import conversation_runner

    case = next(
        case
        for case in load_conversation_dataset(_write(tmp_path, _v2_document_control())).cases
        if case.id == "document_latest_pdf"
    )
    monkeypatch.setattr(
        conversation_runner, "classify_query", lambda question: QueryRoute.CONVERSATION_HISTORY
    )
    service = MagicMock()
    service.ask = AsyncMock(side_effect=AssertionError("service/provider called"))

    result = await evaluate_conversation_case(case, service=service, user_id=uuid.uuid4())

    assert result["passed"] is False
    assert result["actual_route"] == "CONVERSATION_HISTORY"
    assert result["route_passed"] is False
    assert result["failed_checks"] == ["route"]
    service.ask.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_exact_route_mismatch_is_still_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from evaluation import conversation_runner

    monkeypatch.setattr(
        conversation_runner, "classify_query", lambda question: QueryRoute.FILE_INVENTORY
    )
    result = await evaluate_conversation_case(
        _case("document_latest_pdf"), service=None, user_id=uuid.uuid4()
    )

    assert result["passed"] is False
    assert result["actual_route"] == "FILE_INVENTORY"
    assert result["route_expectation_mode"] == "exact"
    assert result["route_expectation_route"] == "GROUNDED_RAG"
    assert result["route_passed"] is False
    assert result["failed_checks"] == ["route"]


@pytest.mark.parametrize(
    ("mutate", "error"),
    [
        (lambda data: data["cases"][1].update(id=data["cases"][0]["id"]), "duplicate"),
        (lambda data: data["cases"][0]["history"][0].update(role="system"), "role"),
        (lambda data: data["cases"][0]["expected"].update(selected_history_index=1), "selected"),
        (lambda data: data["cases"][0]["expected"].update(selected_text="wrong"), "selected"),
        (lambda data: data["cases"][0].update(history=data["cases"][0]["history"] * 5), "history"),
        (lambda data: data["cases"][0]["history"][0].update(text="x" * 8001), "history"),
        (
            lambda data: data["cases"][0].update(
                history=[{"role": "user", "text": "x" * 7000}] * 4
            ),
            "history",
        ),
        (
            lambda data: data["cases"][13]["expected"].update(selected_text="First question"),
            "ordinal",
        ),
        (lambda data: data["cases"][0]["expected"].update(retrieval_count=1), "retrieval"),
        (lambda data: data["cases"][0]["expected"].update(citations=["file.pdf"]), "citations"),
    ],
)
def test_loader_rejects_invalid_contract(tmp_path: Path, mutate: Any, error: str) -> None:
    value = deepcopy(_raw_dataset())
    mutate(value)
    with pytest.raises(ConversationDatasetError, match=error):
        load_conversation_dataset(_write(tmp_path, value))


@pytest.mark.asyncio
async def test_service_case_passes_only_active_structured_history() -> None:
    case = _case("conversation_isolation")
    service = MagicMock()

    async def traced_answer(*args: Any, **kwargs: Any) -> RagResult:
        kwargs["trace"].record_route(QueryRoute.CONVERSATION_HISTORY, "conversation_history")
        return RagResult(
            query_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            question=case.question,
            answer="Your last question was:\nWhich recipe uses mint?",
            citations=[],
            retrieval_count=0,
        )

    service.ask = AsyncMock(side_effect=traced_answer)

    result = await evaluate_conversation_case(case, service=service, user_id=uuid.uuid4())

    assert result["passed"] is True
    kwargs = service.ask.await_args.kwargs
    assert kwargs["conversation_id"] == "chat-b"
    assert kwargs["history"] == [
        {"role": "user", "text": "Which recipe uses mint?"},
        {"role": "assistant", "text": "The salad recipe uses mint."},
    ]
    assert kwargs["history_window_complete"] is True
    assert "tax deadline" not in json.dumps(kwargs["history"])
    assert result["actual_selected_text"] == "Which recipe uses mint?"
    assert result["actual_retrieval_count"] == 0
    assert result["actual_citation_count"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case_id", "outcome"),
    [
        ("ordinal_last", "UNSUPPORTED_ORDINAL_REFERENCE"),
        ("fresh_conversation", "NO_HISTORY"),
        ("assistant_role_absent", "ROLE_NOT_PRESENT"),
        ("bounded_role_absent", "UNAVAILABLE_IN_BOUNDED_HISTORY"),
    ],
)
async def test_distinct_history_outcomes_are_recorded(case_id: str, outcome: str) -> None:
    case = _case(case_id)
    service = MagicMock()

    async def wrong_answer(*args: Any, **kwargs: Any) -> RagResult:
        kwargs["trace"].record_route(QueryRoute.CONVERSATION_HISTORY, "conversation_history")
        return RagResult(
            query_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            question=case.question,
            answer="wrong",
            citations=[],
            retrieval_count=0,
        )

    service.ask = AsyncMock(side_effect=wrong_answer)
    result = await evaluate_conversation_case(case, service=service, user_id=uuid.uuid4())
    assert result["actual_selector_outcome"] == outcome
    assert result["passed"] is False
    assert result["failed_checks"] == ["service_answer"]


@pytest.mark.asyncio
async def test_real_service_uses_no_retriever_or_provider_for_history() -> None:
    case = _case("assistant_after_file_target")
    user_id = uuid.uuid4()
    db = MagicMock()
    db.get = AsyncMock(return_value=User(id=user_id, email="test@example.com", google_id="g"))
    forbidden_retriever = MagicMock()
    forbidden_retriever.retrieve = AsyncMock(side_effect=AssertionError("retrieval used"))
    forbidden_chat = MagicMock()
    forbidden_chat.generate_direct_answer = AsyncMock(side_effect=AssertionError("provider used"))
    service = RagService(
        db,
        Settings(),
        retriever=forbidden_retriever,
        chat_service=forbidden_chat,
        persist_query_history=False,
    )

    result = await evaluate_conversation_case(case, service=service, user_id=user_id)

    assert result["passed"] is True
    assert result["actual_route"] == QueryRoute.CONVERSATION_HISTORY.name
    forbidden_retriever.retrieve.assert_not_awaited()
    forbidden_chat.generate_direct_answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_document_negative_control_only_uses_router() -> None:
    service = MagicMock()
    service.ask = AsyncMock(side_effect=AssertionError("service/provider called"))
    result = await evaluate_conversation_case(
        _case("document_latest_pdf"), service=service, user_id=uuid.uuid4()
    )
    assert result["passed"] is True
    assert result["actual_route"] == "GROUNDED_RAG"
    assert result["actual_selector_outcome"] is None
    service.ask.assert_not_awaited()


@pytest.mark.asyncio
async def test_misrouted_history_case_never_falls_into_document_service() -> None:
    case = _case("user_after_chitchat").model_copy(
        update={"question": "Find the latest report in my Drive"}
    )
    service = MagicMock()
    service.ask = AsyncMock(side_effect=AssertionError("document pipeline called"))
    result = await evaluate_conversation_case(case, service=service, user_id=uuid.uuid4())
    assert result["passed"] is False
    assert "route" in result["failed_checks"]
    service.ask.assert_not_awaited()


def test_aggregate_metrics_and_artifact_identity() -> None:
    results = [
        {
            "passed": True,
            "actual_route": "CONVERSATION_HISTORY",
            "actual_selector_outcome": "SELECTED",
            "actual_retrieval_count": 0,
            "actual_citation_count": 0,
            "runtime_error": None,
            "latency_ms": 2.0,
            "tags": ["user_recall"],
        },
        {
            "passed": False,
            "actual_route": "CONVERSATION_HISTORY",
            "actual_selector_outcome": "UNSUPPORTED_ORDINAL_REFERENCE",
            "actual_retrieval_count": 0,
            "actual_citation_count": 0,
            "runtime_error": None,
            "latency_ms": 4.0,
            "tags": ["unsupported_ordinal"],
        },
        {
            "passed": True,
            "actual_route": "GROUNDED_RAG",
            "route_expectation_mode": "exclude",
            "route_expectation_route": "CONVERSATION_HISTORY",
            "route_passed": True,
            "actual_selector_outcome": None,
            "actual_retrieval_count": None,
            "actual_citation_count": None,
            "runtime_error": None,
            "latency_ms": 1.0,
            "tags": ["negative_document_control"],
        },
    ]
    summary = aggregate_conversation_results(results)
    assert summary["cases_total"] == 3
    assert summary["cases_passed"] == 2
    assert summary["document_negative_false_positive_count"] == 0
    artifact = build_conversation_artifact(
        load_conversation_dataset(DATASET_PATH),
        results,
        dataset_sha256="fixed-digest",
        git=GitState("fixed-sha", "main", False),
    )
    assert artifact["run"]["dataset"]["sha256"] == "fixed-digest"
    assert artifact["run"]["git"]["sha"] == "fixed-sha"
    assert artifact["summary"]["cases_total"] == 3
    assert artifact["cases"][2]["actual_route"] == "GROUNDED_RAG"
    assert artifact["cases"][2]["route_expectation_mode"] == "exclude"
    assert artifact["cases"][2]["route_expectation_route"] == "CONVERSATION_HISTORY"


def test_formal_runner_rejects_dirty_git() -> None:
    with pytest.raises(ValueError, match="clean"):
        require_conversation_clean_git(GitState("sha", "main", True))


def test_formal_runner_requires_explicit_opt_in(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    assert "--execute-conversation" in capsys.readouterr().err
