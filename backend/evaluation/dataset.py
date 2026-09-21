"""Typed loading and structural validation for evaluation datasets."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.retrieval.query_router import QueryRoute

_TOP_LEVEL_FIELDS = {
    "dataset_id",
    "schema_version",
    "corpus_id",
    "case_count",
    "description",
    "evaluation_notes",
    "cases",
}
_CASE_FIELDS = {
    "id",
    "question",
    "expected_route",
    "expected_files",
    "should_answer",
    "reference_answer",
    "must_include",
    "must_not_include",
    "evidence_anchors",
    "tags",
}
_VALID_ROUTES = frozenset(route.name for route in QueryRoute)


class DatasetValidationError(ValueError):
    """Raised when an evaluation dataset violates its structural contract."""


@dataclass(frozen=True)
class EvaluationCase:
    """One human-authored evaluation case."""

    id: str
    question: str
    expected_route: str
    expected_files: tuple[str, ...]
    should_answer: bool
    reference_answer: str | None
    must_include: tuple[str, ...]
    must_not_include: tuple[str, ...]
    evidence_anchors: tuple[str, ...]
    tags: tuple[str, ...]


@dataclass(frozen=True)
class EvaluationDataset:
    """Validated evaluation dataset metadata and cases."""

    dataset_id: str
    schema_version: str
    corpus_id: str
    case_count: int
    description: str
    evaluation_notes: tuple[tuple[str, str], ...]
    cases: tuple[EvaluationCase, ...]


def load_dataset(path: str | Path) -> EvaluationDataset:
    """Load UTF-8 JSON and validate the stable evaluation dataset structure.

    This deliberately does not inspect PostgreSQL, Qdrant, or corpus lifecycle state.
    Those environment-dependent checks belong to the future runner preflight.
    """
    dataset_path = Path(path)
    try:
        raw = json.loads(dataset_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DatasetValidationError(f"Invalid JSON dataset: {exc}") from exc

    data = _require_object(raw, "dataset")
    _require_exact_fields(data, _TOP_LEVEL_FIELDS, "dataset")

    dataset_id = _require_non_empty_string(data["dataset_id"], "dataset_id")
    schema_version = _require_non_empty_string(data["schema_version"], "schema_version")
    corpus_id = _require_non_empty_string(data["corpus_id"], "corpus_id")
    description = _require_string(data["description"], "description")
    case_count = data["case_count"]
    if type(case_count) is not int or case_count < 0:
        raise DatasetValidationError("case_count must be a non-negative integer")

    notes_object = _require_object(data["evaluation_notes"], "evaluation_notes")
    notes: list[tuple[str, str]] = []
    for key, value in notes_object.items():
        notes.append(
            (
                _require_non_empty_string(key, "evaluation_notes key"),
                _require_string(value, f"evaluation_notes.{key}"),
            )
        )

    raw_cases = data["cases"]
    if not isinstance(raw_cases, list):
        raise DatasetValidationError("cases must be a list")
    if case_count != len(raw_cases):
        raise DatasetValidationError(
            f"case_count is {case_count}, but cases contains {len(raw_cases)} entries"
        )

    cases = tuple(_parse_case(value, index) for index, value in enumerate(raw_cases))
    _require_unique((case.id for case in cases), "case IDs")
    _require_unique((case.question.strip() for case in cases), "case questions")

    return EvaluationDataset(
        dataset_id=dataset_id,
        schema_version=schema_version,
        corpus_id=corpus_id,
        case_count=case_count,
        description=description,
        evaluation_notes=tuple(notes),
        cases=cases,
    )


def _parse_case(raw: Any, index: int) -> EvaluationCase:
    label = f"cases[{index}]"
    case = _require_object(raw, label)
    _require_exact_fields(case, _CASE_FIELDS, label)

    route = _require_non_empty_string(case["expected_route"], f"{label}.expected_route")
    if route not in _VALID_ROUTES:
        valid = ", ".join(sorted(_VALID_ROUTES))
        raise DatasetValidationError(f"{label}.expected_route must be one of: {valid}")

    expected_files = _require_string_list(case["expected_files"], f"{label}.expected_files")
    tags = _require_string_list(case["tags"], f"{label}.tags", non_empty=True)
    _require_unique(expected_files, f"{label}.expected_files")
    _require_unique(tags, f"{label}.tags")

    should_answer = case["should_answer"]
    if type(should_answer) is not bool:
        raise DatasetValidationError(f"{label}.should_answer must be a boolean")

    reference_answer = case["reference_answer"]
    if reference_answer is not None and not isinstance(reference_answer, str):
        raise DatasetValidationError(f"{label}.reference_answer must be a string or null")

    return EvaluationCase(
        id=_require_non_empty_string(case["id"], f"{label}.id"),
        question=_require_non_empty_string(case["question"], f"{label}.question"),
        expected_route=route,
        expected_files=expected_files,
        should_answer=should_answer,
        reference_answer=reference_answer,
        must_include=_require_string_list(case["must_include"], f"{label}.must_include"),
        must_not_include=_require_string_list(
            case["must_not_include"], f"{label}.must_not_include"
        ),
        evidence_anchors=_require_string_list(
            case["evidence_anchors"], f"{label}.evidence_anchors"
        ),
        tags=tags,
    )


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise DatasetValidationError(f"{label} must be an object with string keys")
    return value


def _require_exact_fields(value: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual == expected:
        return
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    details: list[str] = []
    if missing:
        details.append(f"missing {missing}")
    if extra:
        details.append(f"unexpected {extra}")
    raise DatasetValidationError(f"{label} fields invalid: {', '.join(details)}")


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise DatasetValidationError(f"{label} must be a string")
    return value


def _require_non_empty_string(value: Any, label: str) -> str:
    text = _require_string(value, label)
    if not text.strip():
        raise DatasetValidationError(f"{label} must be a non-empty string")
    return text


def _require_string_list(
    value: Any,
    label: str,
    *,
    non_empty: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise DatasetValidationError(f"{label} must be a list of strings")
    if non_empty and not value:
        raise DatasetValidationError(f"{label} must not be empty")
    return tuple(_require_non_empty_string(item, f"{label} item") for item in value)


def _require_unique(values: Iterable[str], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise DatasetValidationError(f"{label} contains duplicate value: {value!r}")
        seen.add(value)
