"""Offline typed resolution/state tests using explicit fake metadata snapshots."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError, TypeAdapter

from app.routing.v2 import domain as d
from app.routing.v2 import resolved as r
from app.routing.v2.resolver import resolve, MetadataUnavailable
from app.routing.v2.state import (
    SuccessfulExecution,
    TopicAnswer,
    apply_success,
    preserve_context,
    RoutingConversationState,
)

USER = UUID(int=1)
DATE = datetime(2026, 1, 1, tzinfo=UTC)


class FakeMetadata:
    def __init__(self, files: tuple[r.IndexedFile, ...] = (), fail: bool = False) -> None:
        self.files = files
        self.fail = fail
        self.calls = 0

    async def list_visible_indexed_files(self, user_id: UUID) -> tuple[r.IndexedFile, ...]:
        assert user_id == USER
        self.calls += 1
        if self.fail:
            raise MetadataUnavailable("secret lookup detail")
        return self.files


def file(index: int = 2, name: str = "Report.txt", date: datetime | None = DATE) -> r.IndexedFile:
    return r.IndexedFile(file_id=UUID(int=index), user_id=USER, name=name, modified_at=date)


def literal(name: str = "Report.txt") -> d.BoundInterpretation:
    question = f'Summarize "{name}"'
    source = d.PreparedInput(
        question=question,
        candidates=(
            d.LiteralFileCandidate(
                candidate_id="c1", source=d.SourceLocation(start=11, end=11 + len(name))
            ),
        ),
    )
    request = d.FileTargetRequest(
        input_span=d.InputSpan(start=0, end=len(question)),
        action=d.SummarizeFileRequest(target=d.LiteralMention(candidate_id="c1")),
    )
    return d.BoundInterpretation(
        input=source, interpretation=d.RequestedOperations(requests=(request,))
    )


def selector(value: d.ReferenceSelector) -> d.BoundInterpretation:
    question = (
        "Summarize latest file" if value == d.ReferenceSelector.LATEST else "Summarize oldest file"
    )
    candidate = d.SelectorCandidate(
        candidate_id="c1", source=d.SourceLocation(start=10, end=16), selector=value
    )
    request = d.FileTargetRequest(
        input_span=d.InputSpan(start=0, end=len(question)),
        action=d.SummarizeFileRequest(target=d.MetadataSelector(candidate_id="c1", selector=value)),
    )
    return d.BoundInterpretation(
        input=d.PreparedInput(question=question, candidates=(candidate,)),
        interpretation=d.RequestedOperations(requests=(request,)),
    )


def contextual(topic: bool = False) -> d.BoundInterpretation:
    span = d.InputSpan(start=0, end=12)
    candidate: d.BindingCandidate = (
        d.ContextTopicCandidate(candidate_id="c1", source=d.ContextHandle(handle="ACTIVE_TOPIC"))
        if topic
        else d.ContextFileCandidate(
            candidate_id="c1",
            source=d.ContextHandle(handle="ACTIVE_FILES"),
            reference_kind=d.FileContextKind.IT,
        )
    )
    request: d.SemanticRequest = (
        d.GroundedRagRequest(input_span=span, query=d.ContextTopicReference(candidate_id="c1"))
        if topic
        else d.FileTargetRequest(
            input_span=span,
            action=d.SummarizeFileRequest(
                target=d.ContextFileReference(
                    candidate_id="c1", reference_kind=d.FileContextKind.IT
                )
            ),
        )
    )
    return d.BoundInterpretation(
        input=d.PreparedInput(question="Summarize it", candidates=(candidate,)),
        interpretation=d.RequestedOperations(requests=(request,)),
    )


def simple(capability: str = "FILE_INVENTORY", operation: str = "LIST") -> d.BoundInterpretation:
    span = d.InputSpan(start=0, end=10)
    data = {"capability": capability, "operation": operation, "input_span": span.model_dump()}
    if capability == "GROUNDED_RAG":
        data["query"] = {"kind": "original_query", "span": span.model_dump()}
    request = TypeAdapter(d.SemanticRequest).validate_python(data)
    return d.BoundInterpretation(
        input=d.PreparedInput(question="A question"),
        interpretation=d.RequestedOperations(requests=(request,)),
    )


async def run(
    bound: d.BoundInterpretation,
    files: tuple[r.IndexedFile, ...] = (),
    state: d.ConversationState | None = None,
) -> r.ResolutionReport:
    result = await resolve(
        bound,
        trusted_input=bound.input,
        state=state or d.ConversationState(),
        user_id=USER,
        metadata=FakeMetadata(files),
    )
    assert isinstance(result, r.ResolutionReport)
    return result


def ready(result: r.ResolutionReport) -> r.ReadyBundle:
    assert result.status == "READY" and result.ready_bundle is not None
    return result.ready_bundle


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "files,detail",
    [
        ((), "FILE_NOT_FOUND"),
        ((file(), file(3)), "DUPLICATE_FILENAME"),
        ((file(name="Repor.txt"),), "FILE_NOT_FOUND"),
    ],
)
async def test_literal_absent_duplicate_and_no_normalization(
    files: tuple[r.IndexedFile, ...], detail: str
) -> None:
    result = await run(literal(), files)
    assert result.ready_bundle is None
    outcome = result.outcomes[0]
    assert isinstance(outcome, r.ClarificationRequirement) and outcome.detail == detail


@pytest.mark.asyncio
async def test_unique_literal_quotes_and_explicit_over_context() -> None:
    wanted, other = file(), file(3, "Other.txt")
    result = await run(
        literal(), (wanted, other), d.ConversationState(active_file_ids=(other.file_id,))
    )
    request = ready(result).requests[0]
    assert isinstance(request, r.ResolvedFileTargetRequest)
    assert request.action.file == wanted
    assert request.action.file.name == "Report.txt"
    assert "target" not in request.model_dump()["action"]


@pytest.mark.asyncio
async def test_provenance_and_stale_registry_fail_before_lookup() -> None:
    bound = literal()
    metadata = FakeMetadata((file(),))
    result = await resolve(
        bound,
        trusted_input=literal("Other.txt").input,
        state=d.ConversationState(),
        user_id=USER,
        metadata=metadata,
    )
    assert isinstance(result, r.ResolutionFailure) and result.reason == "PROVENANCE_MISMATCH"
    assert metadata.calls == 0
    damaged = bound.model_copy(
        update={
            "interpretation": d.RequestedOperations(
                requests=(
                    d.FileTargetRequest(
                        input_span=d.InputSpan(start=0, end=10),
                        action=d.SummarizeFileRequest(target=d.LiteralMention(candidate_id="c2")),
                    ),
                )
            )
        }
    )
    result = await resolve(
        damaged,
        trusted_input=bound.input,
        state=d.ConversationState(),
        user_id=USER,
        metadata=metadata,
    )
    assert isinstance(result, r.ResolutionFailure) and result.reason == "INVALID_INPUT"
    assert metadata.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value,expected", [(d.ReferenceSelector.LATEST, 3), (d.ReferenceSelector.OLDEST, 2)]
)
async def test_unique_recency(value: d.ReferenceSelector, expected: int) -> None:
    result = await run(selector(value), (file(3, date=DATE + timedelta(days=1)), file()))
    request = ready(result).requests[0]
    assert isinstance(request, r.ResolvedFileTargetRequest)
    assert request.action.file.file_id == UUID(int=expected)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "files,detail",
    [
        ((), "EMPTY_COLLECTION"),
        ((file(date=None),), "UNKNOWN_RECENCY"),
        ((file(), file(3, date=None)), "UNKNOWN_RECENCY"),
        ((file(), file(3)), "RECENCY_TIE"),
    ],
)
async def test_recency_ambiguity(files: tuple[r.IndexedFile, ...], detail: str) -> None:
    for value in d.ReferenceSelector:
        result = await run(selector(value), files)
        outcome = result.outcomes[0]
        assert isinstance(outcome, r.ClarificationRequirement) and outcome.detail == detail
        assert result.ready_bundle is None
    if len(files) == 2 and files[0].modified_at == files[1].modified_at:
        one = await run(selector(d.ReferenceSelector.LATEST), files)
        two = await run(selector(d.ReferenceSelector.LATEST), tuple(reversed(files)))
        assert one == two


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "capability,operation",
    [
        ("FILE_INVENTORY", "LIST"),
        ("FILE_INVENTORY", "COUNT"),
        ("COLLECTION_SUMMARY", "SUMMARIZE_EACH"),
    ],
)
async def test_default_collection_including_empty(capability: str, operation: str) -> None:
    for files in [(), (file(),)]:
        bundle = ready(await run(simple(capability, operation), files))
        req = bundle.requests[0]
        assert isinstance(req, (r.ResolvedInventoryRequest, r.ResolvedCollectionSummaryRequest))
        assert req.collection.files == files


@pytest.mark.asyncio
async def test_inventory_recency_carries_selected_file() -> None:
    result = await run(simple(operation="LATEST"), (file(),))
    request = ready(result).requests[0]
    assert isinstance(request, r.ResolvedInventoryRequest) and request.selected_file == file()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ids,detail",
    [
        ((), "NO_ACTIVE_FILE"),
        ((UUID(int=2), UUID(int=3)), "MULTIPLE_ACTIVE_FILES"),
        ((UUID(int=4),), "ACTIVE_FILE_UNAVAILABLE"),
    ],
)
async def test_context_file_failures(ids: tuple[UUID, ...], detail: str) -> None:
    result = await run(
        contextual(), (file(), file(3, "Other.txt")), d.ConversationState(active_file_ids=ids)
    )
    outcome = result.outcomes[0]
    assert isinstance(outcome, r.ClarificationRequirement) and outcome.detail == detail


@pytest.mark.asyncio
async def test_context_file_unique_and_topic_not_file_fallback() -> None:
    state = d.ConversationState(active_file_ids=(file().file_id,))
    assert ready(await run(contextual(), (file(),), state))
    result = await run(contextual(True), (), state)
    assert result.status == "NEEDS_CLARIFICATION"
    topic = d.ActiveTopic(original_question="Authentication?", answer_summary="Prior answer.")
    state = d.ConversationState(active_file_ids=(file().file_id,), active_topic=topic)
    request = ready(await run(contextual(True), (), state)).requests[0]
    assert isinstance(request, r.ResolvedGroundedRequest) and isinstance(
        request.query, r.ResolvedTopicQuery
    )
    assert request.query.topic == topic


@pytest.mark.asyncio
async def test_history_role_relative_index_and_unavailable() -> None:
    messages = (
        d.RecentMessage(role="user", text="First"),
        d.RecentMessage(role="assistant", text="Reply"),
        d.RecentMessage(role="user", text="Second"),
    )
    for role, position, text in [
        ("user", 1, "Second"),
        ("user", 2, "First"),
        ("assistant", 1, "Reply"),
        ("user", 3, None),
    ]:
        ref = d.MessageReference.model_validate({"role": role, "relative_position": position})
        request = d.ConversationHistoryRequest(
            input_span=d.InputSpan(start=0, end=10), candidate_id="c1", reference=ref
        )
        bound = d.BoundInterpretation(
            input=d.PreparedInput(
                question="Recall now",
                candidates=(
                    d.PriorMessageCandidate(
                        candidate_id="c1",
                        source=d.ContextHandle(handle="RECENT_MESSAGES"),
                        reference=ref,
                    ),
                ),
            ),
            interpretation=d.RequestedOperations(requests=(request,)),
        )
        result = await run(bound, state=d.ConversationState(recent_messages=messages))
        if text is None:
            assert result.status == "NEEDS_CLARIFICATION"
        else:
            resolved = ready(result).requests[0]
            assert isinstance(resolved, r.ResolvedHistoryRequest) and resolved.message.text == text


@pytest.mark.asyncio
async def test_compound_order_repeated_targets_and_blocking() -> None:
    text = "Summarize A.txt and B.txt"
    candidates = tuple(
        d.LiteralFileCandidate(
            candidate_id=f"c{i}",
            source=d.SourceLocation(start=text.index(name), end=text.index(name) + len(name)),
        )
        for i, name in enumerate(("A.txt", "B.txt"), 1)
    )
    requests = tuple(
        d.FileTargetRequest(
            input_span=d.InputSpan(start=0, end=len(text)),
            action=d.SummarizeFileRequest(target=d.LiteralMention(candidate_id=c.candidate_id)),
        )
        for c in candidates
    )
    third = d.FileInventoryRequest(
        operation="COUNT", input_span=d.InputSpan(start=0, end=len(text))
    )
    for bundle in [requests, requests + (third,)]:
        bound = d.BoundInterpretation(
            input=d.PreparedInput(question=text, candidates=candidates),
            interpretation=d.RequestedOperations(requests=bundle),
        )
        result = await run(bound, (file(name="A.txt"), file(3, "B.txt")))
        resolved = ready(result).requests
        assert [
            q.action.file.name for q in resolved if isinstance(q, r.ResolvedFileTargetRequest)
        ] == ["A.txt", "B.txt"]
        failed = await run(bound, (file(name="A.txt"),))
        assert isinstance(failed.outcomes[0], r.ReadyRequest)
        assert isinstance(failed.outcomes[1], r.ClarificationRequirement)
        assert failed.outcomes[1].request_id == 2 and failed.ready_bundle is None
        state = apply_success(d.ConversationState(), SuccessfulExecution(bundle=ready(result)))
        assert state.active_file_ids == (UUID(int=2), UUID(int=3))
        assert state.last_resolved_bundle == ready(result)


@pytest.mark.asyncio
async def test_state_file_grounded_chitchat_and_failure_preservation() -> None:
    initial = d.ConversationState()
    file_bundle = ready(await run(literal(), (file(),)))
    state = apply_success(initial, SuccessfulExecution(bundle=file_bundle))
    assert state.active_file_ids == (file().file_id,) and initial.active_file_ids == ()
    grounded = ready(await run(simple("GROUNDED_RAG", "ANSWER")))
    state = apply_success(
        state,
        SuccessfulExecution(
            bundle=grounded, topic_answers=(TopicAnswer(request_id=1, answer_summary="Summary."),)
        ),
    )
    assert state.active_topic is not None and state.active_topic.original_question == "A question"
    assert state.active_file_ids == ()
    chit = ready(await run(simple("CHITCHAT", "RESPOND")))
    later = apply_success(
        state, SuccessfulExecution(bundle=chit), messages=(d.RecentMessage(role="user", text="Hi"),)
    )
    assert (
        later.active_topic == state.active_topic
        and later.last_resolved_bundle == state.last_resolved_bundle
    )
    assert ready(await run(contextual(True), state=later))
    preserved = preserve_context(
        later, messages=(d.RecentMessage(role="assistant", text="Please clarify"),)
    )
    assert preserved.active_topic == later.active_topic
    assert preserved.last_successful_request_bundle == later.last_successful_request_bundle
    with pytest.raises(ValidationError):
        SuccessfulExecution(bundle=grounded)
    with pytest.raises(ValidationError):
        SuccessfulExecution(
            bundle=file_bundle,
            topic_answers=(TopicAnswer(request_id=1, answer_summary="Wrong capability"),),
        )


@pytest.mark.asyncio
async def test_multiple_topics_preserved_and_block_ambiguous_continuation() -> None:
    bound = simple("GROUNDED_RAG", "ANSWER")
    assert isinstance(bound.interpretation, d.RequestedOperations)
    source = d.BoundInterpretation(
        input=bound.input,
        interpretation=d.RequestedOperations(requests=bound.interpretation.requests * 2),
    )
    bundle = ready(await run(source))
    state = apply_success(
        d.ConversationState(),
        SuccessfulExecution(
            bundle=bundle,
            topic_answers=(
                TopicAnswer(request_id=1, answer_summary="One"),
                TopicAnswer(request_id=2, answer_summary="Two"),
            ),
        ),
    )
    assert len(state.active_topics) == 2 and state.active_topic is None
    assert (await run(contextual(True), state=state)).status == "NEEDS_CLARIFICATION"


@pytest.mark.asyncio
async def test_unsupported_ambiguity_lookup_failure_and_invalid_metadata() -> None:
    source = d.PreparedInput(question="Something else")
    span = d.InputSpan(start=0, end=14)
    bound = d.BoundInterpretation(
        input=source,
        interpretation=d.UnsupportedRequest(input_span=span, reason=d.UnsupportedReason.SCOPE),
    )
    assert (await run(bound)).status == "UNSUPPORTED"
    bundle = d.RequestedOperations(
        requests=(d.FileInventoryRequest(operation="LIST", input_span=span),)
    )
    bound = d.BoundInterpretation(
        input=source,
        interpretation=d.SemanticAmbiguity(
            input_span=span,
            alternatives=(
                bundle,
                d.RequestedOperations(requests=(d.ChitchatRequest(input_span=span),)),
            ),
        ),
    )
    assert (await run(bound)).status == "NEEDS_CLARIFICATION"
    bound = literal()
    result = await resolve(
        bound,
        trusted_input=bound.input,
        state=d.ConversationState(),
        user_id=USER,
        metadata=FakeMetadata(fail=True),
    )
    assert isinstance(result, r.ResolutionReport) and result.status == "FAILED"
    assert (
        isinstance(result.outcomes[0], r.FailedRequest)
        and result.outcomes[0].reason == "METADATA_UNAVAILABLE"
    )
    assert "secret" not in result.model_dump_json()
    other = file().model_copy(update={"user_id": UUID(int=9)})
    result = await resolve(
        bound,
        trusted_input=bound.input,
        state=d.ConversationState(),
        user_id=USER,
        metadata=FakeMetadata((other,)),
    )
    assert isinstance(result, r.ResolutionReport) and result.status == "FAILED"
    assert (
        isinstance(result.outcomes[0], r.FailedRequest)
        and result.outcomes[0].reason == "INVALID_METADATA"
    )
    with pytest.raises(ValidationError):
        r.ReadyRequest.model_validate({"request_id": 1})
    with pytest.raises(ValidationError):
        r.IndexedFile(
            file_id=UUID(int=2), user_id=USER, name="Name", modified_at=datetime(2026, 1, 1)
        )


def test_message_bounds_and_serialization() -> None:
    initial = RoutingConversationState()
    messages = tuple(d.RecentMessage(role="user", text=str(i) * 2000) for i in range(5))
    result = preserve_context(initial, messages=messages)
    assert len(result.recent_messages) == 3 and result.recent_messages[-1].text == "4" * 2000
    assert RoutingConversationState.model_validate_json(result.model_dump_json()) == result


@pytest.mark.asyncio
async def test_file_question_and_nonready_state() -> None:
    from app.routing.v2.state import apply_not_ready

    original = literal()
    assert isinstance(original.interpretation, d.RequestedOperations)
    summary = original.interpretation.requests[0]
    assert isinstance(summary, d.FileTargetRequest)
    question = d.FileTargetRequest(
        input_span=summary.input_span,
        action=d.FileQuestionRequest(
            target=summary.action.target, question_span=summary.input_span
        ),
    )
    bound = d.BoundInterpretation(
        input=original.input, interpretation=d.RequestedOperations(requests=(question,))
    )
    result = await run(bound, (file(),))
    resolved = ready(result).requests[0]
    assert isinstance(resolved, r.ResolvedFileTargetRequest) and isinstance(
        resolved.action, r.ResolvedFileQuestion
    )
    assert resolved.action.question == original.input.question
    state = apply_success(d.ConversationState(), SuccessfulExecution(bundle=ready(result)))
    unresolved = await run(contextual(), state=d.ConversationState())
    preserved = apply_not_ready(state, unresolved)
    assert preserved.active_file_ids == state.active_file_ids
    assert apply_not_ready(state, r.ResolutionFailure(reason="INVALID_INPUT")) == state
    with pytest.raises(ValueError):
        apply_not_ready(state, result)


@pytest.mark.asyncio
async def test_failed_metadata_blocks_bundle_and_keeps_unaffected_result() -> None:
    source = simple()
    assert isinstance(source.interpretation, d.RequestedOperations)
    chit = d.ChitchatRequest(input_span=d.InputSpan(start=0, end=10))
    bound = d.BoundInterpretation(
        input=source.input,
        interpretation=d.RequestedOperations(requests=source.interpretation.requests + (chit,)),
    )
    result = await resolve(
        bound,
        trusted_input=bound.input,
        state=d.ConversationState(),
        user_id=USER,
        metadata=FakeMetadata(fail=True),
    )
    assert isinstance(result, r.ResolutionReport) and result.status == "FAILED"
    assert isinstance(result.outcomes[0], r.FailedRequest)
    assert isinstance(result.outcomes[1], r.ReadyRequest)
    assert result.ready_bundle is None


@pytest.mark.asyncio
async def test_compound_file_topic_context_and_report_round_trip() -> None:
    original = literal()
    assert isinstance(original.interpretation, d.RequestedOperations)
    span = d.InputSpan(start=0, end=20)
    grounded = d.GroundedRagRequest(input_span=span, query=d.OriginalQuery(span=span))
    source = d.BoundInterpretation(
        input=original.input,
        interpretation=d.RequestedOperations(
            requests=original.interpretation.requests + (grounded,)
        ),
    )
    report = await run(source, (file(),))
    assert r.ResolutionReport.model_validate_json(report.model_dump_json()) == report
    state = apply_success(
        d.ConversationState(),
        SuccessfulExecution(
            bundle=ready(report),
            topic_answers=(TopicAnswer(request_id=2, answer_summary="A topic."),),
        ),
    )
    assert state.active_file_ids == (file().file_id,) and state.active_topic is not None
    assert ready(await run(contextual(), (file(),), state))
    assert ready(await run(contextual(True), state=state))
    assert len(state.last_resolved_bundle.requests) == 2 if state.last_resolved_bundle else False
    summary = ready(await run(simple("COLLECTION_SUMMARY", "SUMMARIZE_EACH"), (file(),)))
    after = apply_success(state, SuccessfulExecution(bundle=summary))
    assert after.active_file_ids == () and after.active_topic is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "requested,files,expected_id,detail",
    [
        ("REPORT.TXT", (file(),), 2, None),
        ("Report.txt", (file(), file(3, "report.txt")), 2, None),
        ("rEpOrT.TxT", (file(), file(3, "report.txt")), None, "DUPLICATE_FILENAME"),
        ("Cafe\u0301.pdf", (file(name="Café.pdf"),), 2, None),
        ("Café.pdf", (file(name="Cafe\u0301.pdf"),), 2, None),
        (
            "CAFÉ.PDF",
            (file(name="Café.pdf"), file(3, "Cafe\u0301.pdf")),
            None,
            "DUPLICATE_FILENAME",
        ),
        ("Straße.pdf", (file(name="STRASSE.pdf"),), 2, None),
        ("Report .txt", (file(),), None, "FILE_NOT_FOUND"),
        ("Report.pdf", (file(),), None, "FILE_NOT_FOUND"),
        ("Reprot.txt", (file(),), None, "FILE_NOT_FOUND"),
    ],
)
async def test_raw_then_unicode_canonical_exact_matching(
    requested: str, files: tuple[r.IndexedFile, ...], expected_id: int | None, detail: str | None
) -> None:
    bound = literal(requested)
    before = bound.model_dump_json()
    result = await run(bound, files)
    assert bound.model_dump_json() == before  # Resolution normalization never changes offsets.
    if expected_id is not None:
        request = ready(result).requests[0]
        assert isinstance(request, r.ResolvedFileTargetRequest)
        assert request.action.file.file_id == UUID(int=expected_id)
        assert request.action.file.name in {f.name for f in files}
    else:
        outcome = result.outcomes[0]
        assert isinstance(outcome, r.ClarificationRequirement) and outcome.detail == detail
        assert result.ready_bundle is None


@pytest.mark.asyncio
async def test_prepared_context_file_is_revalidated_after_disappearance() -> None:
    from app.routing.v2.preparation import prepare, PreparedEnvelope
    from app.routing.v2.options import generate_options, OptionRegistry, FileTargetSummarizeOption
    from app.routing.v2.questions import stage2_questions
    from app.routing.v2.providers.typesafe import parse_stage
    from app.routing.v2.translation import translate
    from tests.routing.test_v2_semantic_adapter import response

    state = d.ConversationState(active_file_ids=(file().file_id,))
    env = prepare("Summarize it", state)
    assert isinstance(env, PreparedEnvelope)
    options = generate_options(env)
    assert isinstance(options, OptionRegistry)
    selected = next(
        o
        for o in options.options
        if isinstance(o, FileTargetSummarizeOption)
        and isinstance(o.target_reference, d.ContextFileReference)
    )
    specs = stage2_questions(options, 1)
    semantic = translate(
        env,
        options,
        1,
        parse_stage(response(specs, {"REQUEST_1": selected.option_id}), specs, 2).answers,
    )
    assert semantic.interpretation is not None
    result = await run(semantic.interpretation, (), state)
    assert result.status == "NEEDS_CLARIFICATION" and result.ready_bundle is None
    outcome = result.outcomes[0]
    assert (
        isinstance(outcome, r.ClarificationRequirement)
        and outcome.detail == "ACTIVE_FILE_UNAVAILABLE"
    )
