"""Mock-only native provider and shadow runner verification."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from pydantic_settings import SettingsConfigDict

from app.routing.providers.jev import JevRouter, JevSettings, idempotency_key, serialize_state
from app.routing.providers.jev_criteria import questions
from app.routing.semantic import ObservationStatus, RoutingInput
from evaluation.jev_runner import (
    SMOKE_IDS,
    execute,
    frozen_cases,
    main,
    smoke_cache,
    write_artifact,
)
from evaluation.routing_runner import DEFAULT_DATASET

KEY = "synthetic-test-credential"


class IsolatedSettings(JevSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")


def settings() -> JevSettings:
    return IsolatedSettings(jev_api_key=SecretStr(KEY))


def response(
    mode: str = "SINGLE", slots: tuple[str, ...] = ("FILE_INVENTORY:LIST",), reason: str = "NONE"
) -> dict[str, Any]:
    answers: dict[str, Any] = {}
    labels = {
        "mode": mode,
        "clarification": reason,
        **{f"operation_{i + 1}": slots[i] if i < len(slots) else "NONE" for i in range(3)},
    }
    for name, spec in questions().items():
        if spec["type"] == "noul":
            answers[name] = {"type": "noul", "noul": 0.8}
        else:
            answers[name] = {
                "type": "choice",
                "choice": labels[name],
                "probabilities": {k: float(k == labels[name]) for k in spec["criteria"]},
                "confidence": 1,
            }
    return {
        "model": "jev-1.13",
        "model_version": "jev-1.13-20260917",
        "answers": answers,
        "usage": {
            "input_tokens": 200,
            "output_tokens": 30,
            "charged_tokens": 200,
            "charged_credits": 0,
            "wallet": "tokens",
        },
        "latency_ms": 10,
    }


@pytest.mark.asyncio
async def test_success_native_payload_and_secret_exclusion() -> None:
    captured = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return httpx.Response(200, json=response())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        obs = await JevRouter(settings(), client).route(
            RoutingInput(question="List files"), idempotency_key="test-key-000"
        )
    assert obs.status == ObservationStatus.SUCCESS
    assert obs.prediction and len(obs.prediction.requests) == 1
    assert obs.answers["has_file_inventory"].noul == 0.8
    assert captured[0].headers["Authorization"] == "Bearer " + KEY
    assert captured[0].headers["Idempotency-Key"] == "test-key-000"
    assert str(captured[0].url) == "https://jev-ai.org/api/v1/systemone/"
    assert len(json.loads(captured[0].content)["questions"]) == 11
    assert KEY not in obs.model_dump_json() and KEY not in repr(settings())
    assert KEY not in json.dumps(settings().model_dump(mode="json"))


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, "AUTH_ERROR"),
        (402, "BILLING_ERROR"),
        (422, "INVALID_RESPONSE"),
        (429, "RATE_LIMITED"),
        (500, "UNAVAILABLE"),
        (503, "UNAVAILABLE"),
        (504, "TIMEOUT"),
        (409, "IDEMPOTENCY_CONFLICT"),
        (308, "INVALID_RESPONSE"),
    ],
)
@pytest.mark.asyncio
async def test_http_errors_no_retry_or_body_leak(status: int, expected: str) -> None:
    calls = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            status, json={"error": {"message": KEY}}, headers={"Retry-After": "60"}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        obs = await JevRouter(settings(), client).route(
            RoutingInput(question="Hello"), idempotency_key="test-key-000"
        )
    assert obs.status.value == expected and calls == 1
    assert obs.prediction is None and KEY not in obs.model_dump_json()


@pytest.mark.parametrize(
    "defect",
    [
        "missing",
        "unknown",
        "negative",
        "nan",
        "sum",
        "noul",
        "usage",
        "model",
        "version",
        "type",
        "slots",
        "malformed",
    ],
)
@pytest.mark.asyncio
async def test_invalid_response(defect: str) -> None:
    data = response()
    if defect == "missing":
        del data["answers"]["mode"]
    elif defect == "unknown":
        data["answers"]["mode"]["choice"] = "META"
    elif defect in ("negative", "nan", "sum"):
        data["answers"]["mode"]["probabilities"]["SINGLE"] = (
            -0.1 if defect == "negative" else "NaN" if defect == "nan" else 0.5
        )
    elif defect == "noul":
        data["answers"]["has_chitchat"]["noul"] = True
    elif defect == "usage":
        data["usage"]["input_tokens"] = -1
    elif defect == "model":
        data["model"] = "jev-latest"
    elif defect == "version":
        data["model_version"] = KEY
    elif defect == "type":
        data["answers"]["mode"]["type"] = "score"
    elif defect == "slots":
        data = response("COMPOUND")

    def handler(req: httpx.Request) -> httpx.Response:
        return (
            httpx.Response(200, content=b"not-json")
            if defect == "malformed"
            else httpx.Response(200, json=data)
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        obs = await JevRouter(settings(), client).route(
            RoutingInput(question="Hello"), idempotency_key="test-key-000"
        )
    assert obs.status == ObservationStatus.INVALID_RESPONSE
    assert obs.prediction is None and KEY not in obs.model_dump_json()


@pytest.mark.parametrize("error", [httpx.ReadTimeout, httpx.ConnectError])
@pytest.mark.asyncio
async def test_transport_and_absent_key(error: type[httpx.TransportError]) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise error(KEY)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        obs = await JevRouter(settings(), client).route(
            RoutingInput(question="Hello"), idempotency_key="test-key-000"
        )
        assert obs.status == (
            ObservationStatus.TIMEOUT
            if error == httpx.ReadTimeout
            else ObservationStatus.UNAVAILABLE
        )
        assert KEY not in obs.model_dump_json()
        absent = IsolatedSettings(jev_api_key=SecretStr(""))
        assert (
            await JevRouter(absent, client).route(
                RoutingInput(question="Hello"), idempotency_key="test-key-000"
            )
        ).calls == 0


def test_history_idempotency_and_freeze(tmp_path: Path) -> None:
    request = RoutingInput(
        question="Summarize it",
        history=tuple({"role": "assistant", "text": "x" * 4000} for _ in range(8)),
        history_window_complete=True,
    )
    state, truncated = serialize_state(request)
    assert sum(len(t["text"]) for t in state["RECENT CONVERSATION CONTEXT"]) == 6000
    assert truncated and not state["history_window_complete"]
    first = idempotency_key("v1", "case", "jev-1.13", request)
    assert first == idempotency_key("v1", "case", "jev-1.13", request)
    assert first != idempotency_key("v2", "case", "jev-1.13", request)
    assert len(frozen_cases(DEFAULT_DATASET)) == 120
    changed = tmp_path / "changed.json"
    changed.write_text(DEFAULT_DATASET.read_text() + " ")
    with pytest.raises(ValueError, match="hash"):
        frozen_cases(changed)


def test_runner_flags_zero_calls(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("JEV_API_KEY", KEY)

    async def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Network forbidden")

    monkeypatch.setattr(JevRouter, "route", forbidden)
    assert main(["--limit", "5"]) == 0
    assert main(["--stage", "full", "--execute-jev"]) == 2
    assert KEY not in capsys.readouterr().out


@pytest.mark.asyncio
async def test_compound_clarify_scores_and_smoke_reuse(tmp_path: Path) -> None:
    cases = [c for c in frozen_cases(DEFAULT_DATASET) if c.id in SMOKE_IDS]
    index = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal index
        case = cases[index]
        index += 1
        labels = tuple(f"{r.capability.value}:{r.operation.value}" for r in case.expected_requests)
        return httpx.Response(
            200,
            json=response(
                case.expected_mode.value,
                labels,
                case.expected_clarification_reason.value
                if case.expected_clarification_reason
                else "NONE",
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await execute(
            cases,
            settings(),
            stage="smoke",
            router=JevRouter(settings(), client),
            spacing_seconds=0,
        )
    assert result["jev_metrics"]["exact_decision_accuracy_labels_only"] == 1
    assert result["jev_metrics"]["compound_omission_rate"] == 0
    assert result["jev_metrics"]["clarification_miss_rate"] == 0
    path = write_artifact(result, tmp_path)
    cached = smoke_cache(path, settings())
    reused = await execute(cases, settings(), stage="full", cache=cached, spacing_seconds=0)
    assert reused["new_calls"] == 0 and reused["reused_observations"] == 6
    assert KEY not in path.read_text()


@pytest.mark.asyncio
async def test_failure_stops_runner() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(422))
    ) as client:
        result = await execute(
            frozen_cases(DEFAULT_DATASET)[:2],
            settings(),
            stage="smoke",
            router=JevRouter(settings(), client),
            spacing_seconds=0,
        )
    assert result["post_attempts"] == 1 and result["new_calls"] == 0
    assert result["stopped_reason"] is not None
    assert result["jev_metrics"]["single_six_route_accuracy"] == 0


def test_question_limits_and_pinned_config() -> None:
    assert len(questions()) <= 20
    for spec in questions().values():
        assert len(spec["instructions"]) <= 1000
        if spec["type"] == "choice":
            assert 2 <= len(spec["criteria"]) <= 24
    with pytest.raises(ValueError):
        IsolatedSettings(jev_model="jev-latest")
    with pytest.raises(ValueError):
        IsolatedSettings(jev_base_url="https://user:secret@example.com")


@pytest.mark.asyncio
async def test_duplicate_capability_slots_not_collapsed() -> None:
    cases = [c for c in frozen_cases(DEFAULT_DATASET) if c.id == "routing-084"]
    data = response("COMPOUND", ("FILE_TARGET:SUMMARIZE", "FILE_TARGET:SUMMARIZE"))
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=data))
    ) as client:
        result = await execute(
            cases,
            settings(),
            stage="smoke",
            router=JevRouter(settings(), client),
            spacing_seconds=0,
        )
    assert result["jev_metrics"]["compound_omission_rate"] == 0
    assert result["jev_metrics"]["exact_decision_accuracy_labels_only"] == 1
    assert result["jev_metrics"]["choice_calibration"]["mode"]["multiclass_brier"] == 0


def test_absent_key_flag_and_invalid_smoke(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("JEV_API_KEY", " ")
    assert main(["--execute-jev"]) == 2
    bad = tmp_path / "smoke.json"
    bad.write_text("{}")
    with pytest.raises(ValueError):
        smoke_cache(bad, settings())


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 2, True, "0.5", None])
def test_nonfinite_or_invalid_probability(value: Any) -> None:
    from app.routing.providers.jev import probability

    with pytest.raises(ValueError):
        probability(value)


@pytest.mark.asyncio
async def test_sanitized_live_single_response_regression() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures/jev_list_all_files_synthetic.json").read_text()
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=fixture["response"]))
    ) as client:
        observation = await JevRouter(settings(), client).route(
            RoutingInput(question=fixture["question"]), idempotency_key="offline-replay-only"
        )
    assert observation.status == ObservationStatus.SUCCESS
    prediction = observation.prediction
    assert prediction and prediction.mode.value == "SINGLE"
    assert [
        (r.capability.value, r.operation.value if r.operation else None)
        for r in prediction.requests
    ] == [("FILE_INVENTORY", "LIST")]
    assert prediction.clarification_reason is None
    assert observation.answers["operation_3"].probabilities["FILE_INVENTORY:LIST"] == 0.66
    assert observation.answers["clarification"].probabilities["MISSING_SCOPE"] == 0.59
    assert observation.assembly_diagnostics is not None
    assert observation.assembly_diagnostics.relevant_answer_ids == ("mode", "operation_1")
    assert "operation_3_nonempty_when_single" in observation.assembly_diagnostics.disagreement_flags
    assert (
        "clarification_non_none_when_executable"
        in observation.assembly_diagnostics.disagreement_flags
    )
    assert observation.usage["input_tokens"] == 100
    assert observation.usage["output_tokens"] == 20
    assert observation.usage["charged_credits"] == 1
    assert observation.upstream_latency_ms == 25


@pytest.mark.parametrize(
    ("mode", "slots", "reason", "expected_size"),
    [
        ("SINGLE", ("FILE_INVENTORY:LIST", "NONE", "GROUNDED_RAG:ANSWER"), "MISSING_SCOPE", 1),
        ("COMPOUND", ("FILE_TARGET:SUMMARIZE", "FILE_TARGET:SUMMARIZE"), "MISSING_SCOPE", 2),
        (
            "COMPOUND",
            ("FILE_TARGET:SUMMARIZE", "FILE_TARGET:SUMMARIZE", "FILE_INVENTORY:COUNT"),
            "NONE",
            3,
        ),
        (
            "CLARIFY",
            ("FILE_INVENTORY:LIST", "NONE", "FILE_TARGET:SUMMARIZE"),
            "MISSING_ARGUMENT",
            0,
        ),
    ],
)
@pytest.mark.asyncio
async def test_mode_gates_auxiliary_disagreements(
    mode: str, slots: tuple[str, ...], reason: str, expected_size: int
) -> None:
    data = response(mode, slots, reason)
    data["answers"]["has_grounded_rag"]["noul"] = 0.68
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=data))
    ) as client:
        obs = await JevRouter(settings(), client).route(
            RoutingInput(question="Offline fixture"), idempotency_key="offline-test"
        )
    assert obs.status == ObservationStatus.SUCCESS and obs.prediction
    assert len(obs.prediction.requests) == expected_size
    assert obs.assembly_diagnostics
    assert obs.answers["has_grounded_rag"].noul == 0.68


@pytest.mark.parametrize(
    ("mode", "slots", "reason"),
    [
        ("SINGLE", (), "NONE"),
        ("COMPOUND", ("FILE_TARGET:SUMMARIZE",), "NONE"),
        ("COMPOUND", ("NONE", "FILE_TARGET:SUMMARIZE", "FILE_TARGET:SUMMARIZE"), "NONE"),
        ("CLARIFY", (), "NONE"),
    ],
)
@pytest.mark.asyncio
async def test_required_mode_fields_still_fail(
    mode: str, slots: tuple[str, ...], reason: str
) -> None:
    data = response(mode, slots, reason)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=data))
    ) as client:
        obs = await JevRouter(settings(), client).route(
            RoutingInput(question="Offline fixture"), idempotency_key="offline-test"
        )
    assert obs.status == ObservationStatus.INVALID_RESPONSE and obs.prediction is None


@pytest.mark.parametrize(
    ("statuses", "versions", "reason"),
    [
        ((200,), ("jev-1.13-20260917",), "invalid_response"),
        ((503,), ("jev-1.13-20260917",), "provider_failure"),
        ((200, 200), ("jev-1.13-20260917", "jev-1.13-20260918"), "model_drift"),
    ],
)
@pytest.mark.asyncio
async def test_distinct_stop_reasons(
    statuses: tuple[int, ...], versions: tuple[str, ...], reason: str
) -> None:
    index = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal index
        status, version = statuses[index], versions[index]
        index += 1
        data = response("COMPOUND") if reason == "invalid_response" else response()
        data["model_version"] = version
        return httpx.Response(status, json=data)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await execute(
            frozen_cases(DEFAULT_DATASET)[:2],
            settings(),
            stage="smoke",
            router=JevRouter(settings(), client),
            spacing_seconds=0,
        )
    assert result["stopped_reason"] == reason
