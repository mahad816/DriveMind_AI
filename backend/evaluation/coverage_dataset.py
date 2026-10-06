"""Frozen verifier comparisons: no routing predictions or provider execution."""

import hashlib
from pathlib import Path
from typing import Literal
from collections import Counter

from pydantic import Field, model_validator

from app.routing.v2 import domain as d
from app.routing.v2.coverage import CoverageInput, CoverageContext, CoverageVerdict
from app.routing.v2.coverage.contracts import contract_identity, verify_lock

ROOT = Path(__file__).parent / "datasets"


class CoverageCase(d.DomainModel):
    id: str = Field(pattern=r"^coverage-[0-9]{3}$")
    split: Literal["development", "held_out"]
    scenario_group: str = Field(min_length=1)
    context_fixture: str = Field(min_length=1)
    input: CoverageInput
    expected_verdict: CoverageVerdict
    family: Literal[
        "faithful",
        "target_change",
        "scope_change",
        "dependency_loss",
        "missing_request",
        "reference_change",
        "unsupported_meaning_loss",
        "uncertain_reference",
        "adversarial",
    ]
    notes: str = Field(min_length=1)
    source_routing_case: str | None = None


class CoverageDataset(d.DomainModel):
    dataset_id: Literal["coverage_v1"]
    schema_version: Literal["coverage-pairs-1.0"]
    synthetic_only: Literal[True]
    contract_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    cases: tuple[CoverageCase, ...] = Field(min_length=80, max_length=80)

    @model_validator(mode="after")
    def valid(self) -> "CoverageDataset":
        if tuple(c.id for c in self.cases) != tuple(f"coverage-{i:03}" for i in range(1, 81)):
            raise ValueError("duplicate/unordered case IDs")
        if Counter(c.split for c in self.cases) != {"development": 32, "held_out": 48}:
            raise ValueError("split counts mismatch")
        held = [c for c in self.cases if c.split == "held_out"]
        if Counter(c.expected_verdict for c in held) != {
            CoverageVerdict.PRESERVED: 24,
            CoverageVerdict.MISMATCH: 20,
            CoverageVerdict.UNCERTAIN: 4,
        }:
            raise ValueError("held-out verdict balance mismatch")
        groups: dict[str, set[str]] = {}
        seen = set()
        for c in self.cases:
            groups.setdefault(c.scenario_group, set()).add(c.split)
            identity = (
                c.input.original_question,
                c.input.interpretation_identity,
                c.input.context_identity,
            )
            if identity in seen:
                raise ValueError("duplicate question/proposal pair")
            seen.add(identity)
            if c.input.contract_identity != self.contract_identity:
                raise ValueError("coverage identity mismatch")
            if c.split == "held_out" and c.source_routing_case is not None:
                raise ValueError("held-out cannot reuse historical routing cases")
        if any(len(splits) > 1 for splits in groups.values()):
            raise ValueError("scenario group crosses splits")
        return self


class CoverageFixtures(d.DomainModel):
    fixture_version: Literal["coverage-context-fixtures-1.0"]
    synthetic_only: Literal[True]
    contexts: dict[str, CoverageContext]
    notes: dict[str, str]

    @model_validator(mode="after")
    def valid(self) -> "CoverageFixtures":
        if set(self.contexts) != set(self.notes):
            raise ValueError("fixture notes mismatch")
        return self


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load() -> tuple[CoverageDataset, CoverageFixtures]:
    dataset = CoverageDataset.model_validate_json((ROOT / "coverage_v1.json").read_text())
    fixtures = CoverageFixtures.model_validate_json(
        (ROOT / "coverage_v1_fixtures.json").read_text()
    )
    if not verify_lock() or dataset.contract_identity != contract_identity():
        raise ValueError("coverage contract mismatch")
    for c in dataset.cases:
        if (
            c.context_fixture not in fixtures.contexts
            or c.input.context != fixtures.contexts[c.context_fixture]
        ):
            raise ValueError("context fixture mismatch")
    return dataset, fixtures
