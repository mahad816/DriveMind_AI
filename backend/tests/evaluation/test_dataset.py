"""Tests for the pure evaluation dataset loader."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evaluation.dataset import DatasetValidationError, load_dataset


def _case(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": "case_001",
        "question": "Which synthetic file contains the answer?",
        "expected_route": "GROUNDED_RAG",
        "expected_files": ["alpha.txt"],
        "should_answer": True,
        "reference_answer": "Alpha contains it.",
        "must_include": ["Alpha"],
        "must_not_include": [],
        "evidence_anchors": ["Alpha"],
        "tags": ["synthetic"],
    }
    value.update(overrides)
    return value


def _dataset(cases: list[dict[str, object]] | None = None) -> dict[str, object]:
    case_values = cases if cases is not None else [_case()]
    return {
        "dataset_id": "synthetic_v1",
        "schema_version": "1.0",
        "corpus_id": "synthetic_corpus",
        "case_count": len(case_values),
        "description": "Synthetic loader fixture.",
        "evaluation_notes": {"expected_files": "Synthetic evidence sources."},
        "cases": case_values,
    }


def _write_dataset(tmp_path: Path, value: Any) -> Path:
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_valid_dataset_loads_as_typed_values(tmp_path: Path) -> None:
    loaded = load_dataset(_write_dataset(tmp_path, _dataset()))

    assert loaded.dataset_id == "synthetic_v1"
    assert loaded.case_count == 1
    assert loaded.cases[0].expected_files == ("alpha.txt",)
    assert loaded.cases[0].reference_answer == "Alpha contains it."


def test_locked_gold_dataset_passes_structural_validation() -> None:
    path = Path(__file__).parents[2] / "evaluation" / "datasets" / "gold_v1.json"

    loaded = load_dataset(path)

    assert loaded.dataset_id == "drivemind_gold_v1"
    assert loaded.case_count == len(loaded.cases) == 24


@pytest.mark.parametrize(
    ("cases", "message"),
    [
        ([_case(), _case(question="A different question")], "case IDs"),
        ([_case(), _case(id="case_002")], "case questions"),
    ],
)
def test_duplicate_ids_and_questions_are_rejected(
    tmp_path: Path,
    cases: list[dict[str, object]],
    message: str,
) -> None:
    with pytest.raises(DatasetValidationError, match=message):
        load_dataset(_write_dataset(tmp_path, _dataset(cases)))


def test_case_count_mismatch_is_rejected(tmp_path: Path) -> None:
    value = _dataset()
    value["case_count"] = 2

    with pytest.raises(DatasetValidationError, match="case_count is 2"):
        load_dataset(_write_dataset(tmp_path, value))


def test_invalid_route_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(DatasetValidationError, match="expected_route"):
        load_dataset(_write_dataset(tmp_path, _dataset([_case(expected_route="unknown")])))


def test_missing_required_case_field_is_rejected(tmp_path: Path) -> None:
    case = _case()
    del case["question"]

    with pytest.raises(DatasetValidationError, match="missing.*question"):
        load_dataset(_write_dataset(tmp_path, _dataset([case])))


def test_malformed_list_field_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(DatasetValidationError, match="expected_files must be a list"):
        load_dataset(_write_dataset(tmp_path, _dataset([_case(expected_files="alpha.txt")])))


@pytest.mark.parametrize("reference_answer", [None, "A supported answer."])
def test_reference_answer_accepts_null_or_string(
    tmp_path: Path, reference_answer: str | None
) -> None:
    loaded = load_dataset(
        _write_dataset(tmp_path, _dataset([_case(reference_answer=reference_answer)]))
    )

    assert loaded.cases[0].reference_answer == reference_answer


def test_duplicate_expected_file_is_rejected(tmp_path: Path) -> None:
    case = _case(expected_files=["alpha.txt", "alpha.txt"])

    with pytest.raises(DatasetValidationError, match="expected_files contains duplicate"):
        load_dataset(_write_dataset(tmp_path, _dataset([case])))


def test_empty_tags_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(DatasetValidationError, match="tags must not be empty"):
        load_dataset(_write_dataset(tmp_path, _dataset([_case(tags=[])])))


def test_duplicate_tags_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(DatasetValidationError, match="tags contains duplicate"):
        load_dataset(_write_dataset(tmp_path, _dataset([_case(tags=["a", "a"])])))
