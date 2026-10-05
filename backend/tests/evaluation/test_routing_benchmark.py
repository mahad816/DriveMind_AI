"""Offline gold validation and honest observation of legacy limitations."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.routing.contract import Capability, ExpectedRequest, Operation, RoutingMode
from evaluation.routing_baseline import observe_rules
from evaluation.routing_dataset import RoutingDataset, load_routing_dataset
from evaluation.routing_metrics import score_routing
from evaluation.routing_runner import DEFAULT_DATASET, run_routing


def raw_case() -> dict:
    return {
        "id": "case-1",
        "question": "List all files",
        "history": [],
        "history_window_complete": True,
        "expected_mode": "SINGLE",
        "expected_requests": [{"capability": "FILE_INVENTORY", "operation": "LIST"}],
        "difficulty": "straightforward",
        "tags": [],
        "notes": "Inventory metadata",
    }


def dataset_raw() -> dict:
    return {
        "dataset_id": "routing_v1",
        "schema_version": "routing-1.0",
        "case_count": 1,
        "description": "Fixture",
        "policy_notes": [],
        "cases": [raw_case()],
    }


def test_real_dataset_composition() -> None:
    dataset = load_routing_dataset(DEFAULT_DATASET)
    assert dataset.case_count == 120
    assert [sum(c.expected_mode == mode for c in dataset.cases) for mode in RoutingMode] == [
        70,
        30,
        20,
    ]
    assert {r.capability for c in dataset.cases for r in c.expected_requests} == set(Capability)
    assert {r.operation for c in dataset.cases for r in c.expected_requests} == set(Operation)


@pytest.mark.parametrize("capability", list(Capability))
@pytest.mark.parametrize("operation", list(Operation))
def test_operation_compatibility(capability: Capability, operation: Operation) -> None:
    allowed = {
        "FILE_INVENTORY": {"LIST", "COUNT", "LATEST", "OLDEST"},
        "FILE_TARGET": {"SUMMARIZE", "ANSWER_QUESTION"},
        "COLLECTION_SUMMARY": {"SUMMARIZE_EACH"},
        "CONVERSATION_HISTORY": {"RECALL"},
        "GROUNDED_RAG": {"ANSWER"},
        "CHITCHAT": {"RESPOND"},
    }
    if operation.value in allowed[capability.value]:
        assert ExpectedRequest(capability=capability, operation=operation).operation == operation
    else:
        with pytest.raises(ValidationError, match="incompatible"):
            ExpectedRequest(capability=capability, operation=operation)


@pytest.mark.parametrize(
    ("mode", "count", "reason"),
    [
        ("SINGLE", 0, None),
        ("SINGLE", 2, None),
        ("COMPOUND", 1, None),
        ("COMPOUND", 4, None),
        ("CLARIFY", 1, "MISSING_ARGUMENT"),
        ("CLARIFY", 0, None),
        ("SINGLE", 1, "MISSING_ARGUMENT"),
    ],
)
def test_invalid_mode_invariants(mode: str, count: int, reason: str | None) -> None:
    raw = dataset_raw()
    case = raw["cases"][0]
    case.update(
        expected_mode=mode,
        expected_requests=case["expected_requests"] * count,
        expected_clarification_reason=reason,
    )
    with pytest.raises(ValidationError):
        RoutingDataset.model_validate(raw)


@pytest.mark.parametrize("mutation", ["duplicate", "count", "extra", "blank", "route"])
def test_dataset_rejects_invalid_input(mutation: str) -> None:
    raw = dataset_raw()
    if mutation == "duplicate":
        raw["cases"].append(raw_case())
        raw["case_count"] = 2
    elif mutation == "count":
        raw["case_count"] = 2
    elif mutation == "extra":
        raw["cases"][0]["sql"] = "SELECT anything"
    elif mutation == "blank":
        raw["cases"][0]["question"] = "   "
    else:
        raw["cases"][0]["expected_requests"][0]["capability"] = "META"
    with pytest.raises(ValidationError):
        RoutingDataset.model_validate(raw)


def test_observation_is_independent_of_gold() -> None:
    raw = dataset_raw()
    first = RoutingDataset.model_validate(raw).cases[0]
    raw["cases"][0].update(
        expected_mode="CLARIFY",
        expected_requests=[],
        expected_clarification_reason="MISSING_ARGUMENT",
    )
    second = RoutingDataset.model_validate(raw).cases[0]
    assert observe_rules(first) == observe_rules(second)
    assert observe_rules(first).operation is None


def test_metrics_duplicate_capabilities_and_clarification() -> None:
    raw = dataset_raw()
    compound = raw_case()
    compound.update(
        id="compound",
        question='Summarize "a.txt" and "b.txt".',
        expected_mode="COMPOUND",
        expected_requests=[
            {"capability": "FILE_TARGET", "operation": "SUMMARIZE"},
            {"capability": "FILE_TARGET", "operation": "SUMMARIZE"},
        ],
    )
    clarify = raw_case()
    clarify.update(
        id="clarify",
        question="Summarize it.",
        expected_mode="CLARIFY",
        expected_requests=[],
        expected_clarification_reason="UNRESOLVED_REFERENCE",
    )
    raw.update(case_count=3, cases=[raw_case(), compound, clarify])
    cases = RoutingDataset.model_validate(raw).cases
    metrics = score_routing(cases, [observe_rules(case) for case in cases])
    assert metrics["single_six_route_accuracy"] == 1
    assert metrics["mode_accuracy"] == pytest.approx(1 / 3)
    assert metrics["compound_omission_rate"] == 0.5
    assert metrics["clarification_miss_rate"] == 1
    assert metrics["capabilities"]["FILE_TARGET"]["recall"] == 0.5
    assert metrics["operation_inferable_predictions"] == 0
    assert metrics["operation_coverage"] == 0
    assert metrics["social_decoration_false_positive_rate"] is None


def test_social_and_rewrite_observations() -> None:
    dataset = load_routing_dataset(DEFAULT_DATASET)
    social = next(c for c in dataset.cases if c.question == "Hi, how many files are there?")
    prediction = observe_rules(social)
    assert prediction.rule_route == Capability.FILE_INVENTORY
    assert score_routing([social], [prediction])["social_decoration_false_positive_rate"] == 0
    dependent = next(
        c for c in dataset.cases if c.question == "Can you elaborate on that?" and c.history
    )
    assert observe_rules(dependent).followup_rewrite_eligible
    absent = next(
        c for c in dataset.cases if c.question == "Can you elaborate on that?" and not c.history
    )
    assert observe_rules(absent).followup_context_signal
    assert not observe_rules(absent).followup_rewrite_eligible


def test_runner_artifact_and_repeatability(tmp_path: Path) -> None:
    first, path = run_routing(DEFAULT_DATASET, tmp_path)
    second, other = run_routing(DEFAULT_DATASET, tmp_path)
    assert path != other
    assert json.loads(path.read_text())["dataset_version"] == "routing-1.0"
    assert first["metrics"] == second["metrics"]
    assert first["cases"] == second["cases"]
    assert first["case_count"] == 120
    assert len(first["git_revision"]) == 40
    assert "confidence" not in first["cases"][0]["prediction"]


def test_scoring_rejects_misaligned_lengths() -> None:
    with pytest.raises(ValueError, match="align"):
        score_routing(load_routing_dataset(DEFAULT_DATASET).cases, [])


@pytest.mark.asyncio
async def test_conversation_provider_guard_implements_current_protocol() -> None:
    from evaluation.conversation_runner import _ForbiddenChat

    guard = _ForbiddenChat()
    with pytest.raises(AssertionError, match="follow-up"):
        await guard.rewrite_followup("Elaborate", [])
    with pytest.raises(AssertionError, match="collection"):
        await guard.generate_collection_answer("Summarize all files", [], max_context_chars=1000)
