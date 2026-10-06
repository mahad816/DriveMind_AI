"""Scoring semantics remain separate from span/readiness and provider validity."""

import json
from pathlib import Path

from evaluation.routing_v2_dataset import load
from evaluation.routing_v2_metrics import analyze, predicted_request, signature


def test_binding_signature_excludes_spans() -> None:
    dataset, _ = load()
    gold = dataset.cases[0].expected_requests[0].model_dump(mode="json")
    prediction = predicted_request(
        {
            "capability": "FILE_INVENTORY",
            "operation": "LIST",
            "ordering": "NAME_ASC",
            "input_span": {"start": 0, "end": 1},
        },
        {"input": {"candidates": [], "question": "x"}},
    )
    assert signature(prediction) == signature(gold)
    prediction["ordering"] = "NAME_DESC"
    assert signature(prediction) != signature(gold)


def test_missing_observations_remain_in_denominator(tmp_path: Path) -> None:
    path = tmp_path / "result.json"
    path.write_text(json.dumps({"cases": []}))
    report = analyze(path)
    assert report["core"]["cardinality_accuracy"] == {
        "numerator": 0,
        "denominator": 180,
        "value": 0.0,
    }
    assert report["core"]["exact_semantic_bundle"]["numerator"] == 0
    assert report["core"]["one_capability_operation"]["denominator"] > 100
    assert report["core"]["unsafe_ready_count"] == 0
    assert report["gates"]["cardinality"] == "FAIL"
