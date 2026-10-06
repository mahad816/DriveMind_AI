"""Offline artifact reuse and mocked idempotency recovery; never live HTTP."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.routing.providers.jev import JevRouter
from app.routing.semantic import ObservationStatus, RoutingInput
from evaluation.jev_cache import find_reusable
from evaluation.jev_runner import execute, frozen_cases, write_artifact
from evaluation.routing_runner import DEFAULT_DATASET
from tests.evaluation.test_jev_shadow import KEY, response, settings

LEGACY = Path(__file__).parent / "fixtures/jev_legacy_routing001_synthetic.json"
REQUEST_ID = "dec_12345678"
STATUS_URL = "https://jev-ai.org/api/v1/requests/dec_12345678/"


def cache_fixture(tmp_path: Path, changes: dict[str, Any] | None = None) -> Path:
    raw = json.loads(LEGACY.read_text())
    raw.update(changes or {})
    path = tmp_path / "jev_shadow_smoke_legacy.json"
    path.write_text(json.dumps(raw))
    return path


@pytest.mark.asyncio
async def test_actual_legacy_reassembled_and_reused_zero_calls(tmp_path: Path) -> None:
    path = cache_fixture(tmp_path)
    before = path.read_bytes()
    cases = frozen_cases(DEFAULT_DATASET)[:1]
    cached = find_reusable(tmp_path, cases, settings())
    assert set(cached) == {"routing-001"}
    obs = cached["routing-001"]
    assert obs.status == ObservationStatus.SUCCESS and obs.prediction
    assert [
        (r.capability.value, r.operation.value if r.operation else None)
        for r in obs.prediction.requests
    ] == [("FILE_INVENTORY", "LIST")]
    assert obs.provenance["original_status"] == "INVALID_RESPONSE"
    assert obs.usage["input_tokens"] == 100 and obs.upstream_latency_ms == 25
    assert obs.latency_ms == pytest.approx(100.0)

    def forbidden(req: httpx.Request) -> httpx.Response:
        raise AssertionError("No HTTP allowed")

    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client:
        result = await execute(
            cases,
            settings(),
            stage="smoke",
            cache=cached,
            router=JevRouter(settings(), client),
            spacing_seconds=0,
        )
    assert result["post_attempts"] == result["new_model_decisions"] == result["new_calls"] == 0
    assert result["reused_artifact_observations"] == 1
    new_path = write_artifact(result, tmp_path)
    assert KEY not in new_path.read_text()
    assert path.read_bytes() == before
    assert find_reusable(tmp_path, cases, settings())["routing-001"].prediction == obs.prediction


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("criteria_hash", "other"),
        ("criteria_version", "other"),
        ("dataset_sha256", "other"),
        ("dataset_version", "other"),
        ("model", "jev-latest"),
        ("context_version", "other"),
        ("question_schema_version", "other"),
        ("base_url", "https://elsewhere.example/api/v1"),
    ],
)
def test_incompatible_artifact_ignored(tmp_path: Path, key: str, value: str) -> None:
    cache_fixture(tmp_path, {key: value})
    assert not find_reusable(tmp_path, frozen_cases(DEFAULT_DATASET)[:1], settings())


def test_bad_inputs_malformed_failures_ignored(tmp_path: Path) -> None:
    path = cache_fixture(tmp_path)
    raw = json.loads(path.read_text())
    raw["cases"][0]["gold"]["question"] = "Different question"
    path.write_text(json.dumps(raw))
    assert not find_reusable(tmp_path, frozen_cases(DEFAULT_DATASET)[:1], settings())
    path.write_text("not json")
    assert not find_reusable(tmp_path, frozen_cases(DEFAULT_DATASET)[:1], settings())
    raw = json.loads(LEGACY.read_text())
    raw["cases"][0]["jev"].update(http_status=409, answers={}, status="IDEMPOTENCY_CONFLICT")
    path.write_text(json.dumps(raw))
    assert not find_reusable(tmp_path, frozen_cases(DEFAULT_DATASET)[:1], settings())
    (tmp_path / "arbitrary.json").write_text(LEGACY.read_text())
    assert not find_reusable(tmp_path, frozen_cases(DEFAULT_DATASET)[:1], settings())


def conflict(code: str) -> dict[str, Any]:
    return {
        "error": {"code": code, "request_id": REQUEST_ID, "status_url": STATUS_URL, "message": KEY}
    }


@pytest.mark.parametrize("code", ["request_already_completed", "request_in_progress"])
@pytest.mark.asyncio
async def test_completed_and_in_progress_recovery_no_second_post(code: str) -> None:
    methods = []
    gets = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal gets
        methods.append(req.method)
        assert req.headers["Authorization"] == "Bearer " + KEY
        if req.method == "POST":
            return httpx.Response(409, json=conflict(code))
        assert str(req.url) == STATUS_URL
        gets += 1
        if code == "request_in_progress" and gets == 1:
            return httpx.Response(200, json={"status": "running"})
        data = response()
        data["id"] = REQUEST_ID
        return httpx.Response(200, json={"status": "completed", "result": data})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        obs = await JevRouter(settings(), client).route(
            RoutingInput(question="List all files"), idempotency_key="stable-offline-key"
        )
    assert methods.count("POST") == 1
    assert obs.status == ObservationStatus.SUCCESS and obs.recovered_idempotent
    assert obs.new_model_decisions == 0 and obs.post_attempts == 1
    assert obs.status_get_attempts == (2 if code == "request_in_progress" else 1)
    assert obs.request_id == REQUEST_ID and KEY not in obs.model_dump_json()


@pytest.mark.asyncio
async def test_body_mismatch_is_hard_failure_and_never_gets() -> None:
    methods = []

    def handler(req: httpx.Request) -> httpx.Response:
        methods.append(req.method)
        return httpx.Response(409, json=conflict("idempotency_key_reused"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await execute(
            frozen_cases(DEFAULT_DATASET)[:2],
            settings(),
            stage="smoke",
            router=JevRouter(settings(), client),
            spacing_seconds=0,
        )
    assert methods == ["POST"]
    assert result["stopped_reason"] == "idempotency_body_mismatch"
    assert result["new_calls"] == 0 and result["post_attempts"] == 1
    assert KEY not in json.dumps(result)


@pytest.mark.asyncio
async def test_unsafe_status_url_never_receives_key() -> None:
    methods = []

    def handler(req: httpx.Request) -> httpx.Response:
        methods.append(req.method)
        data = conflict("request_already_completed")
        data["error"]["status_url"] = "https://attacker.example/"
        return httpx.Response(409, json=data)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        obs = await JevRouter(settings(), client).route(
            RoutingInput(question="List files"), idempotency_key="offline-key"
        )
    assert methods == ["POST"] and obs.status == ObservationStatus.INVALID_RESPONSE


@pytest.mark.asyncio
async def test_pending_polling_is_bounded() -> None:
    methods = []

    def handler(req: httpx.Request) -> httpx.Response:
        methods.append(req.method)
        return (
            httpx.Response(409, json=conflict("request_in_progress"))
            if req.method == "POST"
            else httpx.Response(200, json={"status": "running"})
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        obs = await JevRouter(settings(), client).route(
            RoutingInput(question="List files"), idempotency_key="offline-key"
        )
    assert methods == ["POST", "GET", "GET", "GET"]
    assert obs.status == ObservationStatus.IDEMPOTENCY_CONFLICT and obs.new_model_decisions == 0
