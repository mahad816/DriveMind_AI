"""Strict parsing, request security and inactive FastAPI dependency contracts."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy.exc import OperationalError
from starlette.responses import Response

from app.api.session_dependencies import (
    get_application_session_service,
    require_application_principal,
    require_session_mutation,
)
from app.core.config import Settings
from app.main import app
from app.security.principal import ApplicationPrincipal, ConversationOwner, VerifiedGoogleIdentity
from app.security.session_helpers import (
    InvalidApplicationSession,
    InvalidSessionRequest,
    SessionSecurityConfigurationError,
    SessionStoreUnavailable,
    clear_session_cookie,
    credential_digest,
    encode_token,
    parse_token,
    session_cookie_policy,
    set_session_cookie,
    verify_csrf_secret,
    verify_origin,
)
from app.services.application_session_service import ApplicationSessionService

TOKEN = encode_token(b"x" * 32)
CSRF = encode_token(b"c" * 32)


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        " ",
        "x" * 42,
        "x" * 44,
        TOKEN + "=",
        str(uuid4()),
        "!" * 43,
        "Ａ" * 43,
        "https://app.example.invalid",
        TOKEN[:-1] + "B",
    ],
)
def test_malformed_credentials_fail_deterministically(value: str | None) -> None:
    with pytest.raises(InvalidApplicationSession) as error:
        parse_token(value)
    assert str(error.value) == "Your application session is invalid or expired."
    assert not value or not value.strip() or value not in str(error.value)


def test_canonical_credential_digest_and_bound_csrf() -> None:
    assert parse_token(TOKEN) == b"x" * 32
    assert len(credential_digest(TOKEN)) == 32
    verify_csrf_secret(b"c" * 32, CSRF)
    for value in (None, "bad", TOKEN):
        with pytest.raises(InvalidSessionRequest):
            verify_csrf_secret(b"c" * 32, value)


@pytest.mark.parametrize(
    "origin",
    [
        None,
        "null",
        "https://evil.example.invalid",
        "https://app.example.invalid.evil",
        "http://app.example.invalid",
        "https://app.example.invalid:444",
        "https://app.example.invalid:0",
        "https://user@app.example.invalid",
        "https://app.example.invalid/path",
        "https://app.example.invalid/",
        "https://app.example.invalid?",
        "https://app.example.invalid#",
        "https://app.example.invalid,https://evil.invalid",
    ],
)
def test_untrusted_or_malformed_origins_rejected(settings: Settings, origin: str | None) -> None:
    with pytest.raises(InvalidSessionRequest):
        verify_origin(origin, settings)


def test_origin_normalization_is_configured_not_reflected(settings: Settings) -> None:
    verify_origin("https://APP.example.invalid:443", settings)
    settings.frontend_url += "/"
    verify_origin("https://app.example.invalid", settings)


@pytest.mark.parametrize("demo", [False, True])
def test_production_cookies_are_host_only_secure_and_realm_specific(
    settings: Settings, demo: bool
) -> None:
    settings.demo_mode = demo
    response = Response()
    set_session_cookie(
        response,
        credential=SecretStr(TOKEN),
        expires_at=datetime.now(UTC) + timedelta(days=1),
        settings=settings,
    )
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(
        "__Host-drivemind-demo-session=" if demo else "__Host-drivemind-session="
    )
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie
    assert "Path=/" in cookie and "Domain=" not in cookie and "expires=" in cookie
    assert not response.body
    cleared = Response()
    clear_session_cookie(cleared, settings=settings)
    assert "Max-Age=0" in cleared.headers["set-cookie"]
    assert "Secure" in cleared.headers["set-cookie"]


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]"])
def test_http_cookies_are_explicit_local_development_only(settings: Settings, host: str) -> None:
    settings.frontend_url = f"http://{host}:3000"
    for env, debug in (("production", False), ("development", False), ("test", True)):
        settings.app_env, settings.debug = env, debug
        with pytest.raises(SessionSecurityConfigurationError):
            session_cookie_policy(settings)
    settings.app_env, settings.debug = "development", True
    policy = session_cookie_policy(settings)
    assert not policy.secure and policy.name == "drivemind-local-session"
    settings.demo_mode = True
    assert session_cookie_policy(settings).name == "drivemind-local-demo-session"


@pytest.mark.parametrize(
    "origin",
    [
        "http://app.example.invalid",
        "http://localhost.evil",
        "http://0.0.0.0:3000",
        "https://user:secret@app.example.invalid",
        "https://app.example.invalid/path",
    ],
)
def test_unsafe_cookie_configuration_is_rejected(settings: Settings, origin: str) -> None:
    settings.frontend_url, settings.app_env, settings.debug = origin, "development", True
    with pytest.raises(SessionSecurityConfigurationError):
        session_cookie_policy(settings)


@pytest.mark.parametrize(
    "identity",
    [uuid4(), "verified-subject-a", {"user_id": str(uuid4())}, {"subject": "verified-subject-a"}],
)
async def test_browser_values_cannot_issue_google_sessions(
    settings: Settings, identity: object
) -> None:
    db = AsyncMock()
    with pytest.raises(InvalidApplicationSession):
        await ApplicationSessionService(db, settings).issue_google(identity)  # type: ignore[arg-type]
    db.scalar.assert_not_awaited()
    db.flush.assert_not_awaited()


@pytest.mark.parametrize("subject", ["", " padded", "with space", "é", "x" * 256, "demo:synthetic"])
def test_verified_identity_attestation_is_bounded(subject: str) -> None:
    with pytest.raises(ValueError):
        VerifiedGoogleIdentity(subject)


@pytest.mark.parametrize("operation", ["resolve", "csrf", "issue", "revoke"])
async def test_database_failures_are_safe_and_not_logged(
    settings: Settings, operation: str, caplog: pytest.LogCaptureFixture
) -> None:
    db = AsyncMock()
    db.scalar.side_effect = OperationalError(
        "private SQL", {}, Exception("private-secret-diagnostic")
    )
    service = ApplicationSessionService(db, settings)
    with pytest.raises(SessionStoreUnavailable) as error:
        if operation == "resolve":
            await service.resolve_principal(TOKEN)
        elif operation == "csrf":
            await service.verify_csrf(TOKEN, CSRF)
        elif operation == "issue":
            await service.issue_google(VerifiedGoogleIdentity("verified-subject-a"))
        else:
            await service.revoke(TOKEN)
    assert "private" not in str(error.value) and TOKEN not in str(error.value)
    assert not caplog.records


async def test_future_dependencies_map_errors_safely_without_public_issuance(
    settings: Settings,
) -> None:
    db = AsyncMock()
    db.scalar.side_effect = OperationalError("secret SQL", {}, Exception("secret"))
    service = ApplicationSessionService(db, settings)
    isolated = FastAPI()
    isolated.dependency_overrides[get_application_session_service] = lambda: service

    @isolated.get("/private")
    async def private(
        principal: ApplicationPrincipal = Depends(require_application_principal),
    ) -> dict[str, bool]:
        return {"ok": True}

    @isolated.post("/private")
    async def mutation(
        principal: ApplicationPrincipal = Depends(require_session_mutation),
    ) -> dict[str, bool]:
        return {"ok": True}

    async with AsyncClient(
        transport=ASGITransport(app=isolated), base_url=settings.frontend_url
    ) as client:
        response = await client.get("/private")
        assert response.status_code == 401
        client.cookies.set(session_cookie_policy(settings).name, TOKEN)
        response = await client.get("/private")
        assert response.status_code == 503 and "secret" not in response.text
        response = await client.post("/private", headers={"Origin": "https://evil.invalid"})
        assert response.status_code == 403
        response = await client.post(
            "/private",
            headers=[("Origin", settings.frontend_url), ("Origin", settings.frontend_url)],
        )
        assert response.status_code == 403
        response = await client.post(
            "/private",
            headers=[
                ("Origin", settings.frontend_url),
                ("X-CSRF-Token", CSRF),
                ("X-CSRF-Token", CSRF),
            ],
        )
        assert response.status_code == 403
        response = await client.post(
            "/private", headers={"Origin": settings.frontend_url, "X-CSRF-Token": CSRF}
        )
        assert response.status_code == 503 and TOKEN not in response.text


def test_existing_application_routes_do_not_use_session_dependencies() -> None:
    def calls(dependant):
        return [dependant.call] + [
            call for child in dependant.dependencies for call in calls(child)
        ]

    for route in app.routes:
        if isinstance(route, APIRoute):
            assert require_application_principal not in calls(route.dependant)
            assert require_session_mutation not in calls(route.dependant)
    paths = {route.path for route in app.routes if isinstance(route, APIRoute)}
    assert "/api/v1/auth/session" not in paths and "/api/v1/visitor-session" not in paths
    assert Settings.model_fields["demo_mode"].default is False
    assert Settings.model_fields["tool_rag_agent_enabled"].default is False


@pytest.mark.parametrize("demo", [False, True])
def test_principal_cannot_represent_wrong_owner_or_mode(demo: bool) -> None:
    from app.db.enums import ApplicationSessionKind

    identity = uuid4()
    with pytest.raises(ValueError, match="ownership"):
        ApplicationPrincipal(
            session_id=uuid4(),
            kind=ApplicationSessionKind.GOOGLE_ACCOUNT,
            authenticated_user_id=identity,
            conversation_owner=ConversationOwner("USER", uuid4()),
            corpus_user_id=identity,
            demo_mode=demo,
        )
