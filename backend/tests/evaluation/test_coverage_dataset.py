"""Frozen verifier pairs, split isolation, provenance and privacy; no API calls."""

import json

import pytest
from pydantic import ValidationError

from evaluation.coverage_dataset import ROOT, CoverageDataset, load, sha
from evaluation.coverage_review import review
from app.routing.v2.coverage import CoverageInput
from app.routing.v2.coverage.contracts import contract_identity, verify_lock
from app.routing.v2.contracts import verify_lock as routing_lock


def test_frozen_dataset_counts_and_coverage() -> None:
    dataset, fixtures = load()
    assert len(dataset.cases) == 80 and len(fixtures.contexts) == 9
    audit = review()
    assert audit["splits"] == {"development": 32, "held_out": 48}
    assert audit["held_out_verdicts"] == {"PRESERVED": 24, "MISMATCH": 20, "UNCERTAIN": 4}
    assert audit["verdicts"] == {"PRESERVED": 38, "MISMATCH": 38, "UNCERTAIN": 4}
    historical_ids = audit["historical_unsafe_development_ids"]
    assert isinstance(historical_ids, list)
    assert set(historical_ids) == {
        "v2-146",
        "v2-149",
        "v2-150",
        "v2-153",
        "v2-154",
        "v2-155",
        "v2-161",
        "v2-163",
        "v2-176",
        "v2-177",
        "v2-180",
    }
    assert (
        audit["exact_held_out_routing_reuse"] == []
        and audit["near_cross_split"] == []
        and audit["near_held_out_routing"] == []
    )
    for case in dataset.cases:
        assert CoverageInput.model_validate_json(case.input.model_dump_json()) == case.input
        payload = json.dumps(case.input.provider_state())
        for field in [
            "file_id",
            "active_file_ids",
            "snapshot_identity",
            "Authorization",
            "api_key",
            "router_probabilities",
        ]:
            assert field not in payload


def test_freeze_hashes() -> None:
    freeze = json.loads((ROOT / "coverage_v1_freeze.json").read_text())
    assert (
        freeze["dataset_sha256"]
        == "e1100fff7923a13bc831fb1940f9eb39b2a172cbc82b22c53c30a9ce2c67f888"
    )
    assert (
        freeze["fixture_sha256"]
        == "de9bdd210a5615d1e4b81444d450031024aec64fd92adacbbc4f64309f399082"
    )
    assert freeze["dataset_sha256"] == sha(ROOT / "coverage_v1.json")
    assert freeze["fixture_sha256"] == sha(ROOT / "coverage_v1_fixtures.json")
    assert freeze["schema_sha256"] == sha(ROOT / "coverage_v1.schema.json")
    assert freeze["contract_identity"] == contract_identity() and verify_lock() and routing_lock()
    assert freeze["review"] == review()
    assert (
        json.loads((ROOT / "coverage_v1.schema.json").read_text())
        == CoverageDataset.model_json_schema()
    )


@pytest.mark.parametrize(
    "defect",
    [
        "duplicate_id",
        "split_count",
        "cross_split_group",
        "gold",
        "historical_held_out",
        "cardinality",
        "operation",
        "source_span",
        "filename",
        "unknown_db_field",
        "input_identity",
    ],
)
def test_invalid_pair_rejected(defect: str) -> None:
    data = json.loads((ROOT / "coverage_v1.json").read_text())
    case = data["cases"][0]
    if defect == "duplicate_id":
        data["cases"][1]["id"] = case["id"]
    elif defect == "split_count":
        case["split"] = "held_out"
    elif defect == "cross_split_group":
        data["cases"][32]["scenario_group"] = case["scenario_group"]
    elif defect == "gold":
        case["expected_verdict"] = "APPROVE"
    elif defect == "historical_held_out":
        data["cases"][32]["source_routing_case"] = "v2-001"
    elif defect == "cardinality":
        case["input"]["interpretation"]["proposed_cardinality"] = "THREE"
    elif defect == "operation":
        case["input"]["interpretation"]["requests"][0]["operation"] = "DELETE"
    elif defect == "source_span":
        case["input"]["interpretation"]["requests"][0]["source_span"]["end"] = 7999
    elif defect == "filename":
        case["input"]["interpretation"]["requests"][0]["reference"] = {
            "kind": "LITERAL_FILE",
            "current_input_span": {"start": 0, "end": 4},
            "current_input_filename": "invented_name.pdf",
        }
    elif defect == "unknown_db_field":
        case["input"]["interpretation"]["requests"][0]["db_id"] = "secret-uuid"
    else:
        case["input"]["input_identity"] = "0" * 64
    with pytest.raises(ValidationError):
        CoverageDataset.model_validate(data)
