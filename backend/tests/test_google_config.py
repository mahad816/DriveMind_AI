"""Tests for Google OAuth configuration (Phase 3 Milestone 1)."""

from app.core.config import Settings


def test_settings_include_google_oauth_fields() -> None:
    """Settings model should expose all Google OAuth env fields."""
    settings = Settings(
        google_client_id="test-client-id",
        google_client_secret="test-client-secret",
        google_redirect_uri="http://localhost:8000/api/v1/auth/google/callback",
        google_drive_scopes="https://www.googleapis.com/auth/drive.readonly",
    )
    assert settings.google_client_id == "test-client-id"
    assert settings.google_client_secret == "test-client-secret"
    assert settings.google_redirect_uri.endswith("/auth/google/callback")
    assert "drive.readonly" in settings.google_drive_scopes


def test_settings_google_scope_and_callback_are_correct() -> None:
    """Loaded settings must use read-only Drive scope and OAuth callback path."""
    settings = Settings()
    assert settings.google_drive_scopes == "https://www.googleapis.com/auth/drive.readonly"
    assert settings.google_redirect_uri.endswith("/auth/google/callback")
