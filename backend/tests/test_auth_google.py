"""Tests for Google OAuth routes and service (Phase 3 Milestone 2)."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from google.oauth2.credentials import Credentials

from app.api.auth import get_oauth_service
from app.main import app
from app.services.google_oauth_service import GoogleOAuthService, OAuthCallbackResult, _oauth_states


@pytest.fixture(autouse=True)
def clear_oauth_state_store() -> None:
    """Ensure OAuth state store is clean between tests."""
    _oauth_states.clear()


@pytest.mark.asyncio
async def test_google_login_redirects_to_authorization_url(async_client: AsyncClient) -> None:
    """Login endpoint should redirect to Google authorization URL."""
    fake_service = MagicMock()
    fake_service.create_authorization_url.return_value = (
        "https://accounts.google.com/o/oauth2/auth?client_id=test"
    )
    app.dependency_overrides[get_oauth_service] = lambda: fake_service

    response = await async_client.get("/api/v1/auth/google", follow_redirects=False)

    app.dependency_overrides.clear()
    assert response.status_code == 307
    assert response.headers["location"].startswith("https://accounts.google.com/o/oauth2/auth")


@pytest.mark.asyncio
async def test_google_login_returns_503_when_oauth_not_configured(
    async_client: AsyncClient,
) -> None:
    """Login endpoint should fail clearly when Google credentials are missing."""
    fake_service = MagicMock()
    fake_service.create_authorization_url.side_effect = ValueError(
        "Google OAuth credentials are not configured"
    )
    app.dependency_overrides[get_oauth_service] = lambda: fake_service

    response = await async_client.get("/api/v1/auth/google", follow_redirects=False)

    app.dependency_overrides.clear()
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


@pytest.mark.asyncio
async def test_google_callback_requires_code(async_client: AsyncClient) -> None:
    """Callback endpoint should reject missing authorization code."""
    response = await async_client.get("/api/v1/auth/google/callback")
    assert response.status_code == 400
    assert response.json()["detail"] == "Missing OAuth authorization code"


@pytest.mark.asyncio
async def test_google_callback_success_returns_user_payload(async_client: AsyncClient) -> None:
    """Callback endpoint should return success payload when service succeeds."""
    user_id = uuid.uuid4()
    fake_service = MagicMock()
    fake_service.handle_callback = AsyncMock(
        return_value=OAuthCallbackResult(
            user_id=user_id,
            email="user@example.com",
            google_id="google-123",
        )
    )
    app.dependency_overrides[get_oauth_service] = lambda: fake_service

    response = await async_client.get(
        "/api/v1/auth/google/callback",
        params={"code": "abc", "state": "state-1"},
    )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["email"] == "user@example.com"
    assert body["user_id"] == str(user_id)


@pytest.mark.asyncio
async def test_google_callback_invalid_state_returns_400(async_client: AsyncClient) -> None:
    """Callback endpoint should map service validation errors to HTTP 400."""
    fake_service = MagicMock()
    fake_service.handle_callback = AsyncMock(side_effect=ValueError("Invalid OAuth state"))
    app.dependency_overrides[get_oauth_service] = lambda: fake_service

    response = await async_client.get(
        "/api/v1/auth/google/callback",
        params={"code": "abc", "state": "bad-state"},
    )

    app.dependency_overrides.clear()
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid OAuth state"


def test_create_authorization_url_registers_state() -> None:
    """Authorization URL generation should register OAuth state for callback checks."""
    service = GoogleOAuthService(db=MagicMock())
    with patch.object(service, "_build_flow") as mock_build_flow:
        flow = MagicMock()
        flow.authorization_url.return_value = (
            "https://accounts.google.com/o/oauth2/auth?state=test-state",
            "test-state",
        )
        mock_build_flow.return_value = flow

        url = service.create_authorization_url()

    assert url.startswith("https://accounts.google.com/o/oauth2/auth")
    assert "test-state" in _oauth_states


def test_validate_google_config_requires_client_credentials() -> None:
    """Service should reject missing Google OAuth client credentials."""
    service = GoogleOAuthService(
        db=MagicMock(),
        settings=MagicMock(google_client_id="", google_client_secret=""),
    )
    with pytest.raises(ValueError, match="not configured"):
        service._validate_google_config()


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
