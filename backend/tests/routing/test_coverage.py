"""Coverage gate serializer and native provider tests; mocked HTTP only."""

import json
from typing import Any
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr, ValidationError
from pydantic_settings import SettingsConfigDict

from app.routing.providers.typesafe import TypeSafeSettings
from app.routing.v2 import domain as d
from app.routing.v2.coverage import (
    CoverageVerdict,
    context_from_state,
    serialize_interpretation,
    CoverageInput,
    RuntimeReference,
)
from app.routing.v2.coverage.contracts import contract_identity, verify_lock
from app.routing.v2.coverage.criteria import questions
from app.routing.v2.coverage.providers.typesafe_coverage import (
    TypeSafeCoverageVerifier,
    parse_response,
)
from app.routing.v2.preparation import prepare, PreparedEnvelope


class Settings(TypeSafeSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")


def settings(key: str = "fake-unit-key") -> TypeSafeSettings:
    return Settings(typesafe_api_key=SecretStr(key))


def bound(
    question: str = "Summarize receipt_log.pdf.", kind: str = "literal"
) -> d.BoundInterpretation:
    env = prepare(question)
    assert isinstance(env, PreparedEnvelope)
    span = env.spans[0].span
    if kind == "literal":
        c = next(c for c in env.input.candidates if isinstance(c, d.LiteralFileCandidate))
        ref: d.FileReference = d.LiteralMention(candidate_id=c.candidate_id)
    elif kind == "runtime":
        c = next(c for c in env.input.candidates if isinstance(c, d.RuntimeResultCandidate))
        ref = d.RuntimeResultReference(candidate_id=c.candidate_id)
    else:
        c = next(c for c in env.input.candidates if isinstance(c, d.ContextFileCandidate))
        ref = d.ContextFileReference(candidate_id=c.candidate_id, reference_kind=c.reference_kind)
    return d.BoundInterpretation(
        input=env.input,
        interpretation=d.RequestedOperations(
            requests=(
                d.FileTargetRequest(input_span=span, action=d.SummarizeFileRequest(target=ref)),
            )
        ),
    )


def response(
    selected: str = "PRESERVED", probabilities: dict[str, float] | None = None
) -> dict[str, Any]:
    return {
        "model": "jev-1.13.0",
        "usage": {"input_tokens": 50, "output_tokens": 8},
        "answers": {
            "COVERAGE": {
                "type": "choice",
                "choice": selected,
                "confidence": 0.9,
                "probabilities": probabilities
                or {"PRESERVED": 0.95, "MISMATCH": 0.03, "UNCERTAIN": 0.02},
            }
        },
    }


def test_serialization_stable_current_literal_only() -> None:
    value = bound("Summarize Cafe\u0301_receipt.pdf.")
    one = serialize_interpretation(value)
    two = serialize_interpretation(value)
    assert one == two and CoverageInput.model_validate_json(one.model_dump_json()) == one
    reference = one.interpretation.requests[0].reference
    assert reference.model_dump()["current_input_filename"] == "Cafe\u0301_receipt.pdf"
    data = json.loads(one.model_dump_json())
    data["interpretation"]["requests"][0]["reference"]["current_input_filename"] = "invented.pdf"
    with pytest.raises(ValidationError):
        CoverageInput.model_validate(data)


def test_serializer_privacy() -> None:
    state = d.ConversationState(
        active_file_ids=(UUID(int=777),),
        active_topic=d.ActiveTopic(
            original_question="PRIVATE historical_name.pdf", answer_summary="PRIVATE answer"
        ),
        recent_messages=(d.RecentMessage(role="assistant", text="private-past-filename.pdf"),),
    )
    value = serialize_interpretation(bound("Summarize it.", "context"), state)
    payload = json.dumps(value.provider_state())
    assert "PRIOR_CONVERSATION_FILE_REFERENCE" in payload
    for secret in [
        str(UUID(int=777)),
        "historical_name.pdf",
        "private-past-filename.pdf",
        "PRIVATE answer",
        "snapshot_identity",
    ]:
        assert secret not in payload
    assert value.context.prior_file_count == 1
    changed = state.model_copy(update={"active_file_ids": (UUID(int=778),)})
    assert (
        serialize_interpretation(bound("Summarize it.", "context"), changed).input_identity
        != value.input_identity
    )


def test_runtime_reference_is_non_executable() -> None:
    value = serialize_interpretation(bound("List items and summarize the first one.", "runtime"))
    assert isinstance(value.interpretation.requests[0].reference, RuntimeReference)
    assert value.interpretation.disposition == "NON_EXECUTABLE"


def test_collection_scope_and_history() -> None:
    inp = d.PreparedInput(question="Count only documents in the Legal folder.")
    span = d.InputSpan(start=0, end=len(inp.question))
    value = serialize_interpretation(
        d.BoundInterpretation(
            input=inp,
            interpretation=d.RequestedOperations(
                requests=(d.FileInventoryRequest(input_span=span, operation="COUNT"),)
            ),
        )
    )
    data = value.provider_state()["PROPOSED_OPERATIONAL_INTERPRETATION"]
    assert isinstance(data, dict)
    assert (
        data["requests"][0]["scope"] == "ALL_VISIBLE_INDEXED_FILES"
        and data["requests"][0]["filter"] == "NONE"
    )
    assert "Legal" in data["requests"][0]["source_text_provenance_only"]
    env = prepare("Repeat the last assistant answer.")
    assert isinstance(env, PreparedEnvelope)
    c = next(
        c
        for c in env.input.candidates
        if isinstance(c, d.PriorMessageCandidate) and c.reference.role == "assistant"
    )
    req = d.ConversationHistoryRequest(
        input_span=env.spans[0].span, candidate_id=c.candidate_id, reference=c.reference
    )
    history = serialize_interpretation(
        d.BoundInterpretation(
            input=env.input, interpretation=d.RequestedOperations(requests=(req,))
        )
    )
    assert history.interpretation.requests[0].reference.model_dump() == {
        "kind": "HISTORY_REFERENCE",
        "role": "assistant",
        "relative_position": 1,
    }


def test_context_descriptors_are_bounded() -> None:
    with pytest.raises(ValidationError):
        context_from_state(
            d.ConversationState.model_construct(
                active_file_ids=tuple(UUID(int=i) for i in range(4)),
                active_topic=None,
                recent_messages=(),
                last_substantive_request=None,
                last_successful_request_bundle=None,
            )
        )


def test_exact_one_choice_three_labels() -> None:
    specs = questions()
    assert set(specs) == {"COVERAGE"}
    assert specs["COVERAGE"]["type"] == "choice"
    assert set(specs["COVERAGE"]["criteria"]) == {"PRESERVED", "MISMATCH", "UNCERTAIN"}  # type: ignore[arg-type]
    assert verify_lock()


@pytest.mark.parametrize("verdict", ["PRESERVED", "MISMATCH", "UNCERTAIN"])
@pytest.mark.asyncio
async def test_mocked_native_verdict_and_fail_closed(verdict: str) -> None:
    calls = []

    def mock(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "jev-latest"
        assert set(payload["questions"]) == {"COVERAGE"}
        assert request.url == httpx.URL("https://api.typesafe.ai/v1/systemone")
        calls.append(request)
        probs = {k: float(k == verdict) for k in ("PRESERVED", "MISMATCH", "UNCERTAIN")}
        return httpx.Response(200, json=response(verdict, probs))

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        result = await TypeSafeCoverageVerifier(settings(), client).verify(
            serialize_interpretation(bound()), execute=True
        )
    assert result.verdict == CoverageVerdict(verdict)
    assert result.permits_resolution == (verdict == "PRESERVED")
    assert result.observation.selected_probability == 1 and result.observation.top_two_margin == 1
    assert len(calls) == 1 and "fake-unit-key" not in result.model_dump_json()


@pytest.mark.parametrize(
    "mutation",
    [
        "nan",
        "inf",
        "out_of_range",
        "sum",
        "argmax",
        "missing_label",
        "unknown_label",
        "missing_answer",
        "extra_answer",
        "unknown_choice",
        "model",
        "model_object",
        "usage",
        "confidence",
        "type",
    ],
)
def test_malformed_responses_rejected(mutation: str) -> None:
    data = response()
    ans = data["answers"]["COVERAGE"]
    if mutation in ("nan", "inf", "out_of_range"):
        ans["probabilities"]["PRESERVED"] = {
            "nan": float("nan"),
            "inf": float("inf"),
            "out_of_range": 1.2,
        }[mutation]
    elif mutation == "sum":
        ans["probabilities"] = {k: 0.2 for k in ans["probabilities"]}
    elif mutation == "argmax":
        ans["choice"] = "MISMATCH"
    elif mutation == "missing_label":
        del ans["probabilities"]["UNCERTAIN"]
    elif mutation == "unknown_label":
        ans["probabilities"]["OTHER"] = 0
    elif mutation == "missing_answer":
        data["answers"] = {}
    elif mutation == "extra_answer":
        data["answers"]["REPAIR"] = ans
    elif mutation == "unknown_choice":
        ans["choice"] = "pick_new_route"
    elif mutation == "model":
        data["model"] = "jev-preview"
    elif mutation == "model_object":
        data["model"] = {}
    elif mutation == "usage":
        data["usage"]["input_tokens"] = -2
    elif mutation == "confidence":
        ans["confidence"] = True
    else:
        ans["type"] = "noul"
    observation = parse_response(data, identity=contract_identity())
    assert (
        observation.status == "INVALID_RESPONSE"
        and observation.selected is None
        and not observation.probabilities
    )


def test_rounding_aware_distribution_and_alias() -> None:
    observation = parse_response(
        response(probabilities={"PRESERVED": 0.33, "MISMATCH": 0.33, "UNCERTAIN": 0.33}),
        identity=contract_identity(),
    )
    assert observation.status == "SUCCESS" and observation.returned_model == "jev-1.13.0"
    data = response()
    data["usage"] = {"input_tokens": None}
    assert parse_response(data, identity=contract_identity()).status == "SUCCESS"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 422, 429, 500, 529])
async def test_http_failure_no_retry(status: int) -> None:
    calls = []

    def mock(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status, text="private error body fake-unit-key")

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        result = await TypeSafeCoverageVerifier(settings(), client).verify(
            serialize_interpretation(bound()), execute=True
        )
    assert not result.permits_resolution and result.verdict is None and len(calls) == 1
    assert (
        "private error body" not in result.model_dump_json()
        and "fake-unit-key" not in result.model_dump_json()
    )


@pytest.mark.asyncio
async def test_timeout_no_retry_and_default_zero_calls() -> None:
    calls = []

    def mock(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ReadTimeout("private error", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        verifier = TypeSafeCoverageVerifier(settings(), client)
        inp = serialize_interpretation(bound())
        dry = await verifier.verify(inp)
        assert dry.observation.status == "NOT_EXECUTED" and not calls
        timeout = await verifier.verify(inp, execute=True)
        assert (
            timeout.observation.error_code == "TIMEOUT"
            and len(calls) == 1
            and not timeout.permits_resolution
        )
        no_key = await TypeSafeCoverageVerifier(settings(""), client).verify(inp, execute=True)
        assert no_key.observation.error_code == "MISSING_KEY" and len(calls) == 1


@pytest.mark.asyncio
async def test_input_identity_mismatch_is_zero_call() -> None:
    inp = serialize_interpretation(bound()).model_copy(update={"input_identity": "0" * 64})
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: pytest.fail("POST"))
    ) as client:
        result = await TypeSafeCoverageVerifier(settings(), client).verify(inp, execute=True)
    assert (
        not result.permits_resolution and result.observation.error_code == "INPUT_IDENTITY_MISMATCH"
    )


@pytest.mark.asyncio
async def test_complete_mixed_unsupported_selection_and_context_identity() -> None:
    from app.routing.v2.providers.typesafe import TypeSafeV2Router
    from app.routing.v2.options import generate_options, OptionRegistry, InventoryCountOption
    from app.routing.v2.coverage import serialize_routing_result

    question = "Count the documents and rename dated_memo.txt."
    env = prepare(question)
    assert isinstance(env, PreparedEnvelope)
    registry = generate_options(env)
    assert isinstance(registry, OptionRegistry)
    count = next(o.option_id for o in registry.options if isinstance(o, InventoryCountOption))

    def mock(request: httpx.Request) -> httpx.Response:
        specs = json.loads(request.content)["questions"]
        chosen = (
            {"STRUCTURE": "TWO"}
            if "STRUCTURE" in specs
            else {"REQUEST_1": count, "REQUEST_2": "UNSUPPORTED_OPERATION"}
        )
        return httpx.Response(
            200,
            json={
                "model": "jev-1.13.0",
                "usage": {"input_tokens": 50, "output_tokens": 8},
                "answers": {
                    name: {
                        "type": "choice",
                        "choice": chosen[name],
                        "confidence": 1,
                        "probabilities": {k: float(k == chosen[name]) for k in spec["criteria"]},
                    }
                    for name, spec in specs.items()
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        routed = await TypeSafeV2Router(settings(), client).interpret(env, execute=True)
    value = serialize_routing_result(env, registry, routed)
    assert value.interpretation.disposition == "NON_EXECUTABLE"
    assert value.interpretation.requests[0].operation == "COUNT"
    assert value.interpretation.special_selections[0].position == 2
    with pytest.raises(ValueError, match="context identity"):
        serialize_routing_result(
            env, registry, routed, d.ConversationState(active_file_ids=(UUID(int=77),))
        )


def test_unsupported_requires_supplied_original_cardinality() -> None:
    source = d.PreparedInput(question="Rename sample_note.txt.")
    value = d.BoundInterpretation(
        input=source,
        interpretation=d.UnsupportedRequest(
            reason=d.UnsupportedReason.OPERATION,
            input_span=d.InputSpan(start=0, end=len(source.question)),
        ),
    )
    with pytest.raises(ValueError, match="original cardinality"):
        serialize_interpretation(value)


def test_topic_reference_privacy() -> None:
    env = prepare("Discuss that topic further.")
    assert isinstance(env, PreparedEnvelope)
    c = next(c for c in env.input.candidates if isinstance(c, d.ContextTopicCandidate))
    request = d.GroundedRagRequest(
        input_span=env.spans[0].span, query=d.ContextTopicReference(candidate_id=c.candidate_id)
    )
    value = serialize_interpretation(
        d.BoundInterpretation(
            input=env.input, interpretation=d.RequestedOperations(requests=(request,))
        ),
        d.ConversationState(
            active_topic=d.ActiveTopic(
                original_question="hidden_topic.pdf private", answer_summary="private answer"
            )
        ),
    )
    assert value.interpretation.requests[0].reference.kind == "PRIOR_CONVERSATION_TOPIC_REFERENCE"
    assert "hidden_topic.pdf" not in json.dumps(value.provider_state())
