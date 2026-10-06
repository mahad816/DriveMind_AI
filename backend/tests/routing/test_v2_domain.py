"""Provider-free structural v2 tests; no resolver, database, or network."""

import json
from uuid import UUID

import pytest
from pydantic import TypeAdapter, ValidationError

from app.routing.v2 import domain as d

REQUEST = TypeAdapter(d.SemanticRequest)
INTERPRETATION = TypeAdapter(d.SemanticInterpretation)
REFERENCE = TypeAdapter(d.FileReference)
CANDIDATE = TypeAdapter(d.BindingCandidate)
READINESS = TypeAdapter(d.Readiness)
SPAN = d.InputSpan(start=0, end=10)


def target(candidate: str = "c1") -> d.FileTargetRequest:
    return d.FileTargetRequest(
        input_span=SPAN,
        action=d.SummarizeFileRequest(target=d.LiteralMention(candidate_id=candidate)),
    )


def inventory() -> d.FileInventoryRequest:
    return d.FileInventoryRequest(input_span=SPAN, operation="LIST")


@pytest.mark.parametrize("count", [1, 2, 3])
def test_cardinality_order_and_round_trip(count: int) -> None:
    requests = (inventory(), target("c1"), target("c2"))[:count]
    bundle = d.RequestedOperations(requests=requests)
    assert bundle.cardinality == count and bundle.requests == requests
    assert INTERPRETATION.validate_json(bundle.model_dump_json()) == bundle
    assert "cardinality" not in bundle.model_dump()


@pytest.mark.parametrize("count", [0, 4])
def test_invalid_cardinality(count: int) -> None:
    with pytest.raises(ValidationError):
        d.RequestedOperations(requests=(inventory(),) * count)


def test_repetition_is_never_deduplicated() -> None:
    one, two = target("c1"), target("c2")
    assert d.RequestedOperations(requests=(one, two)).requests == (one, two)
    assert d.RequestedOperations(requests=(one, one)).cardinality == 2


@pytest.mark.parametrize(
    "reference",
    [
        d.MetadataSelector(candidate_id="c1", selector=d.ReferenceSelector.LATEST),
        d.MetadataSelector(candidate_id="c1", selector=d.ReferenceSelector.OLDEST),
        d.ContextFileReference(candidate_id="c1", reference_kind=d.FileContextKind.IT),
        d.UnspecifiedFile(candidate_id="c1"),
    ],
)
def test_file_reference_variants(reference: d.FileReference) -> None:
    request = d.FileTargetRequest(input_span=SPAN, action=d.SummarizeFileRequest(target=reference))
    assert request.operation == "SUMMARIZE"
    assert REQUEST.validate_json(request.model_dump_json()) == request


def test_all_capabilities() -> None:
    requests: list[d.SemanticRequest] = [
        inventory(),
        target(),
        d.CollectionSummaryRequest(input_span=SPAN),
        d.ConversationHistoryRequest(
            input_span=SPAN, candidate_id="c1", reference=d.MessageReference(role="user")
        ),
        d.GroundedRagRequest(input_span=SPAN, query=d.OriginalQuery(span=SPAN)),
        d.ChitchatRequest(input_span=SPAN),
        d.FileTargetRequest(
            input_span=SPAN,
            action=d.FileQuestionRequest(
                target=d.LiteralMention(candidate_id="c1"), question_span=SPAN
            ),
        ),
    ]
    for request in requests:
        assert REQUEST.validate_json(request.model_dump_json()) == request


@pytest.mark.parametrize(
    "data",
    [
        {"capability": "FILE_INVENTORY", "operation": "SUMMARIZE"},
        {"capability": "CHITCHAT", "operation": "ANSWER"},
        {"capability": "META", "operation": "RESPOND"},
        {
            "capability": "FILE_TARGET",
            "action": {"operation": "COUNT", "target": {"kind": "literal", "candidate_id": "c1"}},
        },
        {"capability": "FILE_TARGET", "action": {"operation": "SUMMARIZE"}},
        {"capability": "CHITCHAT", "target": {"kind": "literal", "candidate_id": "c1"}},
        {"capability": "COLLECTION_SUMMARY", "scope": {"kind": "custom_category"}},
        {"capability": "FILE_INVENTORY", "operation": "COUNT", "ordering": "NAME_ASC"},
        {"capability": "FILE_INVENTORY", "operation": "LATEST", "ordering": "NAME_ASC"},
        {"capability": "FILE_INVENTORY", "operation": "OLDEST", "ordering": "NAME_ASC"},
        {"capability": "CHITCHAT", "database_id": "invented"},
        {"capability": "CHITCHAT", "model": "provider", "confidence": 0.9},
        {"capability": "CHITCHAT", "depends_on": "request_1"},
        {
            "capability": "FILE_TARGET",
            "action": {
                "operation": "ANSWER_QUESTION",
                "target": {"kind": "literal", "candidate_id": "c1"},
            },
        },
    ],
)
def test_invalid_requests(data: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        REQUEST.validate_python({"input_span": SPAN.model_dump(), **data})


@pytest.mark.parametrize(
    "data",
    [
        {"kind": "literal", "candidate_id": "c1", "filename": "invented.pdf"},
        {"kind": "literal", "candidate_id": "invented.pdf"},
        {"kind": "literal", "file_id": "invented"},
        {"kind": "selector", "candidate_id": "c1", "selector": "NEWEST_FACT"},
        {"kind": "dependency", "request_id": "request_1"},
    ],
)
def test_illegal_references(data: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        REFERENCE.validate_python(data)


def literal_input() -> d.PreparedInput:
    return d.PreparedInput(
        question="Summarize report.pdf",
        candidates=(
            d.LiteralFileCandidate(candidate_id="c1", source=d.SourceLocation(start=10, end=20)),
        ),
    )


def test_registry_and_file_question_binding() -> None:
    prepared = literal_input()
    request = d.FileTargetRequest(
        input_span=d.InputSpan(start=0, end=20),
        action=d.FileQuestionRequest(
            target=d.LiteralMention(candidate_id="c1"), question_span=SPAN
        ),
    )
    bound = d.BoundInterpretation(
        input=prepared, interpretation=d.RequestedOperations(requests=(request,))
    )
    assert d.BoundInterpretation.model_validate_json(bound.model_dump_json()) == bound
    with pytest.raises(ValidationError):
        d.BoundInterpretation(
            input=prepared, interpretation=d.RequestedOperations(requests=(target("c2"),))
        )
    with pytest.raises(ValidationError):
        d.PreparedInput(question=prepared.question, candidates=prepared.candidates * 2)
    with pytest.raises(ValidationError):
        d.PreparedInput(question="short", candidates=prepared.candidates)


def test_selector_and_context_binding() -> None:
    candidates: tuple[d.BindingCandidate, ...] = (
        d.SelectorCandidate(
            candidate_id="c1",
            source=d.SourceLocation(start=0, end=6),
            selector=d.ReferenceSelector.LATEST,
        ),
        d.ContextFileCandidate(
            candidate_id="c2",
            source=d.ContextHandle(handle="ACTIVE_FILES"),
            reference_kind=d.FileContextKind.IT,
        ),
        d.ContextTopicCandidate(candidate_id="c3", source=d.ContextHandle(handle="ACTIVE_TOPIC")),
        d.PriorMessageCandidate(
            candidate_id="c4",
            source=d.ContextHandle(handle="RECENT_MESSAGES"),
            reference=d.MessageReference(role="assistant"),
        ),
        d.UnspecifiedTargetCandidate(candidate_id="c5", source=d.SourceLocation(start=0, end=6)),
        d.CollectionCandidate(candidate_id="c6"),
    )
    prepared = d.PreparedInput(question="latest file", candidates=candidates)
    requests: list[d.SemanticRequest] = [
        d.FileTargetRequest(
            input_span=SPAN,
            action=d.SummarizeFileRequest(
                target=d.MetadataSelector(candidate_id="c1", selector=d.ReferenceSelector.LATEST)
            ),
        ),
        d.FileTargetRequest(
            input_span=SPAN,
            action=d.SummarizeFileRequest(
                target=d.ContextFileReference(
                    candidate_id="c2", reference_kind=d.FileContextKind.IT
                )
            ),
        ),
        d.GroundedRagRequest(input_span=SPAN, query=d.ContextTopicReference(candidate_id="c3")),
        d.ConversationHistoryRequest(
            input_span=SPAN, candidate_id="c4", reference=d.MessageReference(role="assistant")
        ),
        d.FileTargetRequest(
            input_span=SPAN,
            action=d.SummarizeFileRequest(target=d.UnspecifiedFile(candidate_id="c5")),
        ),
    ]
    for request in requests:
        d.BoundInterpretation(
            input=prepared, interpretation=d.RequestedOperations(requests=(request,))
        )
    wrong = d.FileTargetRequest(
        input_span=SPAN,
        action=d.SummarizeFileRequest(
            target=d.MetadataSelector(candidate_id="c1", selector=d.ReferenceSelector.OLDEST)
        ),
    )
    with pytest.raises(ValidationError):
        d.BoundInterpretation(
            input=prepared, interpretation=d.RequestedOperations(requests=(wrong,))
        )
    with pytest.raises(ValidationError):
        d.ContextTopicCandidate(candidate_id="c1", source=d.ContextHandle(handle="ACTIVE_FILES"))


@pytest.mark.parametrize(
    "span",
    [
        {"start": 1, "end": 1},
        {"start": -1, "end": 4},
        {"start": True, "end": 4},
        {"start": 0, "end": 8001},
    ],
)
def test_bad_spans(span: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        d.InputSpan.model_validate(span)


def test_interpretation_variants_and_immutability() -> None:
    bundle = d.RequestedOperations(requests=(inventory(),))
    ambiguity = d.SemanticAmbiguity(
        input_span=SPAN, alternatives=(bundle, d.RequestedOperations(requests=(target(),)))
    )
    unsupported = d.UnsupportedRequest(input_span=SPAN, reason=d.UnsupportedReason.DEPENDENCY)
    for value in [ambiguity, unsupported]:
        assert INTERPRETATION.validate_json(value.model_dump_json()) == value
    with pytest.raises(ValidationError):
        d.SemanticAmbiguity(input_span=SPAN, alternatives=(bundle,))
    with pytest.raises(ValidationError):
        d.RequestedOperations.model_validate(
            {"requests": [inventory().model_dump()], "cardinality": 2}
        )
    with pytest.raises(ValidationError):
        setattr(bundle, "requests", ())


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "READY"},
        {"status": "NEEDS_CLARIFICATION", "reason": "UNRESOLVED_REFERENCE"},
        {"status": "NEEDS_CLARIFICATION", "reason": "AMBIGUOUS_REFERENCE"},
        {"status": "NEEDS_CLARIFICATION", "reason": "MISSING_REQUIRED_ARGUMENT"},
        {"status": "NEEDS_CLARIFICATION", "reason": "AMBIGUOUS_SEMANTIC_INTERPRETATION"},
        {"status": "UNSUPPORTED", "reason": "DEPENDENCY"},
        {"status": "FAILED", "reason": "RESOLUTION_UNAVAILABLE"},
    ],
)
def test_readiness_round_trip(payload: dict[str, str]) -> None:
    value = READINESS.validate_python(payload)
    assert READINESS.validate_json(value.model_dump_json()) == value
    with pytest.raises(ValidationError):
        READINESS.validate_python({**payload, "probability": 0.9})


def test_conversation_state_resolved_ids_and_bounds() -> None:
    bound = d.BoundInterpretation(
        input=literal_input(), interpretation=d.RequestedOperations(requests=(target(),))
    )
    file_id = UUID("00000000-0000-0000-0000-000000000001")
    state = d.ConversationState(
        last_substantive_request=bound,
        last_successful_request_bundle=bound,
        active_file_ids=(file_id,),
        active_topic=d.ActiveTopic(
            original_question="Architecture?", answer_summary="A document discussion."
        ),
        recent_messages=(d.RecentMessage(role="user", text="Summarize it."),),
    )
    assert d.ConversationState.model_validate_json(state.model_dump_json()) == state
    assert json.loads(state.model_dump_json())["active_file_ids"] == [str(file_id)]
    for data in [
        {"active_file_ids": ["fake-id"]},
        {"active_file_ids": [str(file_id)] * 2},
        {"recent_messages": [{"role": "user", "text": "x"}] * 7},
        {"recent_messages": [{"role": "user", "text": "x" * 2000}] * 4},
        {"active_topic": {"original_question": " ", "answer_summary": " "}},
    ]:
        with pytest.raises(ValidationError):
            d.ConversationState.model_validate(data)
    with pytest.raises(ValidationError):
        d.MessageReference(role="user", relative_position=7)


@pytest.mark.parametrize("operation", ["LIST", "COUNT", "LATEST", "OLDEST"])
def test_valid_inventory_operations(operation: str) -> None:
    value = d.FileInventoryRequest.model_validate(
        {"operation": operation, "input_span": SPAN.model_dump()}
    )
    assert value.operation == operation
    ordered = d.FileInventoryRequest(operation="LIST", input_span=SPAN, ordering="NAME_ASC")
    assert ordered.ordering == "NAME_ASC"


def test_span_and_state_ambiguity_boundaries() -> None:
    prepared = literal_input()
    bundle = d.RequestedOperations(requests=(inventory(),))
    ambiguity = d.SemanticAmbiguity(
        input_span=SPAN, alternatives=(bundle, d.RequestedOperations(requests=(target(),)))
    )
    bound = d.BoundInterpretation(input=prepared, interpretation=ambiguity)
    d.ConversationState(last_substantive_request=bound)
    with pytest.raises(ValidationError):
        d.ConversationState(last_successful_request_bundle=bound)
    with pytest.raises(ValidationError):
        d.PreparedInput(question=" ")
    with pytest.raises(ValidationError):
        d.BoundInterpretation(
            input=prepared,
            interpretation=d.RequestedOperations(
                requests=(d.ChitchatRequest(input_span=d.InputSpan(start=0, end=21)),)
            ),
        )
    with pytest.raises(ValidationError):
        CANDIDATE.validate_python(
            {
                "kind": "literal_file",
                "candidate_id": "c1",
                "source": {"kind": "input", "start": 0, "end": 3},
                "filename": "invented.pdf",
            }
        )
