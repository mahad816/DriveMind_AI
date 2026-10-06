"""Atomic selections to domain: never repair, reorder, or deduplicate output."""

from pydantic import ValidationError
from app.routing.v2 import domain as d
from app.routing.v2.contracts import digest
from app.routing.v2.preparation import PreparedEnvelope
from app.routing.v2.options import OptionRegistry, registry_matches, semantic_request
from app.routing.v2.questions import SPECIAL_OUTCOMES
from app.routing.v2.observations import ChoiceObservation, AdapterResult, SemanticAmbiguitySignal


def translate(
    envelope: PreparedEnvelope,
    registry: OptionRegistry,
    count: int,
    answers: tuple[ChoiceObservation, ...],
) -> AdapterResult:
    if type(count) is not int or count not in (1, 2, 3):
        return AdapterResult(status="DOMAIN_TRANSLATION_ERROR", error_code="CARDINALITY_INVALID")
    if not registry_matches(envelope, registry):
        return AdapterResult(status="DOMAIN_TRANSLATION_ERROR", error_code="STALE_OPTION_REGISTRY")
    expected = {f"REQUEST_{i}" for i in range(1, count + 1)}
    by_id = {a.answer_id: a for a in answers}
    if len(by_id) != len(answers) or set(by_id) != expected:
        return AdapterResult(status="DOMAIN_TRANSLATION_ERROR", error_code="POSITION_IDS_MISMATCH")
    options = {o.option_id: o for o in registry.options}
    labels = [by_id[f"REQUEST_{i}"].selected for i in range(1, count + 1)]
    for i, label in enumerate(labels, 1):
        if label not in options and label not in SPECIAL_OUTCOMES:
            return AdapterResult(
                status="DOMAIN_TRANSLATION_ERROR", error_code="UNKNOWN_OPTION", request_position=i
            )
    executable = [label for label in labels if label in options]
    if len(executable) != len(set(executable)):
        return AdapterResult(
            status="DOMAIN_TRANSLATION_ERROR", error_code="DUPLICATE_OPTION_SELECTION"
        )
    spans = {s.span_id: s.span for s in envelope.spans}
    overlaps = []
    selected = [(i, options[label]) for i, label in enumerate(labels, 1) if label in options]
    for j, (i, one) in enumerate(selected):
        for k, two in selected[j + 1 :]:
            a, b = spans[one.source_span_id], spans[two.source_span_id]
            if b.end <= a.start:
                return AdapterResult(
                    status="DOMAIN_TRANSLATION_ERROR",
                    error_code="REQUEST_ORDER_REVERSED",
                    request_position=k,
                )
            if a.start < b.end and b.start < a.end:
                overlaps.append((i, k))
    full = d.InputSpan(start=0, end=len(envelope.input.question))
    if "SEMANTICALLY_AMBIGUOUS" in labels:
        return AdapterResult(
            status="SEMANTIC_AMBIGUITY",
            semantic_signal=SemanticAmbiguitySignal(
                request_positions=tuple(
                    i for i, label in enumerate(labels, 1) if label == "SEMANTICALLY_AMBIGUOUS"
                )
            ),
            error_code="EXPLICIT_AMBIGUITY_SIGNAL",
            request_position=labels.index("SEMANTICALLY_AMBIGUOUS") + 1,
            source_overlaps=tuple(overlaps),
        )
    if "UNSUPPORTED_OPERATION" in labels:
        unsupported = d.UnsupportedRequest(reason=d.UnsupportedReason.OPERATION, input_span=full)
        return AdapterResult(
            status="SUCCESS",
            interpretation=d.BoundInterpretation(input=envelope.input, interpretation=unsupported),
            source_overlaps=tuple(overlaps),
        )
    try:
        requests = tuple(semantic_request(envelope, options[label]) for label in labels)
        dependency = next((q for q in requests if isinstance(q, d.UnsupportedRequest)), None)
        if dependency is not None:
            return AdapterResult(
                status="SUCCESS",
                interpretation=d.BoundInterpretation(
                    input=envelope.input, interpretation=dependency
                ),
                source_overlaps=tuple(overlaps),
            )
        executable_requests = tuple(q for q in requests if not isinstance(q, d.UnsupportedRequest))
        provenance = [digest(request.model_dump(mode="json")) for request in executable_requests]
        if len(provenance) != len(set(provenance)):
            return AdapterResult(
                status="DOMAIN_TRANSLATION_ERROR", error_code="DUPLICATE_SEMANTIC_PROVENANCE"
            )
        value = d.BoundInterpretation(
            input=envelope.input, interpretation=d.RequestedOperations(requests=executable_requests)
        )
    except (ValidationError, KeyError):
        return AdapterResult(status="DOMAIN_TRANSLATION_ERROR", error_code="DOMAIN_INVARIANT")
    return AdapterResult(status="SUCCESS", interpretation=value, source_overlaps=tuple(overlaps))
