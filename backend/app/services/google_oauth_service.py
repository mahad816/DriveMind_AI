"""Google OAuth service for Drive read-only authentication."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC
from typing import cast

from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.models.google_oauth_token import GoogleOAuthToken
from app.db.models.user import User

_oauth_states: set[str] = set()


@dataclass
class OAuthCallbackResult:
    """Result returned after successful OAuth callback handling."""

    user_id: uuid.UUID
    email: str
    google_id: str


class GoogleOAuthService:
    """Handles Google OAuth URL generation and callback token exchange."""

    def __init__(self, db: AsyncSession, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def _validate_google_config(self) -> None:
        if not self.settings.google_client_id or not self.settings.google_client_secret:
            raise ValueError("Google OAuth credentials are not configured")

    def _build_flow(self) -> Flow:
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
            scopes=[self.settings.google_drive_scopes],
            redirect_uri=self.settings.google_redirect_uri,
        )

    def create_authorization_url(self) -> str:
        """Create Google OAuth URL and register state for callback validation."""
        flow = self._build_flow()
        authorization_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        _oauth_states.add(state)
        return str(authorization_url)

    def _validate_state(self, state: str | None) -> None:
        if not state or state not in _oauth_states:
            raise ValueError("Invalid OAuth state")
        _oauth_states.discard(state)

    def _fetch_credentials(self, code: str) -> Credentials:
        flow = self._build_flow()
        flow.fetch_token(code=code)
        credentials = cast(Credentials, flow.credentials)
        if not credentials.token:
            raise ValueError("Failed to obtain Google OAuth credentials")
        return credentials

    def _fetch_google_profile(self, credentials: Credentials) -> dict[str, str]:
        oauth2_service = build("oauth2", "v2", credentials=credentials, cache_discovery=False)
        profile = oauth2_service.userinfo().get().execute()
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
        token_row = await self.db.scalar(
            select(GoogleOAuthToken).where(GoogleOAuthToken.user_id == user.id)
        )
        expiry = credentials.expiry
        if expiry is not None and expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)

        scopes = (
            " ".join(credentials.scopes)
            if credentials.scopes
            else self.settings.google_drive_scopes
        )
        access_token = credentials.token
        if access_token is None:
            raise ValueError("Failed to obtain Google access token")

        if token_row is None:
            token_row = GoogleOAuthToken(
                user_id=user.id,
                access_token=access_token,
                refresh_token=credentials.refresh_token,
                token_expiry=expiry,
                scopes=scopes,
            )
            self.db.add(token_row)
        else:
            token_row.access_token = access_token
            if credentials.refresh_token:
                token_row.refresh_token = credentials.refresh_token
            token_row.token_expiry = expiry
            token_row.scopes = scopes

    async def handle_callback(self, code: str, state: str | None) -> OAuthCallbackResult:
        """Validate callback, exchange code, and persist user + token records."""
        self._validate_state(state)
        credentials = self._fetch_credentials(code)
        profile = self._fetch_google_profile(credentials)
        user = await self._upsert_user(profile["email"], profile["google_id"])
        await self._upsert_token(user, credentials)
        await self.db.commit()
        await self.db.refresh(user)
        return OAuthCallbackResult(
            user_id=user.id,
            email=user.email,
            google_id=user.google_id,
        )
