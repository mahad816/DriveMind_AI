"""Direct TypeSafe mocked transport and cache isolation."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from pydantic_settings import SettingsConfigDict

from app.routing.providers.typesafe import TypeSafeJevRouter, TypeSafeSettings
from app.routing.providers.jev import serialize_state
from app.routing.providers.jev_criteria import questions
from app.routing.semantic import ObservationStatus, RoutingInput
from evaluation.typesafe_runner import cached_observations, identity, main
from evaluation.jev_runner import frozen_cases
from evaluation.routing_runner import DEFAULT_DATASET
from tests.evaluation.test_jev_shadow import response

KEY = "synthetic-typesafe-secret"


class IsolatedSettings(TypeSafeSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")


def settings() -> TypeSafeSettings:
    return IsolatedSettings(typesafe_api_key=SecretStr(KEY))


def native_response() -> dict[str, Any]:
    data = response()
    data["model"] = "jev-1.13.0"
    del data["model_version"]
    del data["latency_ms"]
    data["usage"] = {"input_tokens": 300, "output_tokens": 50}
    return data


@pytest.mark.asyncio
async def test_success_exact_payload_and_secret_exclusion() -> None:
    captured = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return httpx.Response(200, json=native_response())

    request = RoutingInput(question="List all files")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        obs = await TypeSafeJevRouter(settings(), client).route(request, idempotency_key="unused")
    assert obs.status == ObservationStatus.SUCCESS and obs.prediction
    assert obs.provider == "api.typesafe.ai" and obs.model == "jev-latest"
    assert obs.model_version == "jev-1.13.0" and obs.upstream_latency_ms is None
    assert obs.answers["has_file_inventory"].noul == 0.8
    assert obs.answers["mode"].confidence == 1
    payload = json.loads(captured[0].content)
    assert payload == {
        "model": "jev-latest",
        "state": serialize_state(request)[0],
        "questions": questions(),
    }
    assert str(captured[0].url) == "https://api.typesafe.ai/v1/systemone"
    assert "Idempotency-Key" not in captured[0].headers
    assert KEY not in obs.model_dump_json() and KEY not in repr(settings())
    assert KEY not in json.dumps(settings().model_dump(mode="json"))


@pytest.mark.parametrize(
    "defect",
    ["probability", "unknown", "confidence", "missing", "noul", "usage", "model", "malformed"],
)
@pytest.mark.asyncio
async def test_contract_errors(defect: str) -> None:
    data = native_response()
    if defect == "probability":
        data["answers"]["mode"]["probabilities"]["SINGLE"] = 0.3
    elif defect == "unknown":
        data["answers"]["mode"]["choice"] = "META"
    elif defect == "confidence":
        del data["answers"]["mode"]["confidence"]
    elif defect == "missing":
        del data["answers"]["mode"]
    elif defect == "noul":
        data["answers"]["has_chitchat"]["noul"] = 2
    elif defect == "usage":
        data["usage"]["input_tokens"] = True
    elif defect == "model":
        data["model"] = "jev-preview"
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda req: (
                httpx.Response(200, content=b"not-json")
                if defect == "malformed"
                else httpx.Response(200, json=data)
            )
        )
    ) as client:
        obs = await TypeSafeJevRouter(settings(), client).route(
            RoutingInput(question="Hello"), idempotency_key="unused"
        )
    assert obs.status == ObservationStatus.INVALID_RESPONSE and obs.prediction is None


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, "AUTH_ERROR"),
        (422, "INVALID_RESPONSE"),
        (429, "RATE_LIMITED"),
        (529, "UNAVAILABLE"),
        (500, "UNAVAILABLE"),
    ],
)
@pytest.mark.asyncio
async def test_status_handling_no_retry(status: int, expected: str) -> None:
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        return httpx.Response(status, json={"error": KEY})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        obs = await TypeSafeJevRouter(settings(), client).route(
            RoutingInput(question="Hello"), idempotency_key="unused"
        )
    assert obs.status.value == expected and len(calls) == 1
    assert KEY not in obs.model_dump_json()


@pytest.mark.asyncio
async def test_timeout_and_missing_key() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(KEY)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        obs = await TypeSafeJevRouter(settings(), client).route(
            RoutingInput(question="Hello"), idempotency_key="unused"
        )
        assert obs.status == ObservationStatus.TIMEOUT and KEY not in obs.model_dump_json()
        absent = IsolatedSettings(typesafe_api_key=SecretStr(""))
        obs = await TypeSafeJevRouter(absent, client).route(
            RoutingInput(question="Hello"), idempotency_key="unused"
        )
        assert obs.calls == 0 and obs.status == ObservationStatus.UNAVAILABLE


def test_provider_cache_isolation(tmp_path: Path) -> None:
    cases = frozen_cases(DEFAULT_DATASET)[:1]
    prior = json.loads(
        (Path(__file__).parent / "fixtures/jev_legacy_routing001_synthetic.json").read_text()
    )
    (tmp_path / "jev_shadow_smoke_prior.json").write_text(json.dumps(prior))
    assert cached_observations(tmp_path, cases, settings()) == {}
    assert identity(cases[0], settings())["provider"] == "api.typesafe.ai"
    # Even a renamed wrong-provider artifact cannot enter the direct cache.
    (tmp_path / "typesafe_shadow_smoke_prior.json").write_text(json.dumps(prior))
    assert cached_observations(tmp_path, cases, settings()) == {}


def test_safe_preflight_and_only_latest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TYPESAFE_API_KEY", KEY)

    async def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("No live test calls")

    monkeypatch.setattr(TypeSafeJevRouter, "route", forbidden)
    assert main(["--output-dir", str(tmp_path)]) == 0
    with pytest.raises(ValueError):
        IsolatedSettings(typesafe_model="jev-preview")


@pytest.mark.asyncio
async def test_exact_six_case_runner_and_persistent_direct_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from evaluation.typesafe_runner import run_smoke
    from evaluation.jev_runner import SMOKE_IDS

    async def no_sleep(delay: float) -> None:
        return None

    monkeypatch.setattr("evaluation.typesafe_runner.asyncio.sleep", no_sleep)
    cases = [c for c in frozen_cases(DEFAULT_DATASET) if c.id in SMOKE_IDS]
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        case = cases[len(calls)]
        calls.append(req)
        labels = tuple(f"{r.capability.value}:{r.operation.value}" for r in case.expected_requests)
        data = response(
            case.expected_mode.value,
            labels,
            case.expected_clarification_reason.value
            if case.expected_clarification_reason
            else "NONE",
        )
        data["model"] = "jev-1.13.0"
        data.pop("model_version")
        data.pop("latency_ms")
        data["usage"] = {"input_tokens": 300, "output_tokens": 50}
        return httpx.Response(200, json=data)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result, path = await run_smoke(settings(), tmp_path, TypeSafeJevRouter(settings(), client))
    assert len(calls) == 6 and result["case_count"] == 6
    assert [entry["id"] for entry in result["cases"]] == list(SMOKE_IDS)
    assert result["metrics"]["exact_decision_accuracy_labels_only"] == 1
    assert KEY not in path.read_text()

    def forbidden(req: httpx.Request) -> httpx.Response:
        raise AssertionError("Cached direct cases must not run again")

    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client:
        reused, _ = await run_smoke(settings(), tmp_path, TypeSafeJevRouter(settings(), client))
    assert reused["new_calls"] == 0 and reused["reused_observations"] == 6


def test_forged_wrong_provider_observation_ignored(tmp_path: Path) -> None:
    case = frozen_cases(DEFAULT_DATASET)[0]
    artifact = {
        "artifact_version": "typesafe-shadow-1.0",
        "cases": [
            {
                "id": case.id,
                "identity": identity(case, settings()),
                "observation": {"provider": "jev-ai.org", "http_status": 200},
            }
        ],
    }
    (tmp_path / "typesafe_shadow_smoke_wrong.json").write_text(json.dumps(artifact))
    assert not cached_observations(tmp_path, [case], settings())


@pytest.mark.asyncio
async def test_preserve_valid_fields_when_assembly_fails() -> None:
    data = native_response()
    data["answers"]["mode"] = response("CLARIFY", (), "NONE")["answers"]["mode"]
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=data))
    ) as client:
        obs = await TypeSafeJevRouter(settings(), client).route(
            RoutingInput(question="Ambiguous"), idempotency_key="unused"
        )
    assert obs.status == ObservationStatus.INVALID_RESPONSE
    assert obs.provenance["validation_stage"] == "assembly"
    assert obs.usage["input_tokens"] == 300
    assert obs.model_version == "jev-1.13.0" and obs.answers


@pytest.mark.parametrize(
    "usage",
    [{}, {"input_tokens": None, "output_tokens": None}, {"input_tokens": 0}, {"output_tokens": 0}],
)
@pytest.mark.asyncio
async def test_optional_nullable_usage_counts(usage: dict[str, Any]) -> None:
    data = native_response()
    data["usage"] = usage
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=data))
    ) as client:
        obs = await TypeSafeJevRouter(settings(), client).route(
            RoutingInput(question="Synthetic contract case"), idempotency_key="unused"
        )
    assert obs.status == ObservationStatus.SUCCESS
    assert obs.usage == {k: v for k, v in usage.items() if v is not None}


@pytest.mark.parametrize(
    ("edge", "code"),
    [
        ("body", "BODY_NOT_OBJECT"),
        ("model_missing", "MODEL_MISSING_OR_NULL"),
        ("model_null", "MODEL_MISSING_OR_NULL"),
        ("model_unexpected", "MODEL_UNEXPECTED"),
        ("answers_missing", "ANSWERS_MISSING_OR_NOT_OBJECT"),
        ("answer_ids", "ANSWER_IDS_MISMATCH"),
        ("type", "ANSWER_TYPE_INVALID"),
        ("noul", "PROBABILITY_OUT_OF_RANGE_OR_NONFINITE"),
        ("probability_string", "PROBABILITY_NOT_NUMERIC"),
        ("distribution", "DISTRIBUTION_NOT_NORMALIZED"),
        ("labels", "DISTRIBUTION_LABELS_INVALID"),
        ("selection", "CHOICE_UNKNOWN_OR_NOT_MAXIMUM"),
        ("confidence", "CHOICE_CONFIDENCE_MISSING"),
        ("confidence_null", "PROBABILITY_NOT_NUMERIC"),
        ("usage_missing", "USAGE_MISSING_OR_NOT_OBJECT"),
        ("usage_null", "USAGE_MISSING_OR_NOT_OBJECT"),
        ("usage_negative", "TOKEN_COUNT_INVALID"),
        ("assembly", "CLARIFICATION_REASON_REQUIRED"),
    ],
)
@pytest.mark.asyncio
async def test_synthetic_validation_edges_have_codes(edge: str, code: str) -> None:
    # Synthetic edge cases, NOT a reconstructed routing-101 response.
    data: Any = native_response()
    if edge == "body":
        data = []
    elif edge == "model_missing":
        del data["model"]
    elif edge == "model_null":
        data["model"] = None
    elif edge == "model_unexpected":
        data["model"] = "jev-99.0.0"
    elif edge == "answers_missing":
        del data["answers"]
    elif edge == "answer_ids":
        data["answers"]["unknown"] = {"type": "noul", "noul": 0.5}
    elif edge == "type":
        data["answers"]["has_chitchat"]["type"] = "choice"
    elif edge == "noul":
        data["answers"]["has_chitchat"]["noul"] = 2
    elif edge == "probability_string":
        data["answers"]["mode"]["probabilities"]["SINGLE"] = "1"
    elif edge == "distribution":
        data["answers"]["mode"]["probabilities"]["SINGLE"] = 0.5
    elif edge == "labels":
        data["answers"]["mode"]["probabilities"]["extra"] = 0
    elif edge == "selection":
        data["answers"]["mode"]["choice"] = "COMPOUND"
    elif edge == "confidence":
        del data["answers"]["mode"]["confidence"]
    elif edge == "confidence_null":
        data["answers"]["mode"]["confidence"] = None
    elif edge == "usage_missing":
        del data["usage"]
    elif edge == "usage_null":
        data["usage"] = None
    elif edge == "usage_negative":
        data["usage"]["input_tokens"] = -1
    else:
        data["answers"]["mode"] = response("CLARIFY", (), "NONE")["answers"]["mode"]
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=data))
    ) as client:
        obs = await TypeSafeJevRouter(settings(), client).route(
            RoutingInput(question="Synthetic edge"), idempotency_key="unused"
        )
    assert obs.status == ObservationStatus.INVALID_RESPONSE
    assert obs.provenance["validation_error_code"] == code
    assert "validation_stage" in obs.provenance
    assert "response_schema_summary" in obs.provenance


@pytest.mark.asyncio
async def test_alias_endpoint_integers_and_order() -> None:
    data = native_response()
    data["answers"] = dict(reversed(list(data["answers"].items())))
    for answer in data["answers"].values():
        if answer["type"] == "noul":
            answer["noul"] = 0
        else:
            answer["probabilities"] = {k: int(v) for k, v in answer["probabilities"].items()}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=data))
    ) as client:
        obs = await TypeSafeJevRouter(settings(), client).route(
            RoutingInput(question="Synthetic"), idempotency_key="unused"
        )
    assert obs.status == ObservationStatus.SUCCESS and obs.model_version == "jev-1.13.0"


@pytest.mark.asyncio
async def test_failure_snapshot_excludes_reflected_secret() -> None:
    data = native_response()
    data["Authorization"] = "Bearer " + KEY
    data["error"] = KEY
    data["answers"][KEY] = {"type": "noul", "noul": 0.5}
    data["answers"]["mode"]["choice"] = KEY
    data["usage"]["wallet"] = KEY
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=data))
    ) as client:
        obs = await TypeSafeJevRouter(settings(), client).route(
            RoutingInput(question="Synthetic"), idempotency_key="unused"
        )
    assert obs.status == ObservationStatus.INVALID_RESPONSE
    encoded = obs.model_dump_json()
    assert KEY not in encoded and "Authorization" not in encoded
    assert json.loads(obs.provenance["response_schema_summary"])["unknown_answer_count"] == 1


@pytest.mark.asyncio
async def test_malformed_json_has_fixed_diagnostic_code() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, content=KEY))
    ) as client:
        obs = await TypeSafeJevRouter(settings(), client).route(
            RoutingInput(question="Synthetic"), idempotency_key="unused"
        )
    assert obs.provenance["validation_stage"] == "json"
    assert obs.provenance["validation_error_code"] == "JSON_INVALID"
    assert KEY not in obs.model_dump_json()


@pytest.mark.asyncio
async def test_large_numeric_probability_cannot_break_diagnostic_retention() -> None:
    data = native_response()
    data["answers"]["has_chitchat"]["noul"] = 10**400
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=data))
    ) as client:
        obs = await TypeSafeJevRouter(settings(), client).route(
            RoutingInput(question="Synthetic"), idempotency_key="unused"
        )
    assert obs.status == ObservationStatus.INVALID_RESPONSE
    assert "validation_error_code" in obs.provenance
