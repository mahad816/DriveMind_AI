"""Strict routing gold loader; no service or provider dependencies."""

import json
from pathlib import Path
from typing import Literal

from pydantic import Field, StrictBool, StrictInt, model_validator

from app.routing.contract import (
    ClarificationReason,
    ExpectedRequest,
    RoutingMode,
    StrictModel,
)


class HistoryTurn(StrictModel):
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=8000)


class RoutingCase(StrictModel):
    id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    history: list[HistoryTurn] = Field(default_factory=list, max_length=8)
    history_window_complete: StrictBool
    expected_mode: RoutingMode
    expected_requests: list[ExpectedRequest] = Field(max_length=3)
    expected_clarification_reason: ClarificationReason | None = None
    difficulty: Literal["straightforward", "paraphrase", "boundary", "contextual", "adversarial"]
    tags: list[str]
    notes: str

    @model_validator(mode="after")
    def valid_case(self) -> "RoutingCase":
        if not self.id.strip() or not self.question.strip():
            raise ValueError("ID and question must not be blank")
        if any(not turn.text.strip() for turn in self.history):
            raise ValueError("history must not be blank")
        if sum(len(turn.text) for turn in self.history) > 24000:
            raise ValueError("history exceeds 24000 characters")
        size = len(self.expected_requests)
        if self.expected_mode == RoutingMode.SINGLE and size != 1:
            raise ValueError("SINGLE requires exactly one request")
        if self.expected_mode == RoutingMode.COMPOUND and size not in (2, 3):
            raise ValueError("COMPOUND requires two or three requests")
        if self.expected_mode == RoutingMode.CLARIFY:
            if size or self.expected_clarification_reason is None:
                raise ValueError("CLARIFY requires no requests and a reason")
        elif self.expected_clarification_reason is not None:
            raise ValueError("executable modes cannot have a clarification reason")
        if len(set(self.tags)) != len(self.tags) or any(not tag.strip() for tag in self.tags):
            raise ValueError("tags must be unique and nonblank")
        return self


class RoutingDataset(StrictModel):
    dataset_id: Literal["routing_v1"]
    schema_version: Literal["routing-1.0"]
    case_count: StrictInt = Field(ge=1)
    description: str
    policy_notes: list[str]
    cases: list[RoutingCase]

    @model_validator(mode="after")
    def valid_dataset(self) -> "RoutingDataset":
        if self.case_count != len(self.cases):
            raise ValueError("case_count does not match cases")
        ids = [case.id for case in self.cases]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate case IDs")
        return self


def load_routing_dataset(path: str | Path) -> RoutingDataset:
    return RoutingDataset.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
