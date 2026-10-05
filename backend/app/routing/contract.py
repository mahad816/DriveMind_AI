"""Minimal semantic labels for observational routing evaluation."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


class RoutingMode(StrEnum):
    SINGLE = "SINGLE"
    COMPOUND = "COMPOUND"
    CLARIFY = "CLARIFY"


class Capability(StrEnum):
    CONVERSATION_HISTORY = "CONVERSATION_HISTORY"
    CHITCHAT = "CHITCHAT"
    FILE_INVENTORY = "FILE_INVENTORY"
    FILE_TARGET = "FILE_TARGET"
    COLLECTION_SUMMARY = "COLLECTION_SUMMARY"
    GROUNDED_RAG = "GROUNDED_RAG"


class Operation(StrEnum):
    LIST = "LIST"
    COUNT = "COUNT"
    LATEST = "LATEST"
    OLDEST = "OLDEST"
    SUMMARIZE = "SUMMARIZE"
    ANSWER_QUESTION = "ANSWER_QUESTION"
    SUMMARIZE_EACH = "SUMMARIZE_EACH"
    RECALL = "RECALL"
    ANSWER = "ANSWER"
    RESPOND = "RESPOND"


OPERATIONS: dict[Capability, frozenset[Operation]] = {
    Capability.FILE_INVENTORY: frozenset(
        {Operation.LIST, Operation.COUNT, Operation.LATEST, Operation.OLDEST}
    ),
    Capability.FILE_TARGET: frozenset({Operation.SUMMARIZE, Operation.ANSWER_QUESTION}),
    Capability.COLLECTION_SUMMARY: frozenset({Operation.SUMMARIZE_EACH}),
    Capability.CONVERSATION_HISTORY: frozenset({Operation.RECALL}),
    Capability.GROUNDED_RAG: frozenset({Operation.ANSWER}),
    Capability.CHITCHAT: frozenset({Operation.RESPOND}),
}


class ClarificationReason(StrEnum):
    UNRESOLVED_REFERENCE = "UNRESOLVED_REFERENCE"
    AMBIGUOUS_TARGET = "AMBIGUOUS_TARGET"
    MISSING_SCOPE = "MISSING_SCOPE"
    MISSING_ARGUMENT = "MISSING_ARGUMENT"
    COMPETING_INTERPRETATIONS = "COMPETING_INTERPRETATIONS"
    UNSUPPORTED_OPERATION = "UNSUPPORTED_OPERATION"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ArgumentConstraints(StrictModel):
    """Gold assertions, not executable arguments or an executor contract."""

    target_name: str | None = None
    target_selector: Literal["LATEST", "OLDEST"] | None = None
    scope: Literal["ALL_INDEXED"] | None = None
    ordering: Literal["NAME_ASC", "NAME_DESC", "MODIFIED_AT_ASC", "MODIFIED_AT_DESC"] | None = None
    target_role: Literal["USER", "ASSISTANT"] | None = None
    reference_kind: Literal["LATEST_PRIOR", "EARLIER_ORDINAL"] | None = None


class ExpectedRequest(StrictModel):
    capability: Capability
    operation: Operation
    argument_constraints: ArgumentConstraints | None = None

    @model_validator(mode="after")
    def compatible_operation(self) -> "ExpectedRequest":
        if self.operation not in OPERATIONS[self.capability]:
            raise ValueError("operation is incompatible with capability")
        return self
