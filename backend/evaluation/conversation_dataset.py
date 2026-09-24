"""Strict, separate dataset contract for EXP-03 multi-turn evaluation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    ValidationError,
    model_validator,
)

from app.retrieval.query_router import QueryRoute
from app.schemas.chat import ChatHistoryTurn


class ConversationDatasetError(ValueError):
    """The conversational dataset is not safe to execute."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OtherConversation(StrictModel):
    conversation_id: str = Field(min_length=1)
    history: list[ChatHistoryTurn] = Field(max_length=8)


class RouteExpectation(StrictModel):
    mode: Literal["exact", "exclude"]
    route: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_route(self) -> RouteExpectation:
        if self.route not in QueryRoute.__members__:
            raise ValueError("route expectation must name a known production route")
        return self


class ConversationExpected(StrictModel):
    route: str | None = None  # Frozen v1 legacy exact-route field.
    route_expectation: RouteExpectation | None = None
    target_role: Literal["user", "assistant"] | None
    reference_kind: str | None
    selector_outcome: str | None
    selected_history_index: StrictInt | None
    selected_text: str | None
    retrieval_should_run: StrictBool | None
    retrieval_count: StrictInt | None
    citations: list[str] | None

    @model_validator(mode="after")
    def validate_route_choice(self) -> ConversationExpected:
        if (self.route is None) == (self.route_expectation is None):
            raise ValueError("expected route requires exactly one legacy or explicit expectation")
        if self.route is not None and self.route not in QueryRoute.__members__:
            raise ValueError("expected route is not a known production route")
        return self

    @property
    def route_rule(self) -> RouteExpectation:
        if self.route_expectation is not None:
            return self.route_expectation
        assert self.route is not None  # Validated above.
        return RouteExpectation(mode="exact", route=self.route)


class ConversationEvalCase(StrictModel):
    id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    history_window_complete: StrictBool
    history: list[ChatHistoryTurn] = Field(max_length=8)
    other_conversations: list[OtherConversation] = Field(default_factory=list)
    question: str = Field(min_length=1)
    expected: ConversationExpected
    tags: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_case(self) -> ConversationEvalCase:
        if not self.id.strip() or not self.conversation_id.strip() or not self.question.strip():
            raise ValueError("case id, conversation ID, and question must not be blank")
        if len(set(self.tags)) != len(self.tags) or any(not tag.strip() for tag in self.tags):
            raise ValueError("tags must be unique and nonblank")
        if sum(len(turn.text) for turn in self.history) > 24_000:
            raise ValueError("history exceeds 24,000 characters")
        other_ids = [other.conversation_id for other in self.other_conversations]
        if self.conversation_id in other_ids or len(set(other_ids)) != len(other_ids):
            raise ValueError("other conversations must have distinct IDs from active history")
        for other in self.other_conversations:
            if sum(len(turn.text) for turn in other.history) > 24_000:
                raise ValueError("other conversation history exceeds 24,000 characters")

        expected = self.expected
        route_rule = expected.route_rule
        if route_rule.mode == "exclude" and (
            route_rule.route != QueryRoute.CONVERSATION_HISTORY.name
            or "negative_document_control" not in self.tags
        ):
            raise ValueError("document exclusion must target CONVERSATION_HISTORY")
        if route_rule.mode != "exact" or route_rule.route != QueryRoute.CONVERSATION_HISTORY.name:
            if any(
                value is not None
                for value in (
                    expected.target_role,
                    expected.reference_kind,
                    expected.selector_outcome,
                    expected.selected_history_index,
                    expected.selected_text,
                    expected.retrieval_should_run,
                    expected.retrieval_count,
                    expected.citations,
                )
            ):
                raise ValueError(
                    "document controls must use null selector and retrieval expectations"
                )
            return self

        if expected.retrieval_should_run is not False or expected.retrieval_count != 0:
            raise ValueError("conversation-only cases must expect zero retrieval")
        if expected.citations != []:
            raise ValueError("conversation-only cases must expect zero citations")
        if expected.target_role is None:
            raise ValueError("conversation-only cases need a target role")
        if expected.reference_kind not in {"LATEST_SUPPORTED", "UNSUPPORTED_ORDINAL_REFERENCE"}:
            raise ValueError("invalid conversation reference kind")
        if expected.selector_outcome not in {
            "SELECTED",
            "NO_HISTORY",
            "ROLE_NOT_PRESENT",
            "UNAVAILABLE_IN_BOUNDED_HISTORY",
            "UNSUPPORTED_ORDINAL_REFERENCE",
        }:
            raise ValueError("invalid selector outcome")

        if expected.reference_kind == "UNSUPPORTED_ORDINAL_REFERENCE":
            if expected.selector_outcome != "UNSUPPORTED_ORDINAL_REFERENCE":
                raise ValueError("ordinal reference must have unsupported ordinal outcome")
        elif expected.selector_outcome == "UNSUPPORTED_ORDINAL_REFERENCE":
            raise ValueError("unsupported ordinal outcome requires ordinal reference")

        index = expected.selected_history_index
        text = expected.selected_text
        if expected.selector_outcome == "SELECTED":
            if index is None or index < 0 or index >= len(self.history) or text is None:
                raise ValueError("selected index/text must identify a supplied history turn")
            selected = self.history[index]
            if selected.role != expected.target_role or selected.text != text:
                raise ValueError("selected index/text/role disagree with history")
            if any(turn.role == expected.target_role for turn in self.history[index + 1 :]):
                raise ValueError("selected index is not the latest requested role")
        elif index is not None or text is not None:
            noun = (
                "ordinal"
                if expected.selector_outcome == "UNSUPPORTED_ORDINAL_REFERENCE"
                else "unavailable"
            )
            raise ValueError(f"{noun} outcome must not select a turn")

        if expected.selector_outcome == "NO_HISTORY" and (
            self.history or not self.history_window_complete
        ):
            raise ValueError("NO_HISTORY needs empty complete history")
        if expected.selector_outcome == "ROLE_NOT_PRESENT" and (
            not self.history
            or not self.history_window_complete
            or any(turn.role == expected.target_role for turn in self.history)
        ):
            raise ValueError("ROLE_NOT_PRESENT needs nonempty complete history lacking that role")
        if expected.selector_outcome == "UNAVAILABLE_IN_BOUNDED_HISTORY" and (
            self.history_window_complete
            or any(turn.role == expected.target_role for turn in self.history)
        ):
            raise ValueError("bounded unavailable needs incomplete history lacking that role")
        return self


class ConversationEvalDataset(StrictModel):
    dataset_id: str = Field(min_length=1)
    schema_version: str
    case_count: StrictInt = Field(ge=0)
    description: str
    evaluation_notes: dict[str, str]
    cases: list[ConversationEvalCase]

    @model_validator(mode="after")
    def validate_dataset(self) -> ConversationEvalDataset:
        if (
            self.dataset_id
            not in {
                "conversational_followup_v1",
                "conversational_followup_v2",
            }
            or self.schema_version != "conversation-1.0"
        ):
            raise ValueError("unsupported conversation dataset identity/schema")
        if self.dataset_id == "conversational_followup_v1" and any(
            case.expected.route_expectation is not None for case in self.cases
        ):
            raise ValueError("v1 must retain legacy exact-route expectations")
        if self.case_count != len(self.cases):
            raise ValueError("case_count does not match cases")
        ids = [case.id for case in self.cases]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate case IDs")
        return self


def load_conversation_dataset(path: str | Path) -> ConversationEvalDataset:
    """Load without touching Gold, providers, PostgreSQL, or Qdrant."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return ConversationEvalDataset.model_validate(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
        raise ConversationDatasetError(str(exc)) from exc
