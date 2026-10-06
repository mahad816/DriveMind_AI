"""Current-bundle dependency safety, entirely offline."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.routing.v2 import domain as d
from app.routing.v2 import options as o
from app.routing.v2.preparation import prepare, PreparedEnvelope
from app.routing.v2.resolver import resolve
from app.routing.v2.resolved import IndexedFile, ResolutionReport
from app.routing.v2.translation import translate
from app.routing.v2.observations import ChoiceObservation

USER = UUID(int=1)
OLD = UUID(int=2)


class Metadata:
    async def list_visible_indexed_files(self, user_id: UUID) -> tuple[IndexedFile, ...]:
        return tuple(
            IndexedFile(
                file_id=UUID(int=i),
                user_id=user_id,
                name=name,
                modified_at=datetime(2026, 1, i, tzinfo=UTC),
            )
            for i, name in [(2, "report.pdf"), (3, "A.pdf"), (4, "B.pdf")]
        )


def prepared(question: str) -> PreparedEnvelope:
    result = prepare(question)
    assert isinstance(result, PreparedEnvelope)
    return result


def bound(env: PreparedEnvelope, requests: tuple[d.SemanticRequest, ...]) -> d.BoundInterpretation:
    return d.BoundInterpretation(
        input=env.input, interpretation=d.RequestedOperations(requests=requests)
    )


def file_context(env: PreparedEnvelope) -> d.FileTargetRequest:
    c = next(c for c in env.input.candidates if isinstance(c, d.ContextFileCandidate))
    return d.FileTargetRequest(
        input_span=env.spans[0].span,
        action=d.SummarizeFileRequest(
            target=d.ContextFileReference(
                candidate_id=c.candidate_id, reference_kind=c.reference_kind
            )
        ),
    )


async def resolved(value: d.BoundInterpretation) -> ResolutionReport:
    report = await resolve(
        value,
        trusted_input=value.input,
        state=d.ConversationState(active_file_ids=(OLD,)),
        user_id=USER,
        metadata=Metadata(),
    )
    assert isinstance(report, ResolutionReport)
    return report


@pytest.mark.parametrize(
    "text",
    ["the first one", "the second result", "the file you just listed", "the result you just found"],
)
def test_runtime_extraction_and_no_context_overlap(text: str) -> None:
    env = prepared("List files and summarize " + text)
    runtime = [c for c in env.input.candidates if isinstance(c, d.RuntimeResultCandidate)]
    assert len(runtime) == 1
    for c in env.input.candidates:
        if isinstance(c, d.ContextFileCandidate) and isinstance(c.source, d.SourceLocation):
            assert not (
                c.source.start < runtime[0].source.end and runtime[0].source.start < c.source.end
            )
    registry = o.generate_options(env)
    assert isinstance(registry, o.OptionRegistry)
    option = next(x for x in registry.options if isinstance(x, o.RuntimeDependencyOption))
    answer = ChoiceObservation(
        answer_id="REQUEST_1",
        selected=option.option_id,
        probabilities=((option.option_id, 1.0),),
        confidence=1.0,
    )
    result = translate(env, registry, 1, (answer,))
    assert result.interpretation is not None
    assert isinstance(result.interpretation.interpretation, d.UnsupportedRequest)
    assert (
        result.interpretation.interpretation.reason
        == d.UnsupportedReason.RESULT_DEPENDENCY_UNSUPPORTED
    )


@pytest.mark.parametrize(
    "text",
    [
        "the first chapter",
        "the first section",
        "the second policy",
        "first",
        "second",
        "one",
        '"the first one"',
    ],
)
def test_ordinals_and_quoted_literals_are_not_dependencies(text: str) -> None:
    assert not any(
        isinstance(c, d.RuntimeResultCandidate)
        for c in prepared("Tell me about " + text).input.candidates
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("question", ["Summarize it.", "Summarize the previous file."])
async def test_single_context_unchanged(question: str) -> None:
    env = prepared(question)
    report = await resolved(bound(env, (file_context(env),)))
    assert report.status == "READY" and report.ready_bundle is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["LATEST", "OLDEST"])
async def test_recency_then_context_never_uses_old_file(operation: str) -> None:
    env = prepared("Find the latest file and summarize it.")
    first = d.FileInventoryRequest.model_validate(
        {"input_span": env.spans[0].span, "operation": operation}
    )
    report = await resolved(bound(env, (first, file_context(env))))
    assert report.status == "UNSUPPORTED" and report.ready_bundle is None
    assert (
        report.outcomes[1].model_dump()["reason"]
        == d.UnsupportedReason.RESULT_DEPENDENCY_UNSUPPORTED
    )
    assert "resolved" not in report.outcomes[1].model_dump()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    ["List files and summarize the first one.", "Show files and summarize the second result."],
)
async def test_runtime_ref_and_context_substitution_blocked(question: str) -> None:
    env = prepared(question)
    c = next(c for c in env.input.candidates if isinstance(c, d.RuntimeResultCandidate))
    direct = d.FileTargetRequest(
        input_span=env.spans[0].span,
        action=d.SummarizeFileRequest(target=d.RuntimeResultReference(candidate_id=c.candidate_id)),
    )
    for request in (direct, file_context(env)):
        report = await resolved(bound(env, (request,)))
        assert report.status == "UNSUPPORTED" and report.ready_bundle is None


@pytest.mark.asyncio
async def test_file_then_context_blocked_but_explicit_compounds_ready() -> None:
    env = prepared("Summarize A.pdf and summarize B.pdf")
    registry = o.generate_options(env)
    assert isinstance(registry, o.OptionRegistry)
    requests = tuple(
        o.semantic_request(env, x)
        for x in registry.options
        if isinstance(x, o.FileTargetSummarizeOption)
        and x.source_span_id == "S001"
        and isinstance(x.target_reference, d.LiteralMention)
    )
    assert len(requests) == 2
    assert all(isinstance(x, d.FileTargetRequest) for x in requests)
    explicit = tuple(x for x in requests if isinstance(x, d.FileTargetRequest))
    assert (await resolved(bound(env, explicit))).status == "READY"
    assert (await resolved(bound(env, (explicit[0], file_context(env))))).status == "UNSUPPORTED"
    inventory = d.FileInventoryRequest(input_span=env.spans[0].span, operation="LIST")
    assert (await resolved(bound(env, (inventory, explicit[0])))).status == "READY"


@pytest.mark.asyncio
async def test_grounded_then_context_topic_blocked() -> None:
    env = prepared("Explain authentication and elaborate on that")
    c = next(c for c in env.input.candidates if isinstance(c, d.ContextTopicCandidate))
    first = d.GroundedRagRequest(
        input_span=env.spans[0].span, query=d.OriginalQuery(span=env.spans[0].span)
    )
    second = d.GroundedRagRequest(
        input_span=env.spans[0].span, query=d.ContextTopicReference(candidate_id=c.candidate_id)
    )
    assert (await resolved(bound(env, (first, second)))).status == "UNSUPPORTED"


@pytest.mark.asyncio
async def test_runtime_without_context_never_looks_up_metadata() -> None:
    env = prepared("List files and summarize the first one")
    c = next(c for c in env.input.candidates if isinstance(c, d.RuntimeResultCandidate))
    request = d.FileTargetRequest(
        input_span=env.spans[0].span,
        action=d.SummarizeFileRequest(target=d.RuntimeResultReference(candidate_id=c.candidate_id)),
    )

    class NoLookup:
        async def list_visible_indexed_files(self, user_id: UUID) -> tuple[IndexedFile, ...]:
            raise AssertionError("runtime dependencies must not use metadata")

    value = bound(env, (request,))
    report = await resolve(
        value,
        trusted_input=env.input,
        state=d.ConversationState(),
        user_id=USER,
        metadata=NoLookup(),
    )
    assert isinstance(report, ResolutionReport) and report.status == "UNSUPPORTED"


@pytest.mark.asyncio
async def test_wrong_source_span_cannot_bypass_explicit_runtime_guard() -> None:
    env = prepared("List files and summarize the first one")
    request = file_context(env).model_copy(update={"input_span": d.InputSpan(start=0, end=10)})
    report = await resolved(
        bound(
            env, (d.FileInventoryRequest(input_span=env.spans[0].span, operation="LIST"), request)
        )
    )
    assert report.status == "UNSUPPORTED" and report.ready_bundle is None


@pytest.mark.asyncio
async def test_explicit_question_then_explicit_summary_remains_ready() -> None:
    env = prepared("Ask what A.pdf says about authentication and then summarize B.pdf.")
    literal = [c for c in env.input.candidates if isinstance(c, d.LiteralFileCandidate)]
    one = d.FileTargetRequest(
        input_span=env.spans[0].span,
        action=d.FileQuestionRequest(
            target=d.LiteralMention(candidate_id=literal[0].candidate_id),
            question_span=env.spans[0].span,
        ),
    )
    two = d.FileTargetRequest(
        input_span=env.spans[0].span,
        action=d.SummarizeFileRequest(
            target=d.LiteralMention(candidate_id=literal[1].candidate_id)
        ),
    )
    assert (await resolved(bound(env, (one, two)))).status == "READY"


@pytest.mark.asyncio
async def test_incompatible_output_kind_does_not_block_prior_file_context() -> None:
    env = prepared("Explain authentication and summarize the previous file")
    first = d.GroundedRagRequest(
        input_span=env.spans[0].span, query=d.OriginalQuery(span=env.spans[0].span)
    )
    assert (await resolved(bound(env, (first, file_context(env))))).status == "READY"


def test_runtime_reference_cannot_bind_to_context_candidate() -> None:
    from pydantic import ValidationError

    env = prepared("Summarize it")
    c = next(c for c in env.input.candidates if isinstance(c, d.ContextFileCandidate))
    request = d.FileTargetRequest(
        input_span=env.spans[0].span,
        action=d.SummarizeFileRequest(target=d.RuntimeResultReference(candidate_id=c.candidate_id)),
    )
    with pytest.raises(ValidationError):
        bound(env, (request,))
