"""Isolated semantic coverage gate. No routing, resolution, repair or execution."""

import hashlib
from enum import StrEnum
from typing import Annotated, Literal, TypeAlias

from pydantic import Field, StrictInt, model_validator

from app.routing.v2 import domain as d
from app.routing.v2.contracts import digest
from app.routing.v2.state import RoutingConversationState

INPUT_VERSION = "coverage-input-1.0"
Hash: TypeAlias = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class CoverageVerdict(StrEnum):
    PRESERVED = "PRESERVED"
    MISMATCH = "MISMATCH"
    UNCERTAIN = "UNCERTAIN"


class CoverageContext(d.DomainModel):
    snapshot_identity: Hash
    prior_file_count: StrictInt = Field(default=0, ge=0, le=3)
    prior_topic_count: StrictInt = Field(default=0, ge=0, le=3)
    user_history_positions: tuple[StrictInt, ...] = Field(default=(), max_length=6)
    assistant_history_positions: tuple[StrictInt, ...] = Field(default=(), max_length=6)

    @model_validator(mode="after")
    def positions(self) -> "CoverageContext":
        for positions in (self.user_history_positions, self.assistant_history_positions):
            if positions != tuple(range(1, len(positions) + 1)):
                raise ValueError("history positions must be bounded contiguous relative positions")
        return self

    def provider_data(self) -> dict[str, object]:
        return self.model_dump(exclude={"snapshot_identity"})


def context_from_state(state: d.ConversationState) -> CoverageContext:
    state = type(state).model_validate_json(state.model_dump_json())
    topics = (
        len(state.active_topics)
        if isinstance(state, RoutingConversationState)
        else int(state.active_topic is not None)
    )
    return CoverageContext(
        snapshot_identity=digest(state.model_dump(mode="json")),
        prior_file_count=len(state.active_file_ids),
        prior_topic_count=topics,
        user_history_positions=tuple(
            range(1, sum(m.role == "user" for m in state.recent_messages) + 1)
        ),
        assistant_history_positions=tuple(
            range(1, sum(m.role == "assistant" for m in state.recent_messages) + 1)
        ),
    )


class LiteralReference(d.DomainModel):
    kind: Literal["LITERAL_FILE"] = "LITERAL_FILE"
    current_input_span: d.InputSpan
    current_input_filename: str = Field(min_length=1, max_length=8000)


class SelectorReference(d.DomainModel):
    kind: Literal["INDEPENDENT_METADATA_SELECTION"] = "INDEPENDENT_METADATA_SELECTION"
    selector: d.ReferenceSelector


class FileContextReference(d.DomainModel):
    kind: Literal["PRIOR_CONVERSATION_FILE_REFERENCE"] = "PRIOR_CONVERSATION_FILE_REFERENCE"
    reference_kind: d.FileContextKind


class TopicContextReference(d.DomainModel):
    kind: Literal["PRIOR_CONVERSATION_TOPIC_REFERENCE"] = "PRIOR_CONVERSATION_TOPIC_REFERENCE"


class RuntimeReference(d.DomainModel):
    kind: Literal["CURRENT_BUNDLE_RESULT_REFERENCE"] = "CURRENT_BUNDLE_RESULT_REFERENCE"


class HistoryReference(d.DomainModel):
    kind: Literal["HISTORY_REFERENCE"] = "HISTORY_REFERENCE"
    role: Literal["user", "assistant"]
    relative_position: StrictInt = Field(ge=1, le=6)


class SimpleReference(d.DomainModel):
    kind: Literal["DEFAULT_COLLECTION", "ORIGINAL_QUERY", "SOCIAL_INPUT", "UNSPECIFIED_FILE"]


CoverageReference: TypeAlias = Annotated[
    LiteralReference
    | SelectorReference
    | FileContextReference
    | TopicContextReference
    | RuntimeReference
    | HistoryReference
    | SimpleReference,
    Field(discriminator="kind"),
]


class RequestSummary(d.DomainModel):
    position: StrictInt = Field(ge=1, le=3)
    capability: Literal[
        "FILE_INVENTORY",
        "FILE_TARGET",
        "COLLECTION_SUMMARY",
        "GROUNDED_RAG",
        "CONVERSATION_HISTORY",
        "CHITCHAT",
    ]
    operation: str
    reference: CoverageReference
    scope: Literal[
        "ALL_VISIBLE_INDEXED_FILES",
        "ONE_REFERENCED_FILE",
        "INDEXED_DOCUMENT_CONTENTS",
        "BOUNDED_CONVERSATION_HISTORY",
        "SOCIAL_ONLY",
    ]
    filter: Literal["NONE"] = "NONE"
    ordering: Literal["NAME_ASC", "NAME_DESC", "MODIFIED_AT_ASC", "MODIFIED_AT_DESC"] | None = None
    source_span: d.InputSpan
    source_text_provenance_only: str = Field(min_length=1, max_length=8000)
    query_span: d.InputSpan | None = None
    query_text_provenance_only: str | None = Field(default=None, min_length=1, max_length=8000)

    @model_validator(mode="after")
    def compatible(self) -> "RequestSummary":
        contracts = {
            "FILE_INVENTORY": (
                {"LIST", "COUNT", "LATEST", "OLDEST"},
                {"DEFAULT_COLLECTION"},
                "ALL_VISIBLE_INDEXED_FILES",
            ),
            "COLLECTION_SUMMARY": (
                {"SUMMARIZE_EACH"},
                {"DEFAULT_COLLECTION"},
                "ALL_VISIBLE_INDEXED_FILES",
            ),
            "FILE_TARGET": (
                {"SUMMARIZE", "ANSWER_QUESTION"},
                {
                    "LITERAL_FILE",
                    "INDEPENDENT_METADATA_SELECTION",
                    "PRIOR_CONVERSATION_FILE_REFERENCE",
                    "CURRENT_BUNDLE_RESULT_REFERENCE",
                    "UNSPECIFIED_FILE",
                },
                "ONE_REFERENCED_FILE",
            ),
            "GROUNDED_RAG": (
                {"ANSWER"},
                {"ORIGINAL_QUERY", "PRIOR_CONVERSATION_TOPIC_REFERENCE"},
                "INDEXED_DOCUMENT_CONTENTS",
            ),
            "CONVERSATION_HISTORY": (
                {"RECALL"},
                {"HISTORY_REFERENCE"},
                "BOUNDED_CONVERSATION_HISTORY",
            ),
            "CHITCHAT": ({"RESPOND"}, {"SOCIAL_INPUT"}, "SOCIAL_ONLY"),
        }
        operations, references, scope = contracts[self.capability]
        if (
            self.operation not in operations
            or self.reference.kind not in references
            or self.scope != scope
        ):
            raise ValueError("incompatible summary operation/reference/scope")
        if self.ordering is not None and (self.capability, self.operation) != (
            "FILE_INVENTORY",
            "LIST",
        ):
            raise ValueError("ordering requires inventory LIST")
        query_required = (
            self.operation == "ANSWER_QUESTION" or self.reference.kind == "ORIGINAL_QUERY"
        )
        if query_required != (
            self.query_span is not None and self.query_text_provenance_only is not None
        ) or ((self.query_span is None) != (self.query_text_provenance_only is None)):
            raise ValueError("query source mismatch")
        return self


class SpecialSelection(d.DomainModel):
    position: StrictInt = Field(ge=1, le=3)
    special: Literal["UNSUPPORTED_OPERATION", "SEMANTICALLY_AMBIGUOUS"]


class InterpretationSummary(d.DomainModel):
    proposed_cardinality: Literal["ONE", "TWO", "THREE", "OVER_LIMIT"]
    disposition: Literal["PROPOSED_OPERATIONS", "NON_EXECUTABLE"]
    requests: tuple[RequestSummary, ...] = Field(default=(), max_length=3)
    unsupported_reason: d.UnsupportedReason | None = None
    special_selections: tuple[SpecialSelection, ...] = Field(default=(), max_length=3)

    @model_validator(mode="after")
    def coherent(self) -> "InterpretationSummary":
        positions = [q.position for q in self.requests] + [
            s.position for s in self.special_selections
        ]
        if len(positions) != len(set(positions)) or [q.position for q in self.requests] != sorted(
            q.position for q in self.requests
        ):
            raise ValueError("duplicate or unordered positions")
        n = {"ONE": 1, "TWO": 2, "THREE": 3}.get(self.proposed_cardinality)
        if self.disposition == "PROPOSED_OPERATIONS":
            if (
                self.unsupported_reason
                or self.special_selections
                or positions != list(range(1, (n or 0) + 1))
            ):
                raise ValueError("executable summary cardinality/disposition mismatch")
            if any(isinstance(q.reference, RuntimeReference) for q in self.requests):
                raise ValueError("runtime references cannot be proposed executable")
        elif self.unsupported_reason is None:
            raise ValueError("non-executable summary must retain reason")
        if n is not None and any(p > n for p in positions):
            raise ValueError("position exceeds selected cardinality")
        return self


class CoverageInput(d.DomainModel):
    serialization_version: Literal["coverage-input-1.0"] = "coverage-input-1.0"
    original_question: str = Field(min_length=1, max_length=8000)
    interpretation: InterpretationSummary
    context: CoverageContext
    routing_contract_identity: Hash
    interpretation_identity: Hash
    context_identity: Hash
    contract_identity: Hash
    input_identity: Hash

    @model_validator(mode="after")
    def coherent(self) -> "CoverageInput":
        if not self.original_question.strip():
            raise ValueError("blank question")
        for request in self.interpretation.requests:
            for span, text in [
                (request.source_span, request.source_text_provenance_only),
                (request.query_span, request.query_text_provenance_only),
            ]:
                if span is not None and (
                    span.end > len(self.original_question)
                    or self.original_question[span.start : span.end] != text
                ):
                    raise ValueError("provenance does not match original text")
            if isinstance(request.reference, LiteralReference):
                ref = request.reference
                if (
                    ref.current_input_span.end > len(self.original_question)
                    or self.original_question[
                        ref.current_input_span.start : ref.current_input_span.end
                    ]
                    != ref.current_input_filename
                ):
                    raise ValueError("literal filename must come from current input")
        if self.interpretation_identity != digest(
            self.interpretation.model_dump(mode="json")
        ) or self.context_identity != digest(self.context.model_dump(mode="json")):
            raise ValueError("interpretation/context identity mismatch")
        if self.input_identity != digest(self.model_dump(mode="json", exclude={"input_identity"})):
            raise ValueError("input identity mismatch")
        return self

    def provider_state(self) -> dict[str, object]:
        return {
            "ORIGINAL_USER_REQUEST": self.original_question,
            "PROPOSED_OPERATIONAL_INTERPRETATION": self.interpretation.model_dump(mode="json"),
            "BOUNDED_REFERENCE_CONTEXT": self.context.provider_data(),
        }


def summarize_request(
    bound: d.BoundInterpretation, request: d.SemanticRequest, position: int
) -> RequestSummary:
    registry = {c.candidate_id: c for c in bound.input.candidates}
    text = bound.input.question
    query_span = None
    if isinstance(request, d.FileInventoryRequest) or isinstance(
        request, d.CollectionSummaryRequest
    ):
        reference: CoverageReference = SimpleReference(kind="DEFAULT_COLLECTION")
        scope = "ALL_VISIBLE_INDEXED_FILES"
    elif isinstance(request, d.ChitchatRequest):
        reference = SimpleReference(kind="SOCIAL_INPUT")
        scope = "SOCIAL_ONLY"
    elif isinstance(request, d.ConversationHistoryRequest):
        reference = HistoryReference(
            role=request.reference.role, relative_position=request.reference.relative_position
        )
        scope = "BOUNDED_CONVERSATION_HISTORY"
    elif isinstance(request, d.GroundedRagRequest):
        scope = "INDEXED_DOCUMENT_CONTENTS"
        if isinstance(request.query, d.OriginalQuery):
            reference = SimpleReference(kind="ORIGINAL_QUERY")
            query_span = request.query.span
        else:
            reference = TopicContextReference()
    else:
        scope = "ONE_REFERENCED_FILE"
        ref = request.action.target
        if isinstance(ref, d.LiteralMention):
            candidate = registry[ref.candidate_id]
            assert isinstance(candidate, d.LiteralFileCandidate)
            source = d.InputSpan(start=candidate.source.start, end=candidate.source.end)
            reference = LiteralReference(
                current_input_span=source, current_input_filename=text[source.start : source.end]
            )
        elif isinstance(ref, d.MetadataSelector):
            reference = SelectorReference(selector=ref.selector)
        elif isinstance(ref, d.ContextFileReference):
            reference = FileContextReference(reference_kind=ref.reference_kind)
        elif isinstance(ref, d.RuntimeResultReference):
            reference = RuntimeReference()
        else:
            reference = SimpleReference(kind="UNSPECIFIED_FILE")
        if isinstance(request.action, d.FileQuestionRequest):
            query_span = request.action.question_span
    return RequestSummary.model_validate(
        {
            "position": position,
            "capability": request.capability,
            "operation": request.operation,
            "reference": reference,
            "scope": scope,
            "ordering": request.ordering if isinstance(request, d.FileInventoryRequest) else None,
            "source_span": request.input_span,
            "source_text_provenance_only": text[request.input_span.start : request.input_span.end],
            "query_span": query_span,
            "query_text_provenance_only": text[query_span.start : query_span.end]
            if query_span
            else None,
        }
    )


def make_input(
    question: str, summary: InterpretationSummary, context: CoverageContext
) -> CoverageInput:
    from .contracts import contract_identity, routing_lock_identity

    fields = {
        "serialization_version": INPUT_VERSION,
        "original_question": question,
        "interpretation": summary.model_dump(mode="json"),
        "context": context.model_dump(mode="json"),
        "routing_contract_identity": routing_lock_identity(),
        "interpretation_identity": digest(summary.model_dump(mode="json")),
        "context_identity": digest(context.model_dump(mode="json")),
        "contract_identity": contract_identity(),
    }
    return CoverageInput.model_validate({**fields, "input_identity": digest(fields)})


def serialize_interpretation(
    bound: d.BoundInterpretation,
    state: d.ConversationState | None = None,
    *,
    proposed_cardinality: Literal["ONE", "TWO", "THREE", "OVER_LIMIT"] | None = None,
) -> CoverageInput:
    bound = d.BoundInterpretation.model_validate_json(bound.model_dump_json())
    value = bound.interpretation
    if isinstance(value, d.SemanticAmbiguity):
        raise ValueError("non-executable ambiguity must halt before coverage")
    if isinstance(value, d.RequestedOperations):
        requests = tuple(summarize_request(bound, r, i) for i, r in enumerate(value.requests, 1))
        cardinality = {1: "ONE", 2: "TWO", 3: "THREE"}[len(requests)]
        if proposed_cardinality is not None and proposed_cardinality != cardinality:
            raise ValueError("routing cardinality/domain mismatch")
        reason = (
            d.UnsupportedReason.RESULT_DEPENDENCY_UNSUPPORTED
            if any(isinstance(q.reference, RuntimeReference) for q in requests)
            else None
        )
        summary = InterpretationSummary.model_validate(
            {
                "proposed_cardinality": cardinality,
                "disposition": "NON_EXECUTABLE" if reason else "PROPOSED_OPERATIONS",
                "requests": requests,
                "unsupported_reason": reason,
            }
        )
    else:
        if proposed_cardinality is None and value.reason != d.UnsupportedReason.REQUEST_LIMIT:
            raise ValueError("unsupported domain alone has no original cardinality; supply it")
        cardinality = proposed_cardinality or "OVER_LIMIT"
        summary = InterpretationSummary(
            proposed_cardinality=cardinality,
            disposition="NON_EXECUTABLE",
            unsupported_reason=value.reason,
        )
    return make_input(
        bound.input.question, summary, context_from_state(state or d.ConversationState())
    )


class VerdictProbability(d.DomainModel):
    verdict: CoverageVerdict
    probability: float = Field(ge=0, le=1, allow_inf_nan=False)


class CoverageUsage(d.DomainModel):
    input_tokens: StrictInt | None = Field(default=None, ge=0)
    output_tokens: StrictInt | None = Field(default=None, ge=0)


class CoverageObservation(d.DomainModel):
    provider: Literal["typesafe-direct"] = "typesafe-direct"
    requested_model: Literal["jev-latest"] = "jev-latest"
    returned_model: Literal["jev-latest", "jev-1.13.0"] | None = None
    status: Literal["SUCCESS", "PROVIDER_ERROR", "INVALID_RESPONSE", "NOT_EXECUTED"]
    error_code: (
        Literal[
            "AUTH_ERROR",
            "RATE_LIMITED",
            "HTTP_ERROR",
            "TIMEOUT",
            "TRANSPORT_ERROR",
            "MISSING_KEY",
            "EXECUTION_NOT_AUTHORIZED",
            "INVALID_JSON",
            "INVALID_MODEL",
            "INVALID_USAGE",
            "INVALID_ANSWERS",
            "INVALID_PROBABILITIES",
            "RESPONSE_TOO_LARGE",
            "INPUT_IDENTITY_MISMATCH",
            "CONTRACT_MISMATCH",
            "REQUEST_TOO_LARGE",
        ]
        | None
    ) = None
    selected: CoverageVerdict | None = None
    probabilities: tuple[VerdictProbability, ...] = Field(default=(), max_length=3)
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    http_status: StrictInt | None = None
    latency_ms: float = Field(default=0, ge=0, allow_inf_nan=False)
    usage: CoverageUsage = Field(default_factory=CoverageUsage)
    post_attempts: StrictInt = Field(default=0, ge=0, le=1)
    contract_identity: Hash

    @model_validator(mode="after")
    def coherent(self) -> "CoverageObservation":
        if self.status == "SUCCESS":
            if (
                self.selected is None
                or self.returned_model is None
                or self.confidence is None
                or self.error_code is not None
            ):
                raise ValueError("incomplete successful coverage response")
            if {p.verdict for p in self.probabilities} != set(CoverageVerdict) or len(
                self.probabilities
            ) != 3:
                raise ValueError("coverage distribution labels mismatch")
            from app.routing.providers.probability_validation import validate_distribution

            validate_distribution(
                {p.verdict.value: p.probability for p in self.probabilities}, self.selected.value
            )
        elif self.selected is not None or self.probabilities or self.confidence is not None:
            raise ValueError("failed observation cannot carry a successful-looking verdict")
        return self

    @property
    def selected_probability(self) -> float | None:
        return next((p.probability for p in self.probabilities if p.verdict == self.selected), None)

    @property
    def top_two_margin(self) -> float | None:
        values = sorted((p.probability for p in self.probabilities), reverse=True)
        return values[0] - values[1] if len(values) >= 2 else None


class CoverageResult(d.DomainModel):
    verdict: CoverageVerdict | None
    observation: CoverageObservation
    input_identity: Hash
    interpretation_identity: Hash
    context_identity: Hash
    contract_identity: Hash

    @model_validator(mode="after")
    def coherent(self) -> "CoverageResult":
        if (
            self.verdict != self.observation.selected
            or self.contract_identity != self.observation.contract_identity
        ):
            raise ValueError("verdict/observation identity mismatch")
        return self

    @property
    def permits_resolution(self) -> bool:
        return self.observation.status == "SUCCESS" and self.verdict == CoverageVerdict.PRESERVED

    def telemetry_record(self) -> dict[str, object]:
        data = self.model_dump(mode="json")
        data["selected_probability"] = self.observation.selected_probability
        data["top_two_margin"] = self.observation.top_two_margin
        return data


def serialize_routing_result(
    envelope: object, registry: object, result: object, state: d.ConversationState | None = None
) -> CoverageInput:
    """Keep every validated position when domain translation collapses unsupported work."""
    from app.routing.v2.preparation import PreparedEnvelope
    from app.routing.v2.options import OptionRegistry, RuntimeDependencyOption, semantic_request
    from app.routing.v2.observations import AdapterResult
    from app.routing.v2.translation import translate

    if (
        not isinstance(envelope, PreparedEnvelope)
        or not isinstance(registry, OptionRegistry)
        or not isinstance(result, AdapterResult)
    ):
        raise ValueError("validated routing types required")
    if result.interpretation is None or result.status not in ("SUCCESS", "STAGE1_OVER_LIMIT"):
        raise ValueError("non-interpretable routing result must halt")
    current_state = state or d.ConversationState()
    if (
        envelope.context_identity
        != hashlib.sha256(current_state.model_dump_json().encode()).hexdigest()
        or result.preparation_hash != envelope.identity_hash
    ):
        raise ValueError("routing preparation/context identity mismatch")
    if (
        result.interpretation.input != envelope.input
        or not result.stages
        or result.stages[0].status != "SUCCESS"
    ):
        raise ValueError("routing input/stage provenance mismatch")
    selected = result.stages[0].answers[0].selected
    if selected == "OVER_LIMIT":
        return serialize_interpretation(
            result.interpretation, state, proposed_cardinality="OVER_LIMIT"
        )
    count = {"ONE": 1, "TWO": 2, "THREE": 3}.get(selected)
    if count is None or len(result.stages) != 2 or result.stages[1].status != "SUCCESS":
        raise ValueError("incomplete required routing positions")
    translated = translate(envelope, registry, count, result.stages[1].answers)
    if translated.status != "SUCCESS" or translated.interpretation != result.interpretation:
        raise ValueError("translation identity mismatch")
    if isinstance(result.interpretation.interpretation, d.RequestedOperations):
        return serialize_interpretation(result.interpretation, state)
    options = {o.option_id: o for o in registry.options}
    answers = {a.answer_id: a for a in result.stages[1].answers}
    requests = []
    specials = []
    for position in range(1, count + 1):
        label = answers[f"REQUEST_{position}"].selected
        if label in ("UNSUPPORTED_OPERATION", "SEMANTICALLY_AMBIGUOUS"):
            specials.append(
                SpecialSelection.model_validate({"position": position, "special": label})
            )
        elif isinstance(options[label], RuntimeDependencyOption):
            specials.append(SpecialSelection(position=position, special="UNSUPPORTED_OPERATION"))
        else:
            request = semantic_request(envelope, options[label])
            assert not isinstance(request, d.UnsupportedRequest)
            requests.append(summarize_request(result.interpretation, request, position))
    value = result.interpretation.interpretation
    assert isinstance(value, d.UnsupportedRequest)
    summary = InterpretationSummary.model_validate(
        {
            "proposed_cardinality": selected,
            "disposition": "NON_EXECUTABLE",
            "unsupported_reason": value.reason,
            "requests": requests,
            "special_selections": specials,
        }
    )
    return make_input(
        envelope.input.question, summary, context_from_state(state or d.ConversationState())
    )
