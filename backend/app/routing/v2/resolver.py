"""Resolve known typed semantics against trusted input/state and metadata only."""

import unicodedata
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError

from app.routing.v2 import domain as d
from app.routing.v2 import resolved as r


class OutputContextKind(StrEnum):
    FILE_CONTEXT = "FILE_CONTEXT"
    TOPIC_CONTEXT = "TOPIC_CONTEXT"


OUTPUT_CONTEXT = {
    ("FILE_INVENTORY", "LATEST"): OutputContextKind.FILE_CONTEXT,
    ("FILE_INVENTORY", "OLDEST"): OutputContextKind.FILE_CONTEXT,
    ("FILE_TARGET", "SUMMARIZE"): OutputContextKind.FILE_CONTEXT,
    ("FILE_TARGET", "ANSWER_QUESTION"): OutputContextKind.FILE_CONTEXT,
    ("GROUNDED_RAG", "ANSWER"): OutputContextKind.TOPIC_CONTEXT,
}


def dependency_positions(bound: d.BoundInterpretation) -> frozenset[int]:
    """Fail closed on possible result dependency; never infer coreference."""
    bundle = bound.interpretation
    if not isinstance(bundle, d.RequestedOperations):
        return frozenset()
    earlier: set[OutputContextKind] = set()
    blocked: set[int] = set()
    runtime_spans = tuple(
        c.source for c in bound.input.candidates if isinstance(c, d.RuntimeResultCandidate)
    )
    for index, request in enumerate(bundle.requests, 1):
        context = None
        if isinstance(request, d.FileTargetRequest):
            ref = request.action.target
            if isinstance(ref, d.RuntimeResultReference):
                blocked.add(index)
            elif isinstance(ref, d.ContextFileReference):
                context = OutputContextKind.FILE_CONTEXT
        elif isinstance(request, d.GroundedRagRequest) and isinstance(
            request.query, d.ContextTopicReference
        ):
            context = OutputContextKind.TOPIC_CONTEXT
        if context is not None:
            # Source spans may be broad or incorrectly selected. An explicit
            # runtime occurrence must not be bypassed via a context handle.
            if context in earlier or runtime_spans:
                blocked.add(index)
        output = OUTPUT_CONTEXT.get((request.capability, request.operation))
        if output is not None:
            earlier.add(output)
    return frozenset(blocked)


class FileMetadataProvider(Protocol):
    async def list_visible_indexed_files(self, user_id: UUID) -> tuple[r.IndexedFile, ...]:
        """Complete user-scoped INDEXED snapshot; no extraction/retrieval work."""
        ...


class MetadataUnavailable(Exception):
    """Expected lookup failure; never expose provider exception text."""


def clarification(
    index: int, reason: d.ClarificationReason, detail: str, files: tuple[r.IndexedFile, ...] = ()
) -> r.ClarificationRequirement:
    return r.ClarificationRequirement.model_validate(
        {
            "request_id": index,
            "reason": reason,
            "detail": detail,
            "options": [{"file_id": f.file_id, "name": f.name} for f in files[:3]],
            "match_count": len(files),
        }
    )


def canonical_filename(name: str) -> str:
    """Exact equivalence only: preserve whitespace, punctuation and extensions."""
    return unicodedata.normalize("NFC", unicodedata.normalize("NFC", name).casefold())


def exact_file(
    name: str, files: tuple[r.IndexedFile, ...], index: int
) -> r.IndexedFile | r.ClarificationRequirement:
    matches = tuple(f for f in files if f.name == name)
    if not matches:
        key = canonical_filename(name)
        matches = tuple(f for f in files if canonical_filename(f.name) == key)
    if not matches:
        return clarification(index, d.ClarificationReason.UNRESOLVED_REFERENCE, "FILE_NOT_FOUND")
    if len(matches) > 1:
        return clarification(
            index, d.ClarificationReason.AMBIGUOUS_REFERENCE, "DUPLICATE_FILENAME", matches
        )
    return next(iter(matches))


def recency_file(
    selector: d.ReferenceSelector, files: tuple[r.IndexedFile, ...], index: int
) -> r.IndexedFile | r.ClarificationRequirement:
    if not files:
        return clarification(index, d.ClarificationReason.UNRESOLVED_REFERENCE, "EMPTY_COLLECTION")
    # A missing timestamp could be the true extremum: do not exclude it silently.
    if any(f.modified_at is None for f in files):
        return clarification(index, d.ClarificationReason.UNRESOLVED_REFERENCE, "UNKNOWN_RECENCY")
    stamps = [f.modified_at for f in files if f.modified_at is not None]
    chosen = max(stamps) if selector == d.ReferenceSelector.LATEST else min(stamps)
    matches = tuple(f for f in files if f.modified_at == chosen)
    if len(matches) > 1:
        return clarification(
            index, d.ClarificationReason.AMBIGUOUS_REFERENCE, "RECENCY_TIE", matches
        )
    return next(iter(matches))


def context_file(
    state: d.ConversationState, files: tuple[r.IndexedFile, ...], index: int
) -> r.IndexedFile | r.ClarificationRequirement:
    ids = state.active_file_ids
    if not ids:
        return clarification(index, d.ClarificationReason.UNRESOLVED_REFERENCE, "NO_ACTIVE_FILE")
    matches = tuple(f for f in files if f.file_id in ids)
    if len(matches) != len(ids):
        return clarification(
            index, d.ClarificationReason.UNRESOLVED_REFERENCE, "ACTIVE_FILE_UNAVAILABLE", matches
        )
    if len(matches) > 1:
        return clarification(
            index, d.ClarificationReason.AMBIGUOUS_REFERENCE, "MULTIPLE_ACTIVE_FILES", matches
        )
    return next(iter(matches))


def history_message(
    reference: d.MessageReference, state: d.ConversationState, index: int
) -> d.RecentMessage | r.ClarificationRequirement:
    messages = [m for m in reversed(state.recent_messages) if m.role == reference.role]
    if len(messages) < reference.relative_position:
        return clarification(
            index, d.ClarificationReason.UNRESOLVED_REFERENCE, "HISTORY_UNAVAILABLE"
        )
    return messages[reference.relative_position - 1]


def topic_context(
    state: d.ConversationState, index: int
) -> d.ActiveTopic | r.ClarificationRequirement:
    # Extended phase-3 state may contain multiple separately successful topics.
    from app.routing.v2.state import RoutingConversationState

    topics = (
        state.active_topics
        if isinstance(state, RoutingConversationState)
        else (() if state.active_topic is None else (state.active_topic,))
    )
    if not topics:
        return clarification(index, d.ClarificationReason.UNRESOLVED_REFERENCE, "NO_ACTIVE_TOPIC")
    if len(topics) > 1:
        return clarification(
            index, d.ClarificationReason.AMBIGUOUS_REFERENCE, "MULTIPLE_ACTIVE_TOPICS"
        )
    return next(iter(topics))


def resolve_request(
    request: d.SemanticRequest,
    bound: d.BoundInterpretation,
    state: d.ConversationState,
    collection: r.ResolvedCollection,
    index: int,
) -> r.RequestResolution:
    question = bound.input.question
    span = request.input_span
    text = question[span.start : span.end]
    files = collection.files
    if isinstance(request, d.FileInventoryRequest):
        selected: r.IndexedFile | None = None
        if request.operation in ("LATEST", "OLDEST"):
            choice = recency_file(d.ReferenceSelector(request.operation), files, index)
            if isinstance(choice, r.ClarificationRequirement):
                return choice
            selected = choice
        return r.ReadyRequest(
            request_id=index,
            resolved=r.ResolvedInventoryRequest(
                operation=request.operation,
                ordering=request.ordering,
                collection=collection,
                selected_file=selected,
            ),
        )
    if isinstance(request, d.CollectionSummaryRequest):
        return r.ReadyRequest(
            request_id=index, resolved=r.ResolvedCollectionSummaryRequest(collection=collection)
        )
    if isinstance(request, d.FileTargetRequest):
        ref = request.action.target
        if isinstance(ref, d.RuntimeResultReference):
            return r.UnsupportedResolution(
                request_id=index, reason=d.UnsupportedReason.RESULT_DEPENDENCY_UNSUPPORTED
            )
        if isinstance(ref, d.LiteralMention):
            candidate = next(
                c for c in bound.input.candidates if c.candidate_id == ref.candidate_id
            )
            assert isinstance(candidate, d.LiteralFileCandidate)
            # Registry spans exclude quote delimiters. No trimming/case/fuzzy normalization.
            name = question[candidate.source.start : candidate.source.end]
            file = exact_file(name, files, index)
        elif isinstance(ref, d.MetadataSelector):
            file = recency_file(ref.selector, files, index)
        elif isinstance(ref, d.ContextFileReference):
            file = context_file(state, files, index)
        else:
            return clarification(
                index, d.ClarificationReason.MISSING_REQUIRED_ARGUMENT, "TARGET_REQUIRED"
            )
        if isinstance(file, r.ClarificationRequirement):
            return file
        if isinstance(request.action, d.FileQuestionRequest):
            q = request.action.question_span
            action: r.ResolvedFileSummary | r.ResolvedFileQuestion = r.ResolvedFileQuestion(
                file=file, question=question[q.start : q.end]
            )
        else:
            action = r.ResolvedFileSummary(file=file)
        return r.ReadyRequest(request_id=index, resolved=r.ResolvedFileTargetRequest(action=action))
    if isinstance(request, d.ConversationHistoryRequest):
        message = history_message(request.reference, state, index)
        if isinstance(message, r.ClarificationRequirement):
            return message
        return r.ReadyRequest(
            request_id=index,
            resolved=r.ResolvedHistoryRequest(message=message, reference=request.reference),
        )
    if isinstance(request, d.GroundedRagRequest):
        if isinstance(request.query, d.OriginalQuery):
            q = request.query.span
            query: r.ResolvedOriginalQuery | r.ResolvedTopicQuery = r.ResolvedOriginalQuery(
                text=question[q.start : q.end]
            )
        else:
            topic = topic_context(state, index)
            if isinstance(topic, r.ClarificationRequirement):
                return topic
            query = r.ResolvedTopicQuery(continuation=text, topic=topic)
        return r.ReadyRequest(request_id=index, resolved=r.ResolvedGroundedRequest(query=query))
    return r.ReadyRequest(request_id=index, resolved=r.ResolvedChitchatRequest(text=text))


def metadata_failure(
    bound: d.BoundInterpretation, state: d.ConversationState, user_id: UUID, reason: str
) -> r.ResolutionReport:
    assert isinstance(bound.interpretation, d.RequestedOperations)
    empty = r.ResolvedCollection(user_id=user_id, files=())
    outcomes: list[r.RequestResolution] = []
    for index, request in enumerate(bound.interpretation.requests, 1):
        if isinstance(
            request, (d.FileInventoryRequest, d.FileTargetRequest, d.CollectionSummaryRequest)
        ):
            outcomes.append(r.FailedRequest.model_validate({"request_id": index, "reason": reason}))
        else:
            outcomes.append(resolve_request(request, bound, state, empty, index))
    return r.ResolutionReport(source=bound, outcomes=tuple(outcomes))


async def resolve(
    bound: d.BoundInterpretation,
    *,
    trusted_input: d.PreparedInput,
    state: d.ConversationState,
    user_id: UUID,
    metadata: FileMetadataProvider,
) -> r.ResolutionReport | r.ResolutionFailure:
    """trusted_input is caller-owned preparation for this exact question/registry.

    State excludes the current incoming user message; history is prior turns.
    No executor runs here, including for a partly ready compound.
    """
    try:
        bound = d.BoundInterpretation.model_validate_json(bound.model_dump_json())
        trusted_input = d.PreparedInput.model_validate_json(trusted_input.model_dump_json())
        state = type(state).model_validate_json(state.model_dump_json())
    except ValidationError:
        return r.ResolutionFailure(reason="INVALID_INPUT")
    if bound.input != trusted_input:
        return r.ResolutionFailure(reason="PROVENANCE_MISMATCH")
    interpretation = bound.interpretation
    if isinstance(interpretation, d.SemanticAmbiguity):
        return r.ResolutionReport(
            source=bound,
            outcomes=(
                clarification(
                    1,
                    d.ClarificationReason.AMBIGUOUS_SEMANTIC_INTERPRETATION,
                    "COMPETING_INTERPRETATIONS",
                ),
            ),
        )
    if isinstance(interpretation, d.UnsupportedRequest):
        return r.ResolutionReport(
            source=bound,
            outcomes=(r.UnsupportedResolution(request_id=1, reason=interpretation.reason),),
        )
    blocked = dependency_positions(bound)
    needs_files = any(
        isinstance(q, (d.FileInventoryRequest, d.FileTargetRequest, d.CollectionSummaryRequest))
        for i, q in enumerate(interpretation.requests, 1)
        if i not in blocked
    )
    try:
        records = await metadata.list_visible_indexed_files(user_id) if needs_files else ()
    except Exception:
        # Cancellation remains unhandled (BaseException); lookup details stay private.
        return metadata_failure(bound, state, user_id, "METADATA_UNAVAILABLE")
    try:
        # Revalidate lookup data and stabilize ambiguity options independently of SQL order.
        files = tuple(
            sorted(
                (r.IndexedFile.model_validate_json(f.model_dump_json()) for f in records),
                key=lambda f: (f.name, str(f.file_id)),
            )
        )
        collection = r.ResolvedCollection(user_id=user_id, files=files)
    except (ValidationError, AttributeError, TypeError):
        return metadata_failure(bound, state, user_id, "INVALID_METADATA")
    outcomes = tuple(
        r.UnsupportedResolution(
            request_id=i, reason=d.UnsupportedReason.RESULT_DEPENDENCY_UNSUPPORTED
        )
        if i in blocked
        else resolve_request(request, bound, state, collection, i)
        for i, request in enumerate(interpretation.requests, 1)
    )
    return r.ResolutionReport(source=bound, outcomes=outcomes)
