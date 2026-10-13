"""Retired browser OAuth routes and retained shared provider helpers."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from google.oauth2.credentials import Credentials

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.main import create_app
from app.services.google_oauth_service import GoogleOAuthService, OAuthCallbackResult
from app.db.models.oauth_pending_state import OAuthPendingState


@pytest.mark.asyncio
@pytest.mark.parametrize("demo", [False, True])
@pytest.mark.parametrize(
    "path",
    [
        "/auth/google",
        "/auth/google/",
        "/auth/google/callback",
        "/auth/google/callback?code=synthetic-code&state=synthetic-state",
    ],
)
async def test_legacy_oauth_routes_unreachable(
    demo: bool, path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: Settings(demo_mode=demo)
    database = MagicMock(return_value=MagicMock())
    application.dependency_overrides[get_db] = lambda: database()
    start = AsyncMock(return_value="https://accounts.google.com/synthetic")
    callback = AsyncMock(
        return_value=OAuthCallbackResult(
            user_id=uuid.UUID(int=101), email="synthetic@example.invalid", google_id="synthetic"
        )
    )
    monkeypatch.setattr(GoogleOAuthService, "create_authorization_url", start)
    monkeypatch.setattr(GoogleOAuthService, "handle_callback", callback)
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/v1" + path, follow_redirects=False)
    assert response.status_code == 404
    assert "location" not in response.headers
    assert "set-cookie" not in response.headers
    database.assert_not_called()
    start.assert_not_awaited()
    callback.assert_not_awaited()


def test_only_v2_session_auth_routes_are_mounted() -> None:
    application = create_app()
    expected = {
        "/api/v1/auth/session",
        "/api/v1/auth/session/google",
        "/api/v1/auth/session/google/callback",
        "/api/v1/auth/session/logout",
    }
    assert {
        path for path in application.openapi()["paths"] if path.startswith("/api/v1/auth/")
    } == expected


@pytest.mark.asyncio
async def test_create_authorization_url_persists_pending_state() -> None:
    """Authorization URL generation should persist PKCE state in the database."""
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    service = GoogleOAuthService(db=mock_db)
    with patch.object(service, "_build_flow") as mock_build_flow:
        flow = MagicMock()
        flow.code_verifier = "pkce-verifier-123"
        flow.authorization_url.return_value = (
            "https://accounts.google.com/o/oauth2/auth?state=test-state",
            "test-state",
        )
        mock_build_flow.return_value = flow

        url = await service.create_authorization_url()

    assert url.startswith("https://accounts.google.com/o/oauth2/auth")
    mock_db.add.assert_called_once()
    added = mock_db.add.call_args[0][0]
    assert isinstance(added, OAuthPendingState)
    assert added.state == "test-state"
    assert added.code_verifier == "pkce-verifier-123"


def test_fetch_credentials_uses_stored_code_verifier() -> None:
    """Token exchange should reuse the PKCE verifier from the login step."""
    service = GoogleOAuthService(db=MagicMock())
    with patch.object(service, "_build_flow") as mock_build_flow:
        flow = MagicMock()
        flow.credentials = Credentials(token="access-token")
        mock_build_flow.return_value = flow

        credentials = service._fetch_credentials("auth-code", "pkce-verifier-123")

    assert flow.code_verifier == "pkce-verifier-123"
    flow.fetch_token.assert_called_once_with(code="auth-code")
    assert credentials.token == "access-token"


def test_validate_google_config_requires_client_credentials() -> None:
    """Service should reject missing Google OAuth client credentials."""
    service = GoogleOAuthService(
        db=MagicMock(),
        settings=MagicMock(google_client_id="", google_client_secret=""),
    )
    with pytest.raises(ValueError, match="not configured"):
        service._validate_google_config()


def test_oauth_scopes_include_identity_and_drive() -> None:
    """OAuth should request identity scopes needed for userinfo plus Drive access."""
    service = GoogleOAuthService(
        db=MagicMock(),
        settings=MagicMock(google_drive_scopes="https://www.googleapis.com/auth/drive.readonly"),
    )
    scopes = service._oauth_scopes()
    assert "openid" in scopes
    assert "https://www.googleapis.com/auth/userinfo.email" in scopes
    assert "https://www.googleapis.com/auth/drive.readonly" in scopes


def test_fetch_google_profile_requires_identity_fields() -> None:
    """Profile fetch should fail when Google does not return email/id."""
    service = GoogleOAuthService(db=MagicMock())
    credentials = Credentials(token="token")
    with patch("app.services.google_oauth_service.build") as mock_build:
        mock_build.return_value.userinfo.return_value.get.return_value.execute.return_value = {
            "email": None,
            "id": None,
        }
        with pytest.raises(ValueError, match="missing required identity fields"):
            service._fetch_google_profile(credentials)
