"""Full-run guards and supplemental metrics use synthetic offline observations."""

from pathlib import Path

import pytest

from app.routing.providers.typesafe import validate_typesafe
from app.routing.providers.jev_criteria import CRITERIA_VERSION
from app.routing.semantic import ObservationStatus, ProviderObservation
from evaluation.jev_runner import frozen_cases
from evaluation.routing_runner import DEFAULT_DATASET
from evaluation.typesafe_full import main, preflight
from evaluation.typesafe_analysis import analysis
from tests.evaluation.test_typesafe_shadow import settings
from tests.evaluation.test_jev_shadow import response


def observation(mode: str, labels: tuple[str, ...], reason: str = "NONE") -> ProviderObservation:
    data = response(mode, labels, reason)
    data["model"] = "jev-1.13.0"
    return ProviderObservation(
        status=ObservationStatus.SUCCESS,
        provider="api.typesafe.ai",
        model="jev-latest",
        criteria_version=CRITERIA_VERSION,
        **validate_typesafe(data),
    )


def test_mode_reason_distinct_and_duplicate_compounds() -> None:
    gold = frozen_cases(DEFAULT_DATASET)
    cases = [
        next(c for c in gold if c.id == "routing-084"),
        next(c for c in gold if c.id == "routing-101"),
    ]
    predictions = [
        observation("COMPOUND", ("FILE_TARGET:SUMMARIZE", "FILE_TARGET:SUMMARIZE")),
        observation("CLARIFY", (), "MISSING_SCOPE"),
    ]
    result = analysis(cases, predictions)
    assert result["clarification"]["mode_accuracy"] == 1
    assert result["clarification"]["exact_reason_accuracy"] == 0
    assert result["compound"]["operation_recall"] == 1
    assert result["compound"]["exact_request_multiset_accuracy"] == 1
    assert result["core"]["exact_decision_accuracy_labels_only"] == 0.5


def test_omissions_extras_and_order() -> None:
    gold = frozen_cases(DEFAULT_DATASET)
    case = next(c for c in gold if c.id == "routing-071")
    reverse = observation("COMPOUND", ("FILE_TARGET:SUMMARIZE", "FILE_INVENTORY:LIST"))
    result = analysis([case], [reverse])
    assert result["compound"]["exact_request_multiset_accuracy"] == 1
    assert result["compound"]["ordered_request_accuracy"] == 0
    extra = observation(
        "COMPOUND", ("FILE_INVENTORY:LIST", "FILE_TARGET:SUMMARIZE", "GROUNDED_RAG:ANSWER")
    )
    result = analysis([case], [extra])
    assert result["compound"]["extra_operation_rate_per_gold_operation"] == 0.5


def test_preflight_and_no_flag_network_safety(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manifest = preflight(settings())
    assert manifest["case_count"] == 120 and manifest["fresh"]
    assert manifest["question_count"] == 11
    assert main(["--output-dir", str(tmp_path)]) == 0
    monkeypatch.setattr("evaluation.typesafe_full.EXPECTED_CRITERIA_HASH", "mismatch")
    with pytest.raises(ValueError):
        preflight(settings())


def test_invalid_observation_counts_as_failure() -> None:
    case = frozen_cases(DEFAULT_DATASET)[0]
    obs = ProviderObservation(
        status=ObservationStatus.INVALID_RESPONSE,
        provider="api.typesafe.ai",
        model="jev-latest",
        criteria_version=CRITERIA_VERSION,
    )
    result = analysis([case], [obs])
    assert result["core"]["mode_accuracy"] == 0
    assert result["core"]["operation_coverage"] == 0
    assert result["comparison_counts"] == {"rule_win": 1}


def test_structural_invalid_continuation_is_explicit() -> None:
    from evaluation.typesafe_full import acceptable_checkpoint

    invalid = {
        "status": "INVALID_RESPONSE",
        "http_status": 200,
        "model_version": "jev-1.13.0",
        "provenance": {
            "validation_stage": "assembly",
            "validation_error_code": "OPERATION_SLOT_REQUIRED",
        },
    }
    assert not acceptable_checkpoint(invalid, False)
    assert acceptable_checkpoint(invalid, True)
    invalid["provenance"]["validation_stage"] = "answers"
    assert not acceptable_checkpoint(invalid, True)
    invalid["provenance"]["validation_stage"] = "assembly"
    invalid["provenance"]["validation_error_code"] = "DISTRIBUTION_NOT_NORMALIZED"
    assert not acceptable_checkpoint(invalid, True)


@pytest.mark.asyncio
async def test_final_eight_preserve_paid_invalid_without_reposting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.routing.semantic import RoutingInput
    from evaluation.typesafe_full import run_full
    from evaluation.typesafe_runner import identity

    cases = frozen_cases(DEFAULT_DATASET)
    successful = observation("SINGLE", ("FILE_INVENTORY:LIST",))
    invalid = ProviderObservation(
        status=ObservationStatus.INVALID_RESPONSE,
        provider="api.typesafe.ai",
        model="jev-latest",
        model_version="jev-1.13.0",
        criteria_version=CRITERIA_VERSION,
        http_status=200,
        provenance={
            "validation_stage": "assembly",
            "validation_error_code": "OPERATION_SLOT_REQUIRED",
        },
    )
    records = [
        {
            "id": c.id,
            "identity": identity(c, settings()),
            "gold": c.model_dump(mode="json"),
            "fresh": False,
            "observation": (invalid if c.id == "routing-112" else successful).model_dump(
                mode="json"
            ),
        }
        for c in cases[:112]
    ]
    monkeypatch.setattr("evaluation.typesafe_full.replay_checkpoint", lambda *_: records.copy())
    sent = []

    class FakeRouter:
        async def route(
            self, request: RoutingInput, *, idempotency_key: str
        ) -> ProviderObservation:
            sent.append(request.question)
            return invalid if len(sent) == 1 else successful

    async def no_wait(_: float) -> None:
        pass

    monkeypatch.setattr("evaluation.typesafe_full.asyncio.sleep", no_wait)
    result, _ = await run_full(
        settings(),
        tmp_path,
        FakeRouter(),
        resume_from=Path("synthetic.jsonl"),
        allow_structural_invalid=True,
    )
    assert sent == [c.question for c in cases[112:]]
    assert len(sent) == 8
    assert result["cases"][111]["observation"]["status"] == "INVALID_RESPONSE"
    assert result["cases"][112]["observation"]["status"] == "INVALID_RESPONSE"
    assert result["operational"]["reused_existing"] == 112
