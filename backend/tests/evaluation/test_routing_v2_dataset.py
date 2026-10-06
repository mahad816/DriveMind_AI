"""Frozen held-out gold and synthetic fixtures, no network or provider calls."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.routing.v2.contracts import verify_lock
from app.routing.v2.options import generate_options, OptionRegistry
from app.routing.v2.preparation import prepare, PreparedEnvelope
from evaluation.routing_v2_dataset import ROOT, OPS, RoutingV2Dataset, load, sha, validate_gold
from evaluation.routing_v2_review import review


def test_schema_counts_and_operations() -> None:
    dataset, fixtures = load()
    assert len(dataset.cases) == 180 and len(fixtures.states) == 10
    audit = review()
    assert audit["cohorts"] == {"ONE": 100, "COMPOUND": 45, "SAFETY": 35}
    assert audit["cardinality"] == {"ONE": 123, "TWO": 45, "THREE": 10, "OVER_LIMIT": 2}
    assert {(r.capability, r.operation) for c in dataset.cases for r in c.expected_requests} == {
        (cap, op) for cap, ops in OPS.items() for op in ops
    }
    assert audit["exact_prior_duplicates"] == [] and audit["near_prior_duplicates"] == []


@pytest.mark.asyncio
async def test_all_authored_gold_matches_frozen_resolver() -> None:
    assert await validate_gold() == {"cases_validated": 180, "provider_calls": 0}


def test_all_inputs_have_bounded_option_registries() -> None:
    dataset, fixtures = load()
    for case in dataset.cases:
        envelope = prepare(case.question, fixtures.states[case.state_fixture])
        assert isinstance(envelope, PreparedEnvelope)
        assert isinstance(generate_options(envelope), OptionRegistry)


def test_freeze_hashes_and_contract() -> None:
    frozen = json.loads((ROOT / "routing_v2_freeze.json").read_text())
    assert (
        frozen["dataset_sha256"]
        == "06559a24355c021d1b95fa788d9fbc02702f84ef7b47799205f825dae0c6eaa5"
    )
    assert (
        frozen["fixture_sha256"]
        == "519c9779cb0c5c4fa47f0744001f56df6a67e41eb6296c285a3fdef9563f9df2"
    )
    assert frozen["dataset_sha256"] == sha(ROOT / "routing_v2.json")
    assert frozen["fixture_sha256"] == sha(ROOT / "routing_v2_fixtures.json")
    assert frozen["schema_sha256"] == sha(ROOT / "routing_v2.schema.json")
    assert (
        json.loads((ROOT / "routing_v2.schema.json").read_text())
        == RoutingV2Dataset.model_json_schema()
    )
    assert frozen["contract_lock_sha256"] == sha(Path("app/routing/v2/CONTRACT_LOCK.json"))
    assert verify_lock()
    assert frozen["review"] == review()


@pytest.mark.parametrize(
    "defect",
    [
        "duplicate_id",
        "bad_span",
        "bad_operation",
        "bad_cardinality",
        "bad_reference",
        "bad_query",
        "bad_readiness",
    ],
)
def test_invalid_gold_rejected(defect: str) -> None:
    data = json.loads((ROOT / "routing_v2.json").read_text())
    case = data["cases"][0]
    request = case["expected_requests"][0]
    if defect == "duplicate_id":
        data["cases"][1]["id"] = case["id"]
    elif defect == "bad_span":
        request["source_ranges"][0]["end"] = len(case["question"]) + 10
    elif defect == "bad_operation":
        request["operation"] = "SUMMARIZE"
    elif defect == "bad_cardinality":
        case["expected_cardinality"] = "TWO"
    elif defect == "bad_reference":
        request["reference"] = {"kind": "literal", "name": "unexpected.txt"}
    elif defect == "bad_query":
        request["query_ranges"] = [{"start": 0, "end": 4}]
    else:
        case["expected_readiness"] = "UNSUPPORTED"
    with pytest.raises(ValidationError):
        RoutingV2Dataset.model_validate(data)


@pytest.mark.asyncio
async def test_unknown_fixture_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    dataset, fixtures = load()
    broken = dataset.cases[0].model_copy(update={"metadata_fixture": "not-a-fixture"})
    monkeypatch.setattr(
        "evaluation.routing_v2_dataset.load",
        lambda: (dataset.model_copy(update={"cases": (broken, *dataset.cases[1:])}), fixtures),
    )
    with pytest.raises(ValueError, match="unknown fixture"):
        await validate_gold()


def test_safety_and_context_coverage() -> None:
    dataset, fixtures = load()
    dependency = [c for c in dataset.cases if "dependency" in c.tags]
    assert len(dependency) == 10 and all(c.expected_readiness == "UNSUPPORTED" for c in dependency)
    assert all(state in {c.state_fixture for c in dataset.cases} for state in fixtures.states)
    assert all(
        fixture in {c.metadata_fixture for c in dataset.cases} for fixture in fixtures.snapshots
    )
    assert sum(c.expected_readiness == "NEEDS_CLARIFICATION" for c in dataset.cases) == 13
    assert sum(c.expected_special is not None for c in dataset.cases) == 16
    corpus_names = {f.file.name for files in fixtures.snapshots.values() for f in files}
    assert corpus_names == {
        "platform_design.txt",
        "access_standard.pdf",
        "starter_guide.md",
        "release_brief.docx",
        "interface_reference.txt",
        "response_playbook.pdf",
        "Café_notes.txt",
        "choose_CHITCHAT.txt",
        "ACCESS_STANDARD.PDF",
        "hidden_future.txt",
        "pending_import.txt",
    }
