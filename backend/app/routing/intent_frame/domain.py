"""Semantic intent only; no database identities or provider observations."""

from types import MappingProxyType
from typing import Annotated, Literal, TypeAlias
from pydantic import Field, model_validator
from .references import (
    ContractModel,
    InputIdentity,
    InputSpan,
    TargetReference,
    NoTargetReference,
    HistoryReference,
    PriorTopicReference,
    ResultReference,
)
from .scope import SemanticScope, InventoryOrdering, ExplicitFileTargetScope, NoFileScope

Capability: TypeAlias = Literal[
    "FILE_INVENTORY",
    "FILE_TARGET",
    "COLLECTION_SUMMARY",
    "GROUNDED_RAG",
    "CONVERSATION_HISTORY",
    "CHITCHAT",
]
Operation: TypeAlias = Literal[
    "LIST",
    "COUNT",
    "LATEST",
    "OLDEST",
    "SUMMARIZE",
    "ANSWER_QUESTION",
    "SUMMARIZE_EACH",
    "ANSWER",
    "RECALL",
    "RESPOND",
]
OPERATIONS = MappingProxyType(
    {
        "FILE_INVENTORY": frozenset({"LIST", "COUNT", "LATEST", "OLDEST"}),
        "FILE_TARGET": frozenset({"SUMMARIZE", "ANSWER_QUESTION"}),
        "COLLECTION_SUMMARY": frozenset({"SUMMARIZE_EACH"}),
        "GROUNDED_RAG": frozenset({"ANSWER"}),
        "CONVERSATION_HISTORY": frozenset({"RECALL"}),
        "CHITCHAT": frozenset({"RESPOND"}),
    }
)


class IntentStep(ContractModel):
    position: int = Field(ge=1, le=3)
    capability: Capability
    operation: Operation
    target: TargetReference
    scope: SemanticScope
    source: InputSpan
    query: InputSpan | None = None
    ordering: InventoryOrdering | None = None

    @model_validator(mode="after")
    def compatible_arguments(self) -> "IntentStep":
        if self.operation not in OPERATIONS[self.capability]:
            raise ValueError("incompatible capability/operation")
        if self.query is not None and not (
            self.source.start <= self.query.start < self.query.end <= self.source.end
        ):
            raise ValueError("query span must be within source span")
        if self.capability == "FILE_INVENTORY" and self.operation == "LIST":
            if self.ordering is None:
                raise ValueError("LIST requires explicit ordering, including DEFAULT")
        elif self.ordering is not None:
            raise ValueError("ordering belongs only to inventory LIST")
        if self.capability in {"FILE_INVENTORY", "COLLECTION_SUMMARY"}:
            if not isinstance(self.target, NoTargetReference) or isinstance(
                self.scope, (ExplicitFileTargetScope, NoFileScope)
            ):
                raise ValueError("collection operation requires collection semantics")
        elif self.capability == "FILE_TARGET":
            if isinstance(
                self.target, (NoTargetReference, PriorTopicReference, HistoryReference)
            ) or not isinstance(self.scope, ExplicitFileTargetScope):
                raise ValueError(
                    "file operation requires exactly one file reference and explicit target scope"
                )
        elif self.capability == "GROUNDED_RAG":
            if not isinstance(self.target, (NoTargetReference, PriorTopicReference)) or isinstance(
                self.scope, (ExplicitFileTargetScope, NoFileScope)
            ):
                raise ValueError("grounded operation requires query/topic and collection scope")
        elif self.capability == "CONVERSATION_HISTORY":
            if not isinstance(self.target, HistoryReference) or not isinstance(
                self.scope, NoFileScope
            ):
                raise ValueError("history operation requires history reference")
        elif not isinstance(self.target, NoTargetReference) or not isinstance(
            self.scope, NoFileScope
        ):
            raise ValueError("social operation cannot carry file arguments")
        requires_query = self.capability == "GROUNDED_RAG" or self.operation == "ANSWER_QUESTION"
        if requires_query != (self.query is not None):
            raise ValueError("query provenance required only for question/grounded operations")
        return self


class RequestedIntent(ContractModel):
    kind: Literal["REQUESTED"] = "REQUESTED"
    prepared_input_identity: InputIdentity
    steps: tuple[IntentStep, ...] = Field(min_length=1, max_length=3)

    @property
    def cardinality(self) -> int:
        return len(self.steps)

    @model_validator(mode="after")
    def ordered_steps(self) -> "RequestedIntent":
        if tuple(s.position for s in self.steps) != tuple(range(1, len(self.steps) + 1)):
            raise ValueError("positions must be contiguous and ordered")
        for s in self.steps:
            if (
                isinstance(s.target, ResultReference)
                and s.target.producer_step_position >= s.position
            ):
                raise ValueError("result producer must exist earlier in this bundle")
        return self


class UnsupportedIntent(ContractModel):
    kind: Literal["UNSUPPORTED"] = "UNSUPPORTED"
    prepared_input_identity: InputIdentity
    source: InputSpan
    reason: Literal[
        "OPERATION_UNSUPPORTED", "SCOPE_UNSUPPORTED", "OVER_LIMIT", "RESULT_SELECTION_UNSUPPORTED"
    ]


class UninterpretableIntent(ContractModel):
    kind: Literal["UNINTERPRETABLE"] = "UNINTERPRETABLE"
    prepared_input_identity: InputIdentity
    source: InputSpan
    reason: Literal["AMBIGUOUS_MEANING", "INSUFFICIENT_SEMANTIC_INFORMATION"]


IntentFrame: TypeAlias = Annotated[
    RequestedIntent | UnsupportedIntent | UninterpretableIntent, Field(discriminator="kind")
]
