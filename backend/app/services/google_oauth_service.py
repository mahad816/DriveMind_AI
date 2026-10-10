"""Google OAuth service for Drive read-only authentication."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.credential_diagnostics import OAuthCredentialFailure, failure_category, safe_failure
from app.core.config import Settings, get_settings
from pydantic import SecretStr
from app.services.google_credential_repository import (
    GoogleCredentialRepository,
    CredentialRepositoryError,
    CredentialReauthorizationRequired,
)
from app.security.google_credential_crypto import CredentialCryptoError
from app.db.models.oauth_pending_state import OAuthPendingState
from app.db.models.user import User

_OAUTH_STATE_TTL = timedelta(minutes=10)
_OAUTH_STATE_RETRY_HINT = "Start again from /api/v1/auth/google (do not refresh the callback URL)."


@dataclass
class OAuthCallbackResult:
    """Result returned after successful OAuth callback handling."""

    user_id: uuid.UUID
    email: str
    google_id: str


_identity_scopes = (
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
)


class GoogleOAuthService:
    """Handles Google OAuth URL generation and callback token exchange."""

    def __init__(self, db: AsyncSession, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def _validate_google_config(self) -> None:
        if not self.settings.google_client_id or not self.settings.google_client_secret:
            raise OAuthCredentialFailure(
                "Google OAuth credentials are not configured", category="configuration_error"
            )

    def _oauth_scopes(self) -> list[str]:
        scopes: list[str] = list(_identity_scopes)
        for scope in self.settings.google_drive_scopes.split():
            if scope and scope not in scopes:
                scopes.append(scope)
        return scopes

    def _build_flow(
        self, *, scopes: list[str] | None = None, redirect_uri: str | None = None
    ) -> Flow:
        self._validate_google_config()
        client_config = {
            "web": {
                "client_id": self.settings.google_client_id,
                "client_secret": self.settings.google_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        }
        return Flow.from_client_config(
            client_config,
            scopes=scopes if scopes is not None else self._oauth_scopes(),
            redirect_uri=redirect_uri or self.settings.google_redirect_uri,
        )

    async def create_authorization_url(self) -> str:
        """Create Google OAuth URL and persist PKCE state for callback validation."""
        flow = self._build_flow()
        authorization_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        code_verifier = flow.code_verifier
        if not code_verifier:
            raise ValueError("OAuth PKCE code verifier was not generated")

        expires_at = datetime.now(UTC) + _OAUTH_STATE_TTL
        self.db.add(
            OAuthPendingState(
                state=state,
                code_verifier=code_verifier,
                expires_at=expires_at,
            )
        )
        await self.db.commit()
        return str(authorization_url)

    async def _pop_code_verifier(self, state: str | None) -> str:
        if not state:
            raise ValueError(f"Invalid OAuth state. {_OAUTH_STATE_RETRY_HINT}")

        pending = await self.db.scalar(
            select(OAuthPendingState).where(
                OAuthPendingState.state == state, OAuthPendingState.browser_binding_hash.is_(None)
            )
        )
        if pending is None:
            raise ValueError(f"Invalid OAuth state. {_OAUTH_STATE_RETRY_HINT}")

        await self.db.delete(pending)
        await self.db.flush()

        if pending.expires_at < datetime.now(UTC):
            raise ValueError(f"OAuth session expired. {_OAUTH_STATE_RETRY_HINT}")

        return pending.code_verifier

    def _fetch_credentials(self, code: str, code_verifier: str) -> Credentials:
        flow = self._build_flow()
        flow.code_verifier = code_verifier
        try:
            flow.fetch_token(code=code)
        except Exception as exc:
            raise OAuthCredentialFailure(
                safe_failure(exc, "OAuth token exchange"), category=failure_category(exc)
            ) from None
        credentials = cast(Credentials, flow.credentials)
        if not credentials.token:
            raise ValueError("Failed to obtain Google OAuth credentials")
        return credentials

    @staticmethod
    def _userinfo_credentials(credentials: Credentials) -> Credentials:
        """Fresh OAuth access only: userinfo must never refresh an unpersisted grant."""
        expiry = credentials.expiry
        if expiry is not None and expiry.tzinfo is not None:
            expiry = expiry.astimezone(UTC).replace(tzinfo=None)
        return Credentials(  # type: ignore[no-untyped-call]
            token=credentials.token, scopes=credentials.scopes, expiry=expiry
        )

    def _fetch_google_profile(self, credentials: Credentials) -> dict[str, str]:
        failure: OAuthCredentialFailure | None = None
        profile: dict[str, str] = {}
        try:
            oauth2_service = build(
                "oauth2",
                "v2",
                credentials=self._userinfo_credentials(credentials),
                cache_discovery=False,
            )
            profile = oauth2_service.userinfo().get().execute()
        except Exception as exc:
            failure = OAuthCredentialFailure(
                safe_failure(exc, "Google profile request"), category=failure_category(exc)
            )
        if failure is not None:
            raise failure from None
        email = profile.get("email")
        google_id = profile.get("id")
        if not email or not google_id:
            raise ValueError("Google profile missing required identity fields")
        return {"email": email, "google_id": google_id}

    async def _upsert_user(self, email: str, google_id: str) -> User:
        user = await self.db.scalar(select(User).where(User.google_id == google_id))
        if user is None:
            user = User(email=email, google_id=google_id)
            self.db.add(user)
            await self.db.flush()
        else:
            user.email = email
        return user

    async def _upsert_token(self, user: User, credentials: Credentials) -> None:
        expiry = credentials.expiry
        if expiry is not None:
            expiry = expiry.replace(tzinfo=UTC) if expiry.tzinfo is None else expiry.astimezone(UTC)
        if not credentials.token:
            raise ValueError("Failed to obtain Google access token")
        granted_scopes = credentials.granted_scopes or credentials.scopes
        try:
            await GoogleCredentialRepository(self.db, self.settings).write_verified_grant(
                user.id,
                access_token=SecretStr(credentials.token),
                refresh_token=SecretStr(credentials.refresh_token)
                if credentials.refresh_token
                else None,
                token_expiry=expiry,
                scopes=" ".join(granted_scopes)
                if granted_scopes
                else self.settings.google_drive_scopes,
            )
        except CredentialReauthorizationRequired:
            raise OAuthCredentialFailure(
                "Reconnect Google Drive with offline authorization.",
                category="reauthorization_required",
            ) from None
        except (CredentialRepositoryError, CredentialCryptoError):
            raise OAuthCredentialFailure(
                "Google credential storage is unavailable.", category="configuration_error"
            ) from None

    async def handle_callback(self, code: str, state: str | None) -> OAuthCallbackResult:
        """Validate callback, exchange code, and persist user + token records."""
        code_verifier = await self._pop_code_verifier(state)
        credentials = self._fetch_credentials(code, code_verifier)
        profile = self._fetch_google_profile(credentials)
        user = await self._upsert_user(profile["email"], profile["google_id"])
        await self._upsert_token(user, credentials)
        await self._cleanup_expired_pending_states()
        await self.db.commit()
        await self.db.refresh(user)
        return OAuthCallbackResult(
            user_id=user.id,
            email=user.email,
            google_id=user.google_id,
        )

    async def _cleanup_expired_pending_states(self) -> None:
        """Remove expired OAuth pending rows (best-effort housekeeping)."""
        await self.db.execute(
            delete(OAuthPendingState).where(OAuthPendingState.expires_at < datetime.now(UTC))
        )
