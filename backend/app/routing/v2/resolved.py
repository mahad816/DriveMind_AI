"""Concrete resolution arguments and readiness; no executor calls."""

from datetime import datetime
from typing import Annotated, Literal, TypeAlias
from uuid import UUID

from pydantic import Field, StrictInt, model_validator

from app.routing.v2 import domain as d


class IndexedFile(d.DomainModel):
    """Lookup provider attests that this record is visible and INDEXED for user_id."""

    file_id: UUID
    user_id: UUID
    name: str = Field(min_length=1, max_length=1024)
    modified_at: datetime | None

    @model_validator(mode="after")
    def aware_timestamp(self) -> "IndexedFile":
        if not self.name.strip():
            raise ValueError("canonical name must not be blank")
        if self.modified_at is not None and self.modified_at.utcoffset() is None:
            raise ValueError("modified_at must be timezone-aware")
        return self


class ResolvedCollection(d.DomainModel):
    kind: Literal["indexed_collection"] = "indexed_collection"
    user_id: UUID
    files: tuple[IndexedFile, ...]

    @model_validator(mode="after")
    def coherent(self) -> "ResolvedCollection":
        if any(f.user_id != self.user_id for f in self.files):
            raise ValueError("collection contains another user's file")
        if len({f.file_id for f in self.files}) != len(self.files):
            raise ValueError("duplicate file IDs in metadata snapshot")
        return self


class ResolvedInventoryRequest(d.DomainModel):
    capability: Literal["FILE_INVENTORY"] = "FILE_INVENTORY"
    operation: Literal["LIST", "COUNT", "LATEST", "OLDEST"]
    collection: ResolvedCollection
    selected_file: IndexedFile | None = None
    ordering: Literal["NAME_ASC", "NAME_DESC", "MODIFIED_AT_ASC", "MODIFIED_AT_DESC"] | None = None

    @model_validator(mode="after")
    def compatible(self) -> "ResolvedInventoryRequest":
        if self.ordering is not None and self.operation != "LIST":
            raise ValueError("ordering requires LIST")
        selector = self.operation in ("LATEST", "OLDEST")
        if selector != (self.selected_file is not None):
            raise ValueError("recency inventory requires exactly one selected file")
        if self.selected_file is not None and self.selected_file not in self.collection.files:
            raise ValueError("selected file is not in collection snapshot")
        return self


class ResolvedFileSummary(d.DomainModel):
    operation: Literal["SUMMARIZE"] = "SUMMARIZE"
    file: IndexedFile


class ResolvedFileQuestion(d.DomainModel):
    operation: Literal["ANSWER_QUESTION"] = "ANSWER_QUESTION"
    file: IndexedFile
    question: str = Field(min_length=1, max_length=8000, pattern=r"\S")


class ResolvedFileTargetRequest(d.DomainModel):
    capability: Literal["FILE_TARGET"] = "FILE_TARGET"
    action: Annotated[ResolvedFileSummary | ResolvedFileQuestion, Field(discriminator="operation")]

    @property
    def operation(self) -> str:
        return self.action.operation


class ResolvedCollectionSummaryRequest(d.DomainModel):
    capability: Literal["COLLECTION_SUMMARY"] = "COLLECTION_SUMMARY"
    operation: Literal["SUMMARIZE_EACH"] = "SUMMARIZE_EACH"
    collection: ResolvedCollection


class ResolvedHistoryRequest(d.DomainModel):
    capability: Literal["CONVERSATION_HISTORY"] = "CONVERSATION_HISTORY"
    operation: Literal["RECALL"] = "RECALL"
    message: d.RecentMessage
    reference: d.MessageReference


class ResolvedOriginalQuery(d.DomainModel):
    kind: Literal["original_query"] = "original_query"
    text: str = Field(min_length=1, max_length=8000, pattern=r"\S")


class ResolvedTopicQuery(d.DomainModel):
    kind: Literal["topic_continuation"] = "topic_continuation"
    continuation: str = Field(min_length=1, max_length=8000, pattern=r"\S")
    topic: d.ActiveTopic


class ResolvedGroundedRequest(d.DomainModel):
    capability: Literal["GROUNDED_RAG"] = "GROUNDED_RAG"
    operation: Literal["ANSWER"] = "ANSWER"
    query: Annotated[ResolvedOriginalQuery | ResolvedTopicQuery, Field(discriminator="kind")]


class ResolvedChitchatRequest(d.DomainModel):
    capability: Literal["CHITCHAT"] = "CHITCHAT"
    operation: Literal["RESPOND"] = "RESPOND"
    text: str = Field(min_length=1, max_length=8000, pattern=r"\S")


ResolvedRequest: TypeAlias = Annotated[
    ResolvedInventoryRequest
    | ResolvedFileTargetRequest
    | ResolvedCollectionSummaryRequest
    | ResolvedHistoryRequest
    | ResolvedGroundedRequest
    | ResolvedChitchatRequest,
    Field(discriminator="capability"),
]


class ReadyRequest(d.DomainModel):
    status: Literal["READY"] = "READY"
    request_id: StrictInt = Field(ge=1, le=3)
    resolved: ResolvedRequest


class FileOption(d.DomainModel):
    file_id: UUID
    name: str = Field(min_length=1, max_length=1024)


class ClarificationRequirement(d.DomainModel):
    status: Literal["NEEDS_CLARIFICATION"] = "NEEDS_CLARIFICATION"
    request_id: StrictInt = Field(ge=1, le=3)
    reason: d.ClarificationReason
    detail: Literal[
        "FILE_NOT_FOUND",
        "DUPLICATE_FILENAME",
        "EMPTY_COLLECTION",
        "UNKNOWN_RECENCY",
        "RECENCY_TIE",
        "NO_ACTIVE_FILE",
        "MULTIPLE_ACTIVE_FILES",
        "ACTIVE_FILE_UNAVAILABLE",
        "NO_ACTIVE_TOPIC",
        "MULTIPLE_ACTIVE_TOPICS",
        "HISTORY_UNAVAILABLE",
        "TARGET_REQUIRED",
        "COMPETING_INTERPRETATIONS",
    ]
    options: tuple[FileOption, ...] = Field(default=(), max_length=3)
    match_count: StrictInt = Field(default=0, ge=0)


class UnsupportedResolution(d.DomainModel):
    status: Literal["UNSUPPORTED"] = "UNSUPPORTED"
    request_id: StrictInt = Field(ge=1, le=3)
    reason: d.UnsupportedReason


class FailedRequest(d.DomainModel):
    status: Literal["FAILED"] = "FAILED"
    request_id: StrictInt = Field(ge=1, le=3)
    reason: Literal["METADATA_UNAVAILABLE", "INVALID_METADATA"]


RequestResolution: TypeAlias = Annotated[
    ReadyRequest | ClarificationRequirement | UnsupportedResolution | FailedRequest,
    Field(discriminator="status"),
]


class ResolutionFailure(d.DomainModel):
    status: Literal["FAILED"] = "FAILED"
    reason: Literal[
        "INVALID_INPUT", "PROVENANCE_MISMATCH", "METADATA_UNAVAILABLE", "INVALID_METADATA"
    ]


class ReadyBundle(d.DomainModel):
    source: d.BoundInterpretation
    requests: tuple[ResolvedRequest, ...] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def corresponding(self) -> "ReadyBundle":
        semantics = self.source.interpretation
        if not isinstance(semantics, d.RequestedOperations) or len(semantics.requests) != len(
            self.requests
        ):
            raise ValueError("ready bundle must correspond to requested operations")
        for semantic, resolved in zip(semantics.requests, self.requests, strict=True):
            if (semantic.capability, semantic.operation) != (
                resolved.capability,
                resolved.operation,
            ):
                raise ValueError("resolved capability/operation contradicts source")
        return self


class ResolutionReport(d.DomainModel):
    source: d.BoundInterpretation
    outcomes: tuple[RequestResolution, ...] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def ordered(self) -> "ResolutionReport":
        expected = self.source.interpretation
        size = expected.cardinality if isinstance(expected, d.RequestedOperations) else 1
        if len(self.outcomes) != size or tuple(o.request_id for o in self.outcomes) != tuple(
            range(1, size + 1)
        ):
            raise ValueError("outcomes must match source order and cardinality")
        if isinstance(expected, d.RequestedOperations):
            for semantic, outcome in zip(expected.requests, self.outcomes, strict=True):
                if isinstance(outcome, ReadyRequest) and (
                    semantic.capability,
                    semantic.operation,
                ) != (outcome.resolved.capability, outcome.resolved.operation):
                    raise ValueError("ready request contradicts corresponding semantic request")
        if all(isinstance(o, ReadyRequest) for o in self.outcomes):
            ReadyBundle(
                source=self.source,
                requests=tuple(o.resolved for o in self.outcomes if isinstance(o, ReadyRequest)),
            )
        elif not isinstance(expected, d.RequestedOperations) and any(
            isinstance(o, ReadyRequest) for o in self.outcomes
        ):
            raise ValueError("non-executable interpretation cannot be ready")
        return self

    @property
    def status(self) -> str:
        if any(isinstance(o, FailedRequest) for o in self.outcomes):
            return "FAILED"
        if any(isinstance(o, UnsupportedResolution) for o in self.outcomes):
            return "UNSUPPORTED"
        if any(isinstance(o, ClarificationRequirement) for o in self.outcomes):
            return "NEEDS_CLARIFICATION"
        return "READY"

    @property
    def ready_bundle(self) -> ReadyBundle | None:
        if self.status != "READY":
            return None
        return ReadyBundle(
            source=self.source,
            requests=tuple(o.resolved for o in self.outcomes if isinstance(o, ReadyRequest)),
        )
