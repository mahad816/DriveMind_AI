"""Validated execution contracts; resolution and executor behavior come later."""

from types import MappingProxyType
from typing import Annotated, Literal, TypeAlias
from collections.abc import Mapping
from uuid import UUID
from pydantic import Field, model_validator
from .domain import RequestedIntent
from .references import (
    ContractModel,
    OutputKind,
    ResultReference,
    UnspecifiedSingleFileReference,
    HistoryReference,
    PriorTopicReference,
    CandidateId,
)
from .scope import (
    ExecutionScope,
    RetrievalScope,
    AllVisibleIndexedFiles,
    ExplicitFileTargetScope,
    NoFileScope,
    EligibleCollectionScope,
    ResolvedFileScope,
    DeferredFileResultScope,
    NoRetrievalScope,
)

# Public output contract: file content answers are TEXT, not invented FILE results.
OUTPUT_KINDS: Mapping[str, OutputKind] = MappingProxyType(
    {
        "LIST": "ORDERED_FILE_LIST",
        "COUNT": "TEXT_ANSWER",
        "LATEST": "FILE",
        "OLDEST": "FILE",
        "SUMMARIZE": "TEXT_ANSWER",
        "ANSWER_QUESTION": "TEXT_ANSWER",
        "SUMMARIZE_EACH": "TEXT_ANSWER",
        "ANSWER": "TEXT_ANSWER",
        "RECALL": "TEXT_ANSWER",
        "RESPOND": "TEXT_ANSWER",
    }
)


class CollectionArguments(ContractModel):
    kind: Literal["COLLECTION"] = "COLLECTION"


class ResolvedFileArguments(ContractModel):
    kind: Literal["RESOLVED_FILE"] = "RESOLVED_FILE"
    file_id: UUID
    canonical_name: str = Field(min_length=1, max_length=1024, pattern=r"\S")


class DeferredFileArguments(ContractModel):
    kind: Literal["DEFERRED_FILE"] = "DEFERRED_FILE"
    reference: ResultReference


class TextArguments(ContractModel):
    kind: Literal["TEXT_INPUT"] = "TEXT_INPUT"
    text: str = Field(min_length=1, max_length=8000, pattern=r"\S")


class TopicArguments(ContractModel):
    kind: Literal["TOPIC_INPUT"] = "TOPIC_INPUT"
    candidate_id: CandidateId
    current_query: str = Field(min_length=1, max_length=8000, pattern=r"\S")
    topic: str = Field(min_length=1, max_length=2000, pattern=r"\S")


class HistoryArguments(ContractModel):
    kind: Literal["HISTORY_INPUT"] = "HISTORY_INPUT"
    reference: HistoryReference
    text: str = Field(min_length=1, max_length=8000, pattern=r"\S")


ExecutionArguments: TypeAlias = Annotated[
    CollectionArguments
    | ResolvedFileArguments
    | DeferredFileArguments
    | TextArguments
    | TopicArguments
    | HistoryArguments,
    Field(discriminator="kind"),
]


class ExecutionStep(ContractModel):
    position: int = Field(ge=1, le=3)
    arguments: ExecutionArguments
    scope: ExecutionScope
    # Capability, operation and source/query provenance have one owner: plan.intent.


class ExecutionPlan(ContractModel):
    user_id: UUID
    intent: RequestedIntent
    steps: tuple[ExecutionStep, ...] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def validated_plan(self) -> "ExecutionPlan":
        if tuple(s.position for s in self.steps) != tuple(s.position for s in self.intent.steps):
            raise ValueError("execution must preserve every semantic step and its order")
        for s, intent in zip(self.steps, self.intent.steps, strict=True):
            if isinstance(intent.scope, AllVisibleIndexedFiles):
                if not isinstance(s.scope, EligibleCollectionScope):
                    raise ValueError("full collection scope must remain full eligible collection")
            elif isinstance(intent.scope, ExplicitFileTargetScope):
                if isinstance(intent.target, UnspecifiedSingleFileReference):
                    raise ValueError("unspecified single target is not executable")
                if isinstance(intent.target, ResultReference):
                    if (
                        not isinstance(s.arguments, DeferredFileArguments)
                        or s.arguments.reference != intent.target
                        or not isinstance(s.scope, DeferredFileResultScope)
                    ):
                        raise ValueError("result target must remain a deferred reference")
                    producer = self.intent.steps[intent.target.producer_step_position - 1]
                    if OUTPUT_KINDS[producer.operation] != intent.target.required_output_kind:
                        raise ValueError("producer output is incompatible with dependency")
                elif (
                    not isinstance(s.arguments, ResolvedFileArguments)
                    or not isinstance(s.scope, ResolvedFileScope)
                    or s.scope.file_ids != (s.arguments.file_id,)
                ):
                    raise ValueError("single-file scope must match resolved target exactly")
            elif isinstance(intent.scope, NoFileScope):
                if not isinstance(s.scope, NoRetrievalScope):
                    raise ValueError("non-file operation must not acquire collection scope")
            else:
                raise ValueError("semantic restriction has no supported executable representation")
            if intent.capability in {"FILE_INVENTORY", "COLLECTION_SUMMARY"}:
                valid = isinstance(s.arguments, CollectionArguments)
            elif intent.capability == "FILE_TARGET":
                valid = isinstance(s.arguments, (ResolvedFileArguments, DeferredFileArguments))
            elif intent.capability == "CONVERSATION_HISTORY":
                valid = (
                    isinstance(s.arguments, HistoryArguments)
                    and s.arguments.reference == intent.target
                )
            elif intent.capability == "GROUNDED_RAG" and isinstance(
                intent.target, PriorTopicReference
            ):
                valid = (
                    isinstance(s.arguments, TopicArguments)
                    and s.arguments.candidate_id == intent.target.candidate_id
                )
            else:
                valid = isinstance(s.arguments, TextArguments)
            if not valid:
                raise ValueError("execution arguments incompatible with semantic operation")
        return self


class RetrievalRequest(ContractModel):
    user_id: UUID
    query: str = Field(min_length=1, max_length=8000, pattern=r"\S")
    scope: RetrievalScope
    candidate_limit: int = Field(ge=1, le=100)

    @model_validator(mode="after")
    def nonempty_exact_scope(self) -> "RetrievalRequest":
        if isinstance(self.scope, ResolvedFileScope) and not self.scope.file_ids:
            raise ValueError("an exact retrieval request requires at least one file")
        return self
