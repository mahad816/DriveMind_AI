"""V2 domain schemas only: no providers, resolution, dispatch, or persistence.

Candidate IDs are request-local handles, not evidence of provenance on their
own. BoundInterpretation validates them against Python's prepared registry.
Spans use half-open Unicode character offsets in the current question.
"""

from enum import StrEnum
from typing import Annotated, Literal, TypeAlias
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


CandidateId: TypeAlias = Annotated[str, Field(pattern=r"^c[0-9]{1,3}$")]


class InputSpan(DomainModel):
    start: StrictInt = Field(ge=0, lt=8000)
    end: StrictInt = Field(gt=0, le=8000)

    @model_validator(mode="after")
    def nonempty(self) -> "InputSpan":
        if self.end <= self.start:
            raise ValueError("span must be nonempty and forward")
        return self


class ContextHandle(DomainModel):
    kind: Literal["context"] = "context"
    handle: Literal["ACTIVE_FILES", "ACTIVE_TOPIC", "RECENT_MESSAGES"]


class SourceLocation(InputSpan):
    kind: Literal["input"] = "input"


CandidateSource: TypeAlias = Annotated[SourceLocation | ContextHandle, Field(discriminator="kind")]


class ReferenceSelector(StrEnum):
    LATEST = "LATEST"
    OLDEST = "OLDEST"


class FileContextKind(StrEnum):
    IT = "IT"
    THAT = "THAT"
    THIS_FILE = "THIS_FILE"
    PREVIOUS_DOCUMENT = "PREVIOUS_DOCUMENT"


class LiteralFileCandidate(DomainModel):
    kind: Literal["literal_file"] = "literal_file"
    candidate_id: CandidateId
    source: SourceLocation


class SelectorCandidate(DomainModel):
    kind: Literal["metadata_selector"] = "metadata_selector"
    candidate_id: CandidateId
    source: SourceLocation
    selector: ReferenceSelector


class ContextFileCandidate(DomainModel):
    kind: Literal["context_file"] = "context_file"
    candidate_id: CandidateId
    source: CandidateSource
    reference_kind: FileContextKind

    @model_validator(mode="after")
    def correct_handle(self) -> "ContextFileCandidate":
        if isinstance(self.source, ContextHandle) and self.source.handle != "ACTIVE_FILES":
            raise ValueError("file context requires ACTIVE_FILES")
        return self


class ContextTopicCandidate(DomainModel):
    kind: Literal["context_topic"] = "context_topic"
    candidate_id: CandidateId
    source: CandidateSource

    @model_validator(mode="after")
    def correct_handle(self) -> "ContextTopicCandidate":
        if isinstance(self.source, ContextHandle) and self.source.handle != "ACTIVE_TOPIC":
            raise ValueError("topic context requires ACTIVE_TOPIC")
        return self


class MessageReference(DomainModel):
    role: Literal["user", "assistant"]
    relative_position: StrictInt = Field(default=1, ge=1, le=6)


class PriorMessageCandidate(DomainModel):
    kind: Literal["prior_message"] = "prior_message"
    candidate_id: CandidateId
    source: CandidateSource
    reference: MessageReference

    @model_validator(mode="after")
    def correct_handle(self) -> "PriorMessageCandidate":
        if isinstance(self.source, ContextHandle) and self.source.handle != "RECENT_MESSAGES":
            raise ValueError("message context requires RECENT_MESSAGES")
        return self


class CollectionCandidate(DomainModel):
    kind: Literal["indexed_collection"] = "indexed_collection"
    candidate_id: CandidateId
    # Absent source means the supported default, not an inferred external scope.
    source: SourceLocation | None = None


class UnspecifiedTargetCandidate(DomainModel):
    kind: Literal["unspecified_target"] = "unspecified_target"
    candidate_id: CandidateId
    source: SourceLocation


class RuntimeResultCandidate(DomainModel):
    """Application-owned explicit current-result occurrence, never prior context."""

    kind: Literal["runtime_result"] = "runtime_result"
    candidate_id: CandidateId
    source: SourceLocation


class OriginalQueryCandidate(DomainModel):
    kind: Literal["original_query"] = "original_query"
    candidate_id: CandidateId
    source: SourceLocation


BindingCandidate: TypeAlias = Annotated[
    LiteralFileCandidate
    | SelectorCandidate
    | ContextFileCandidate
    | ContextTopicCandidate
    | PriorMessageCandidate
    | CollectionCandidate
    | UnspecifiedTargetCandidate
    | OriginalQueryCandidate
    | RuntimeResultCandidate,
    Field(discriminator="kind"),
]


class LiteralMention(DomainModel):
    kind: Literal["literal"] = "literal"
    candidate_id: CandidateId


class MetadataSelector(DomainModel):
    kind: Literal["selector"] = "selector"
    candidate_id: CandidateId
    selector: ReferenceSelector


class ContextFileReference(DomainModel):
    kind: Literal["context_file"] = "context_file"
    candidate_id: CandidateId
    reference_kind: FileContextKind


class RuntimeResultReference(DomainModel):
    kind: Literal["runtime_result"] = "runtime_result"
    candidate_id: CandidateId


class UnspecifiedFile(DomainModel):
    kind: Literal["unspecified"] = "unspecified"
    candidate_id: CandidateId


FileReference: TypeAlias = Annotated[
    LiteralMention
    | MetadataSelector
    | ContextFileReference
    | UnspecifiedFile
    | RuntimeResultReference,
    Field(discriminator="kind"),
]


class ContextTopicReference(DomainModel):
    kind: Literal["context_topic"] = "context_topic"
    candidate_id: CandidateId


class IndexedCollection(DomainModel):
    kind: Literal["indexed_collection"] = "indexed_collection"


class FileInventoryRequest(DomainModel):
    capability: Literal["FILE_INVENTORY"] = "FILE_INVENTORY"
    operation: Literal["LIST", "COUNT", "LATEST", "OLDEST"]
    input_span: InputSpan
    scope: IndexedCollection = Field(default_factory=IndexedCollection)
    ordering: Literal["NAME_ASC", "NAME_DESC", "MODIFIED_AT_ASC", "MODIFIED_AT_DESC"] | None = None

    @model_validator(mode="after")
    def compatible_ordering(self) -> "FileInventoryRequest":
        if self.ordering is not None and self.operation != "LIST":
            raise ValueError("explicit ordering is supported only for LIST")
        return self


class SummarizeFileRequest(DomainModel):
    operation: Literal["SUMMARIZE"] = "SUMMARIZE"
    target: FileReference


class FileQuestionRequest(DomainModel):
    operation: Literal["ANSWER_QUESTION"] = "ANSWER_QUESTION"
    target: FileReference
    question_span: InputSpan


FileAction: TypeAlias = Annotated[
    SummarizeFileRequest | FileQuestionRequest, Field(discriminator="operation")
]


class FileTargetRequest(DomainModel):
    capability: Literal["FILE_TARGET"] = "FILE_TARGET"
    input_span: InputSpan
    action: FileAction

    @property
    def operation(self) -> str:
        return self.action.operation


class CollectionSummaryRequest(DomainModel):
    capability: Literal["COLLECTION_SUMMARY"] = "COLLECTION_SUMMARY"
    operation: Literal["SUMMARIZE_EACH"] = "SUMMARIZE_EACH"
    input_span: InputSpan
    scope: IndexedCollection = Field(default_factory=IndexedCollection)


class ConversationHistoryRequest(DomainModel):
    capability: Literal["CONVERSATION_HISTORY"] = "CONVERSATION_HISTORY"
    operation: Literal["RECALL"] = "RECALL"
    input_span: InputSpan
    candidate_id: CandidateId
    reference: MessageReference


class OriginalQuery(DomainModel):
    kind: Literal["original_query"] = "original_query"
    span: InputSpan


class GroundedRagRequest(DomainModel):
    capability: Literal["GROUNDED_RAG"] = "GROUNDED_RAG"
    operation: Literal["ANSWER"] = "ANSWER"
    input_span: InputSpan
    query: Annotated[OriginalQuery | ContextTopicReference, Field(discriminator="kind")]


class ChitchatRequest(DomainModel):
    capability: Literal["CHITCHAT"] = "CHITCHAT"
    operation: Literal["RESPOND"] = "RESPOND"
    input_span: InputSpan


SemanticRequest: TypeAlias = Annotated[
    FileInventoryRequest
    | FileTargetRequest
    | CollectionSummaryRequest
    | ConversationHistoryRequest
    | GroundedRagRequest
    | ChitchatRequest,
    Field(discriminator="capability"),
]


class RequestedOperations(DomainModel):
    kind: Literal["requested_operations"] = "requested_operations"
    requests: tuple[SemanticRequest, ...] = Field(min_length=1, max_length=3)

    @property
    def cardinality(self) -> int:
        return len(self.requests)


class SemanticAmbiguity(DomainModel):
    kind: Literal["semantic_ambiguity"] = "semantic_ambiguity"
    alternatives: tuple[RequestedOperations, ...] = Field(min_length=2, max_length=3)
    input_span: InputSpan


class UnsupportedReason(StrEnum):
    OPERATION = "OPERATION"
    SCOPE = "SCOPE"
    DEPENDENCY = "DEPENDENCY"
    RESULT_DEPENDENCY_UNSUPPORTED = "RESULT_DEPENDENCY_UNSUPPORTED"
    REQUEST_LIMIT = "REQUEST_LIMIT"


class UnsupportedRequest(DomainModel):
    kind: Literal["unsupported"] = "unsupported"
    reason: UnsupportedReason
    input_span: InputSpan


SemanticInterpretation: TypeAlias = Annotated[
    RequestedOperations | SemanticAmbiguity | UnsupportedRequest, Field(discriminator="kind")
]


class PreparedInput(DomainModel):
    question: str = Field(min_length=1, max_length=8000)
    candidates: tuple[BindingCandidate, ...] = Field(default=(), max_length=32)

    def validate_span(self, span: InputSpan) -> None:
        if span.end > len(self.question) or not self.question[span.start : span.end].strip():
            raise ValueError("span must identify nonblank text within the question")

    @model_validator(mode="after")
    def valid_registry(self) -> "PreparedInput":
        if not self.question.strip():
            raise ValueError("question must not be blank")
        ids = [candidate.candidate_id for candidate in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("candidate IDs must be unique")
        for candidate in self.candidates:
            if isinstance(candidate.source, SourceLocation):
                self.validate_span(candidate.source)
        return self


class BoundInterpretation(DomainModel):
    """Structural binding check only; does not establish existence or readiness."""

    input: PreparedInput
    interpretation: SemanticInterpretation

    @model_validator(mode="after")
    def valid_bindings(self) -> "BoundInterpretation":
        registry = {c.candidate_id: c for c in self.input.candidates}

        def candidate(candidate_id: str) -> BindingCandidate:
            if candidate_id not in registry:
                raise ValueError("reference is absent from prepared candidate registry")
            return registry[candidate_id]

        def bundle(value: RequestedOperations) -> None:
            for request in value.requests:
                self.input.validate_span(request.input_span)
                if isinstance(request, FileTargetRequest):
                    ref = request.action.target
                    binding = candidate(ref.candidate_id)
                    if isinstance(ref, LiteralMention):
                        valid = isinstance(binding, LiteralFileCandidate)
                    elif isinstance(ref, MetadataSelector):
                        valid = (
                            isinstance(binding, SelectorCandidate)
                            and ref.selector == binding.selector
                        )
                    elif isinstance(ref, ContextFileReference):
                        valid = (
                            isinstance(binding, ContextFileCandidate)
                            and ref.reference_kind == binding.reference_kind
                        )
                    elif isinstance(ref, RuntimeResultReference):
                        valid = isinstance(binding, RuntimeResultCandidate)
                    else:
                        valid = isinstance(binding, UnspecifiedTargetCandidate)
                    if not valid:
                        raise ValueError("file reference and candidate disagree")
                    if isinstance(request.action, FileQuestionRequest):
                        self.input.validate_span(request.action.question_span)
                elif isinstance(request, ConversationHistoryRequest):
                    binding = candidate(request.candidate_id)
                    if (
                        not isinstance(binding, PriorMessageCandidate)
                        or binding.reference != request.reference
                    ):
                        raise ValueError("message reference and candidate disagree")
                elif isinstance(request, GroundedRagRequest):
                    if isinstance(request.query, OriginalQuery):
                        self.input.validate_span(request.query.span)
                    elif not isinstance(
                        candidate(request.query.candidate_id), ContextTopicCandidate
                    ):
                        raise ValueError("topic reference and candidate disagree")

        value = self.interpretation
        if isinstance(value, RequestedOperations):
            bundle(value)
        else:
            self.input.validate_span(value.input_span)
            if isinstance(value, SemanticAmbiguity):
                for alternative in value.alternatives:
                    bundle(alternative)
        return self


class ClarificationReason(StrEnum):
    UNRESOLVED_REFERENCE = "UNRESOLVED_REFERENCE"
    AMBIGUOUS_REFERENCE = "AMBIGUOUS_REFERENCE"
    MISSING_REQUIRED_ARGUMENT = "MISSING_REQUIRED_ARGUMENT"
    AMBIGUOUS_SEMANTIC_INTERPRETATION = "AMBIGUOUS_SEMANTIC_INTERPRETATION"


class Ready(DomainModel):
    """Resolver-issued status marker, not an execution payload or authorization."""

    status: Literal["READY"] = "READY"


class NeedsClarification(DomainModel):
    status: Literal["NEEDS_CLARIFICATION"] = "NEEDS_CLARIFICATION"
    reason: ClarificationReason


class Unsupported(DomainModel):
    status: Literal["UNSUPPORTED"] = "UNSUPPORTED"
    reason: UnsupportedReason


class Failed(DomainModel):
    status: Literal["FAILED"] = "FAILED"
    reason: Literal["RESOLUTION_UNAVAILABLE", "INTERNAL_ERROR"]


Readiness: TypeAlias = Annotated[
    Ready | NeedsClarification | Unsupported | Failed, Field(discriminator="status")
]


class RecentMessage(DomainModel):
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=2000)


class ActiveTopic(DomainModel):
    original_question: str = Field(min_length=1, max_length=2000)
    answer_summary: str = Field(min_length=1, max_length=2000)


class ConversationState(DomainModel):
    last_substantive_request: BoundInterpretation | None = None
    last_successful_request_bundle: BoundInterpretation | None = None
    active_file_ids: tuple[UUID, ...] = Field(default=(), max_length=3)
    active_topic: ActiveTopic | None = None
    recent_messages: tuple[RecentMessage, ...] = Field(default=(), max_length=6)

    @model_validator(mode="after")
    def bounded_state(self) -> "ConversationState":
        if self.last_successful_request_bundle is not None and not isinstance(
            self.last_successful_request_bundle.interpretation, RequestedOperations
        ):
            raise ValueError("successful request state requires requested operations")
        if self.active_topic is not None and (
            not self.active_topic.original_question.strip()
            or not self.active_topic.answer_summary.strip()
        ):
            raise ValueError("active topic must not be blank")
        if len(self.active_file_ids) != len(set(self.active_file_ids)):
            raise ValueError("active file IDs must be unique")
        if sum(len(message.text) for message in self.recent_messages) > 6000:
            raise ValueError("recent conversation exceeds 6000 characters")
        if any(not message.text.strip() for message in self.recent_messages):
            raise ValueError("messages must not be blank")
        return self
