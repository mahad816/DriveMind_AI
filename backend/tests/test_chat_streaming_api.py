"""Mounted SSE route, real Origin/CSRF dependency orchestration, no external IO."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.conversations import router, get_conversation_chat_service
from app.api.paid_question import get_paid_question_quota
from tests.paid_quota_fakes import AdmitAllQuota
from app.api.session_dependencies import get_application_session_service
from app.core.config import Settings, get_settings
from app.schemas.conversation import ConversationSubmission
from app.security.session_helpers import InvalidApplicationSession, InvalidSessionRequest
from app.services.chat_stream import emit


DTO = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "frontend/lib/api/fixtures/conversation-backend-dto.json"
    ).read_text()
)
CID = DTO["metadata"]["id"]
BODY = {
    "client_request_id": DTO["submission"]["turn"]["client_request_id"],
    "question": DTO["submission"]["turn"]["question"],
    "expected_content_version": 0,
}


@pytest.fixture
def mounted():
    settings = Settings(
        _env_file=None,
        app_env="development",
        chat_streaming_enabled=True,
        tool_rag_agent_enabled=True,
        frontend_url="http://localhost:3440",
    )
    session = SimpleNamespace(
        settings=settings,
        resolve_principal=AsyncMock(return_value=SimpleNamespace()),
        verify_csrf=AsyncMock(return_value=SimpleNamespace()),
    )
    # A known request id is a replay: no admission is needed, so these route-orchestration tests
    # need no quota (admission has its own PostgreSQL tests).
    service = SimpleNamespace(
        settings=settings,
        submit=AsyncMock(),
        has_turn_for_request=AsyncMock(return_value=True),
    )

    async def submit(*args, **kwargs):
        await emit("state", {"phase": "searching"})
        return ConversationSubmission.model_validate(DTO["submission"]), 200

    service.submit.side_effect = submit
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_application_session_service] = lambda: session
    app.dependency_overrides[get_conversation_chat_service] = lambda: service
    app.dependency_overrides[get_paid_question_quota] = lambda: AdmitAllQuota()
    return app, settings, session, service


async def post(mounted, **headers):
    async with AsyncClient(
        transport=ASGITransport(app=mounted[0]), base_url="http://localhost:3440"
    ) as client:
        return await client.post(
            f"/api/v1/conversations/{CID}/turns/stream",
            json=BODY,
            headers={"origin": mounted[1].frontend_url, "x-csrf-token": "fixture", **headers},
        )


@pytest.mark.asyncio
async def test_stream_only_completes_after_authoritative_submission(mounted):
    response = await post(mounted)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "no-store" in response.headers["cache-control"]
    assert "no-transform" in response.headers["cache-control"]
    assert response.headers["x-accel-buffering"] == "no"
    assert "event: state" in response.text and "event: complete" in response.text
    mounted[3].submit.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "environment,enabled,native,expected",
    [
        ("production", True, True, 200),
        ("production", False, True, 404),
        ("production", True, False, 409),
        ("development", True, True, 200),
        ("development", False, True, 404),
        ("development", True, False, 409),
    ],
)
async def test_stream_requires_explicit_opt_in_including_production(
    mounted, environment, enabled, native, expected
):
    mounted[1].app_env = environment
    mounted[1].chat_streaming_enabled = enabled
    mounted[1].tool_rag_agent_enabled = native
    if environment == "production":
        mounted[1].frontend_url = "https://app.example.invalid"
    assert (await post(mounted)).status_code == expected
    if expected == 200:
        mounted[3].submit.assert_awaited_once()
    else:
        mounted[3].submit.assert_not_awaited()


@pytest.mark.parametrize("environment", ["development", "production"])
def test_streaming_is_disabled_by_default_and_legacy_local_flag_does_not_enable_it(
    monkeypatch, environment
):
    monkeypatch.delenv("CHAT_STREAMING_ENABLED", raising=False)
    monkeypatch.setenv("LOCAL_CHAT_STREAMING_ENABLED", "true")
    assert Settings(_env_file=None, app_env=environment).chat_streaming_enabled is False


@pytest.mark.asyncio
@pytest.mark.parametrize("environment", ["development", "production"])
async def test_wrong_origin_cannot_submit(mounted, environment):
    mounted[1].app_env = environment
    if environment == "production":
        mounted[1].frontend_url = "https://app.example.invalid"
    assert (await post(mounted, origin="https://untrusted.invalid")).status_code == 403
    mounted[3].submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_production_flag_cannot_enable_streaming_in_public_demo_mode(mounted):
    mounted[1].app_env = "production"
    mounted[1].frontend_url = "https://app.example.invalid"
    mounted[1].demo_mode = True
    assert (await post(mounted)).status_code == 403
    mounted[3].submit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,status", [("auth", 401), ("csrf", 403)])
@pytest.mark.parametrize("environment", ["development", "production"])
async def test_auth_and_csrf_fail_before_stream_headers(mounted, kind, status, environment):
    mounted[1].app_env = environment
    if environment == "production":
        mounted[1].frontend_url = "https://app.example.invalid"
    if kind == "auth":
        mounted[2].resolve_principal.side_effect = InvalidApplicationSession()
    else:
        mounted[2].verify_csrf.side_effect = InvalidSessionRequest()
    response = await post(mounted)
    assert response.status_code == status and "event:" not in response.text
    mounted[3].submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_private_exception_is_a_safe_terminal_error(mounted):
    mounted[3].submit.side_effect = RuntimeError("private document and provider diagnostic")
    response = await post(mounted)
    assert "event: error" in response.text and "event: complete" not in response.text
    assert "private document" not in response.text


@pytest.mark.asyncio
async def test_terminal_interruption_replay_is_a_receipt_not_service_failure(mounted):
    turn = {
        **DTO["submission"]["turn"],
        "status": "INTERRUPTED",
        "answer": None,
        "query_id": None,
        "citations": [],
        "error_code": "TURN_INTERRUPTED",
        "retrieval_count": 0,
    }
    mounted[3].submit.side_effect = None
    mounted[3].submit.return_value = (ConversationSubmission(turn=turn, replayed=True), 200)
    response = await post(mounted)
    assert "event: receipt" in response.text
    assert "event: error" not in response.text and "event: complete" not in response.text
