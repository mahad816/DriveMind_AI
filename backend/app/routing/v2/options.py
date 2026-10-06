"""Capability-specific bounded atomic choices; no semantic likelihood ranking."""

from enum import StrEnum
from typing import Annotated, Literal, TypeAlias

from pydantic import Field, TypeAdapter, model_validator, ValidationError

from app.routing.v2 import domain as d
from app.routing.v2.preparation import PreparedEnvelope, PreparationFailure
from app.routing.v2.contracts import digest

MAX_OPTIONS = 220  # + two non-executable outcomes, strictly below TypeSafe's 255.
SpanId: TypeAlias = Annotated[str, Field(pattern=r"^S[0-9]{3}$")]
OptionId: TypeAlias = Annotated[str, Field(pattern=r"^R[0-9]{3}$")]


class InventoryOrdering(StrEnum):
    DEFAULT = "DEFAULT"
    NEWEST_FIRST = "NEWEST_FIRST"
    OLDEST_FIRST = "OLDEST_FIRST"
    NAME_ASC = "NAME_ASC"
    NAME_DESC = "NAME_DESC"


ORDERING = {
    InventoryOrdering.DEFAULT: "NAME_ASC",
    InventoryOrdering.NEWEST_FIRST: "MODIFIED_AT_DESC",
    InventoryOrdering.OLDEST_FIRST: "MODIFIED_AT_ASC",
    InventoryOrdering.NAME_ASC: "NAME_ASC",
    InventoryOrdering.NAME_DESC: "NAME_DESC",
}


class Option(d.DomainModel):
    option_id: OptionId
    source_span_id: SpanId


class InventoryListOption(Option):
    kind: Literal["inventory_list"] = "inventory_list"
    collection_binding: d.CandidateId
    ordering: InventoryOrdering


class InventoryCountOption(Option):
    kind: Literal["inventory_count"] = "inventory_count"
    collection_binding: d.CandidateId


class InventoryLatestOption(Option):
    kind: Literal["inventory_latest"] = "inventory_latest"
    collection_binding: d.CandidateId


class InventoryOldestOption(Option):
    kind: Literal["inventory_oldest"] = "inventory_oldest"
    collection_binding: d.CandidateId


class FileTargetSummarizeOption(Option):
    kind: Literal["file_summarize"] = "file_summarize"
    target_reference: d.FileReference


class FileTargetQuestionOption(Option):
    kind: Literal["file_question"] = "file_question"
    target_reference: d.FileReference
    question_span_id: SpanId


class CollectionSummaryOption(Option):
    kind: Literal["collection_summary"] = "collection_summary"
    collection_binding: d.CandidateId


class ConversationHistoryOption(Option):
    kind: Literal["history"] = "history"
    history_binding: d.CandidateId
    reference: d.MessageReference


class GroundedQueryOption(Option):
    kind: Literal["grounded_query"] = "grounded_query"
    query_span_id: SpanId


class GroundedTopicOption(Option):
    kind: Literal["grounded_topic"] = "grounded_topic"
    topic_reference: d.ContextTopicReference


class RuntimeDependencyOption(Option):
    kind: Literal["unsupported_result_dependency"] = "unsupported_result_dependency"
    reference: d.RuntimeResultReference


class ChitchatOption(Option):
    kind: Literal["chitchat"] = "chitchat"


SemanticRequestOption: TypeAlias = Annotated[
    InventoryListOption
    | InventoryCountOption
    | InventoryLatestOption
    | InventoryOldestOption
    | FileTargetSummarizeOption
    | FileTargetQuestionOption
    | CollectionSummaryOption
    | ConversationHistoryOption
    | GroundedQueryOption
    | GroundedTopicOption
    | ChitchatOption
    | RuntimeDependencyOption,
    Field(discriminator="kind"),
]
OPTION: TypeAdapter[SemanticRequestOption] = TypeAdapter(SemanticRequestOption)


class OptionRegistry(d.DomainModel):
    envelope_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    options: tuple[SemanticRequestOption, ...] = Field(min_length=1, max_length=MAX_OPTIONS)

    @model_validator(mode="after")
    def unique_options(self) -> "OptionRegistry":
        if len({o.option_id for o in self.options}) != len(self.options):
            raise ValueError("duplicate option IDs")
        if len(
            {digest(o.model_dump(mode="json", exclude={"option_id"})) for o in self.options}
        ) != len(self.options):
            raise ValueError("duplicate atomic option payloads")
        return self

    @property
    def identity_hash(self) -> str:
        return digest(self.model_dump(mode="json"))


def semantic_request(
    envelope: PreparedEnvelope, option: SemanticRequestOption
) -> d.SemanticRequest | d.UnsupportedRequest:
    spans = {s.span_id: s.span for s in envelope.spans}
    span = spans[option.source_span_id]
    if isinstance(option, RuntimeDependencyOption):
        return d.UnsupportedRequest(
            reason=d.UnsupportedReason.RESULT_DEPENDENCY_UNSUPPORTED, input_span=span
        )
    if isinstance(option, InventoryListOption):
        return d.FileInventoryRequest.model_validate(
            {"input_span": span, "operation": "LIST", "ordering": ORDERING[option.ordering]}
        )
    if isinstance(option, (InventoryCountOption, InventoryLatestOption, InventoryOldestOption)):
        operation = {
            "inventory_count": "COUNT",
            "inventory_latest": "LATEST",
            "inventory_oldest": "OLDEST",
        }[option.kind]
        return d.FileInventoryRequest.model_validate({"input_span": span, "operation": operation})
    if isinstance(option, CollectionSummaryOption):
        return d.CollectionSummaryRequest(input_span=span)
    if isinstance(option, FileTargetSummarizeOption):
        return d.FileTargetRequest(
            input_span=span, action=d.SummarizeFileRequest(target=option.target_reference)
        )
    if isinstance(option, FileTargetQuestionOption):
        return d.FileTargetRequest(
            input_span=span,
            action=d.FileQuestionRequest(
                target=option.target_reference, question_span=spans[option.question_span_id]
            ),
        )
    if isinstance(option, ConversationHistoryOption):
        return d.ConversationHistoryRequest(
            input_span=span, candidate_id=option.history_binding, reference=option.reference
        )
    if isinstance(option, GroundedQueryOption):
        return d.GroundedRagRequest(
            input_span=span, query=d.OriginalQuery(span=spans[option.query_span_id])
        )
    if isinstance(option, GroundedTopicOption):
        return d.GroundedRagRequest(input_span=span, query=option.topic_reference)
    return d.ChitchatRequest(input_span=span)


def generate_options(envelope: PreparedEnvelope) -> OptionRegistry | PreparationFailure:
    try:
        envelope = PreparedEnvelope.model_validate_json(envelope.model_dump_json())
    except ValidationError:
        return PreparationFailure(reason="INVALID_INPUT")
    collection = next(
        (c for c in envelope.input.candidates if isinstance(c, d.CollectionCandidate)), None
    )
    if collection is None:
        return PreparationFailure(reason="INVALID_INPUT")
    options: list[SemanticRequestOption] = []
    option_count = 0

    def add(kind: type[Option], span_id: str, **fields: object) -> None:
        nonlocal option_count
        option_count += 1
        if option_count > MAX_OPTIONS:
            return  # Count all bounded templates; no partial registry escapes.
        option = OPTION.validate_python(
            kind.model_validate(
                {"option_id": f"R{len(options) + 1:03}", "source_span_id": span_id, **fields}
            )
        )
        options.append(option)

    for unit in envelope.spans:
        span_id = unit.span_id
        for ordering in InventoryOrdering:
            add(
                InventoryListOption,
                span_id,
                collection_binding=collection.candidate_id,
                ordering=ordering,
            )
        for inventory in (InventoryCountOption, InventoryLatestOption, InventoryOldestOption):
            add(inventory, span_id, collection_binding=collection.candidate_id)
        add(CollectionSummaryOption, span_id, collection_binding=collection.candidate_id)
        add(ChitchatOption, span_id)
        add(GroundedQueryOption, span_id, query_span_id=span_id)
        for candidate in envelope.input.candidates:
            source = candidate.source
            if isinstance(source, d.SourceLocation) and not isinstance(
                candidate, d.UnspecifiedTargetCandidate
            ):
                if not (unit.span.start <= source.start and source.end <= unit.span.end):
                    continue
            ref: d.FileReference | None = None
            if isinstance(candidate, d.RuntimeResultCandidate):
                add(
                    RuntimeDependencyOption,
                    span_id,
                    reference=d.RuntimeResultReference(candidate_id=candidate.candidate_id),
                )
            elif isinstance(candidate, d.LiteralFileCandidate):
                ref = d.LiteralMention(candidate_id=candidate.candidate_id)
            elif isinstance(candidate, d.SelectorCandidate):
                ref = d.MetadataSelector(
                    candidate_id=candidate.candidate_id, selector=candidate.selector
                )
            elif isinstance(candidate, d.ContextFileCandidate):
                ref = d.ContextFileReference(
                    candidate_id=candidate.candidate_id, reference_kind=candidate.reference_kind
                )
            elif isinstance(candidate, d.UnspecifiedTargetCandidate):
                ref = d.UnspecifiedFile(candidate_id=candidate.candidate_id)
            elif isinstance(candidate, d.PriorMessageCandidate):
                add(
                    ConversationHistoryOption,
                    span_id,
                    history_binding=candidate.candidate_id,
                    reference=candidate.reference,
                )
            elif isinstance(candidate, d.ContextTopicCandidate):
                add(
                    GroundedTopicOption,
                    span_id,
                    topic_reference=d.ContextTopicReference(candidate_id=candidate.candidate_id),
                )
            if ref is not None:
                add(FileTargetSummarizeOption, span_id, target_reference=ref)
                add(
                    FileTargetQuestionOption,
                    span_id,
                    target_reference=ref,
                    question_span_id=span_id,
                )
    if option_count > MAX_OPTIONS:
        return PreparationFailure(
            reason="OPTION_LIMIT_EXCEEDED",
            span_count=len(envelope.spans),
            candidate_count=len(envelope.input.candidates),
            binding_count=len(envelope.bindings),
            option_count=option_count,
        )
    registry = OptionRegistry(envelope_hash=envelope.identity_hash, options=tuple(options))
    # Validate all source/reference combinations, even unselected options.
    for option in registry.options:
        request = semantic_request(envelope, option)
        d.BoundInterpretation(
            input=envelope.input,
            interpretation=request
            if isinstance(request, d.UnsupportedRequest)
            else d.RequestedOperations(requests=(request,)),
        )
    return registry


def registry_matches(envelope: PreparedEnvelope, registry: OptionRegistry) -> bool:
    try:
        registry = OptionRegistry.model_validate_json(registry.model_dump_json())
        generated = generate_options(envelope)
        return isinstance(generated, OptionRegistry) and generated == registry
    except (ValidationError, KeyError, StopIteration):
        return False
