"""Opt-in browser-bound OIDC login, reusing Drive OAuth and application sessions."""

import asyncio
import hmac
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from functools import partial
from urllib.parse import urlsplit
from uuid import UUID

import httplib2  # type: ignore[import-untyped]
from google_auth_httplib2 import AuthorizedHttp  # type: ignore[import-untyped]
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

import requests
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
from google.oauth2.credentials import Credentials
from pydantic import SecretStr
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.db.models.application_session import ApplicationSession
from app.db.models.oauth_pending_state import OAuthPendingState
from app.db.models.user import User
from app.security.principal import VerifiedGoogleIdentity
from app.security.session_helpers import (
    InvalidApplicationSession,
    SessionSecurityConfigurationError,
    SessionStoreUnavailable,
    credential_digest,
    encode_token,
    parse_token,
    trusted_origin,
    verify_origin,
)
from app.services.application_session_service import (
    ApplicationSessionService,
    IssuedApplicationSession,
)
from app.core.credential_diagnostics import OAuthCredentialFailure
from app.services.google_oauth_service import GoogleOAuthService, _identity_scopes


class GoogleAuthIntent(StrEnum):
    LOGIN = "LOGIN"
    CONNECT_DRIVE = "CONNECT_DRIVE"


class GoogleLoginRejected(ValueError):
    def __init__(self) -> None:
        super().__init__("Google login could not be verified. Please start again.")


def _granted_scopes(raw_scopes: object) -> list[str]:
    """Validate actual provider scope evidence, never the requested-scope fallback."""
    if isinstance(raw_scopes, str):
        granted = raw_scopes.split(" ")
    elif isinstance(raw_scopes, list):
        granted = raw_scopes
    else:
        raise GoogleLoginRejected()
    # RFC 6749 scope tokens exclude whitespace, quotes, backslashes
    # and non-printable/non-ASCII characters. Never stringify a list.
    if not granted or any(
        not isinstance(scope, str)
        or not scope
        or any(not "!" <= char <= "~" or char in '"\\' for char in scope)
        for scope in granted
    ):
        raise GoogleLoginRejected()
    return granted


def validate_session_login_configuration(settings: Settings) -> None:
    """Require an explicit callback on the cookie-owning frontend origin."""
    if not settings.google_application_sessions_enabled or settings.demo_mode:
        raise SessionSecurityConfigurationError()
    try:
        parsed = urlsplit(settings.google_session_redirect_uri)
        callback_origin = f"{parsed.scheme}://{parsed.netloc}"
        verify_origin(callback_origin, settings)
        if (
            parsed.path != settings.api_prefix + "/auth/session/google/callback"
            or parsed.query
            or parsed.fragment
            or not settings.google_client_id
            or not settings.google_client_secret
        ):
            raise ValueError()
        trusted_origin(settings)
    except (ValueError, TypeError):
        raise SessionSecurityConfigurationError() from None


def verify_google_token(
    credentials: Credentials, nonce: str, settings: Settings
) -> tuple[VerifiedGoogleIdentity, str]:
    """Google's maintained verifier checks signature, audience, issuer, exp and iat.

    Certificate fetches are bounded; no custom JWT verification or token logging.
    """
    token = credentials.id_token
    if not isinstance(token, str) or len(token) > 16384:
        raise GoogleLoginRejected()
    try:
        with requests.Session() as transport:
            request = partial(GoogleRequest(session=transport), timeout=20)
            claims = id_token.verify_oauth2_token(  # type: ignore[no-untyped-call]
                token, request, settings.google_client_id
            )
        subject, email, actual_nonce = claims.get("sub"), claims.get("email"), claims.get("nonce")
        if (
            not isinstance(subject, str)
            or not isinstance(email, str)
            or not email
            or len(email) > 320
            or not isinstance(actual_nonce, str)
            or not hmac.compare_digest(actual_nonce.encode(), nonce.encode())
            or claims.get("email_verified") is not True
        ):
            raise GoogleLoginRejected()
        return VerifiedGoogleIdentity(subject), email
    except Exception:
        raise GoogleLoginRejected() from None


@dataclass(frozen=True)
class GoogleLoginStart:
    authorization_url: str = field(repr=False)
    browser_binding: SecretStr = field(repr=False)
    expires_at: datetime


@dataclass(frozen=True)
class PendingLogin:
    verifier: str = field(repr=False)
    nonce: str = field(repr=False)
    intent: GoogleAuthIntent
    session_id: UUID | None
    credential_hash: bytes | None = field(repr=False)


class GoogleSessionAuthService(GoogleOAuthService):
    """State consumption and successful login use separate short transactions.

    No DB transaction is held during external Google I/O. Failures after state
    consumption require a new login. No legacy-account or demo fallback exists.
    """

    def _check(self) -> None:
        validate_session_login_configuration(self.settings)

    def _session_service(self) -> ApplicationSessionService:
        return ApplicationSessionService(self.db, self.settings)

    def _flow(self, intent: GoogleAuthIntent) -> Flow:
        return self._build_flow(
            scopes=list(_identity_scopes)
            if intent == GoogleAuthIntent.LOGIN
            else self._oauth_scopes(),
            redirect_uri=self.settings.google_session_redirect_uri,
        )

    async def start(self, intent: GoogleAuthIntent, credential: str | None) -> GoogleLoginStart:
        self._check()
        if not isinstance(intent, GoogleAuthIntent):
            raise GoogleLoginRejected()
        try:
            digest = credential_digest(credential) if credential is not None else None
            session_id = None
            if credential is not None:
                try:
                    principal = await self._session_service().resolve_principal(credential)
                    session_id = principal.session_id
                except InvalidApplicationSession:
                    if intent == GoogleAuthIntent.CONNECT_DRIVE:
                        raise
            if intent == GoogleAuthIntent.CONNECT_DRIVE and session_id is None:
                raise InvalidApplicationSession()
            binding, state, nonce = (encode_token(secrets.token_bytes(32)) for _ in range(3))
            flow = self._flow(intent)
            url, returned_state = flow.authorization_url(
                state=state,
                nonce=nonce,
                access_type="offline" if intent == GoogleAuthIntent.CONNECT_DRIVE else "online",
                prompt="consent" if intent == GoogleAuthIntent.CONNECT_DRIVE else "select_account",
                **(
                    {"include_granted_scopes": "true"}
                    if intent == GoogleAuthIntent.CONNECT_DRIVE
                    else {}
                ),
            )
            if returned_state != state or not flow.code_verifier:
                raise GoogleLoginRejected()
            expires = datetime.now(UTC) + timedelta(minutes=10)
            self.db.add(
                OAuthPendingState(
                    state=state,
                    code_verifier=flow.code_verifier,
                    expires_at=expires,
                    browser_binding_hash=credential_digest(binding),
                    nonce=nonce,
                    intent=intent.value,
                    initiating_session_id=session_id,
                    initiating_credential_hash=digest,
                )
            )
            await self.db.commit()
            return GoogleLoginStart(str(url), SecretStr(binding), expires)
        except SQLAlchemyError:
            await self.db.rollback()
            raise SessionStoreUnavailable() from None

    async def _consume(self, state: str | None, binding: str | None) -> PendingLogin:
        try:
            parse_token(state)
            digest = credential_digest(binding)
        except InvalidApplicationSession:
            raise GoogleLoginRejected() from None
        row = await self.db.scalar(
            delete(OAuthPendingState)
            .where(
                OAuthPendingState.state == state,
                OAuthPendingState.browser_binding_hash == digest,
                OAuthPendingState.intent.is_not(None),
                OAuthPendingState.expires_at > datetime.now(UTC),
            )
            .returning(OAuthPendingState)
        )
        if row is None or row.nonce is None or row.intent is None:
            raise GoogleLoginRejected()
        pending = PendingLogin(
            row.code_verifier,
            row.nonce,
            GoogleAuthIntent(row.intent),
            row.initiating_session_id,
            row.initiating_credential_hash,
        )
        await self.db.commit()  # Atomic one-shot consumption precedes external I/O.
        return pending

    def _fetch_google_profile(self, credentials: Credentials) -> dict[str, str]:
        # Bound userinfo transport independently of the overall async deadline.
        transport = httplib2.Http(timeout=20)
        try:
            client = build(
                "oauth2",
                "v2",
                http=AuthorizedHttp(self._userinfo_credentials(credentials), http=transport),
                cache_discovery=False,
            )
            profile = client.userinfo().get().execute(num_retries=0)
            subject, email = profile.get("id"), profile.get("email")
            if not isinstance(subject, str) or not isinstance(email, str):
                raise GoogleLoginRejected()
            return {"google_id": subject, "email": email}
        finally:
            transport.close()

    def _exchange_and_verify(
        self, code: str, pending: PendingLogin
    ) -> tuple[Credentials, VerifiedGoogleIdentity, str]:
        try:
            flow = self._flow(pending.intent)
            flow.code_verifier = pending.verifier
            if pending.intent == GoogleAuthIntent.CONNECT_DRIVE:
                requested = set(flow.oauth2session.scope)

                def incremental_scopes(response: requests.Response) -> requests.Response:
                    payload = response.json()
                    if not isinstance(payload, dict):
                        raise GoogleLoginRejected()
                    if "error" in payload:
                        return response  # Preserve OAuthlib's OAuth error handling.
                    granted = _granted_scopes(payload.get("scope"))
                    if not requested.issubset(granted):
                        raise GoogleLoginRejected()
                    # This callback-local flow has already sent its token request.
                    # Compare against the validated actual superset, without changing
                    # the response, requested permissions or global OAuthlib policy.
                    flow.oauth2session.scope = granted
                    return response

                flow.oauth2session.register_compliance_hook(
                    "access_token_response", incremental_scopes
                )
            flow.fetch_token(code=code, timeout=20)
            credentials = flow.credentials
            if not isinstance(credentials, Credentials) or not credentials.token:
                raise GoogleLoginRejected()
            identity, email = verify_google_token(credentials, pending.nonce, self.settings)
            profile = self._fetch_google_profile(credentials)
            if profile["google_id"] != identity.subject:
                raise GoogleLoginRejected()
            if pending.intent == GoogleAuthIntent.CONNECT_DRIVE:
                # Requested scopes are not evidence that Google actually granted them.
                granted = _granted_scopes(flow.oauth2session.token.get("scope"))
                if not set(self.settings.google_drive_scopes.split()).issubset(granted):
                    raise GoogleLoginRejected()
            return credentials, identity, email
        except Exception:
            raise GoogleLoginRejected() from None

    async def callback(
        self, *, code: str, state: str | None, binding: str | None, credential: str | None
    ) -> IssuedApplicationSession:
        self._check()
        if not code or len(code) > 4096:
            raise GoogleLoginRejected()
        try:
            pending = await self._consume(state, binding)
            digest = credential_digest(credential) if credential is not None else None
            if digest != pending.credential_hash:
                raise GoogleLoginRejected()
            async with asyncio.timeout(60):
                credentials, identity, email = await asyncio.to_thread(
                    self._exchange_and_verify, code, pending
                )
            # Serialize rotation against logout or another successful login. Locks
            # are acquired only AFTER Google I/O, never while waiting on Google.
            if pending.session_id is not None:
                await self.db.scalar(
                    select(ApplicationSession.id)
                    .where(ApplicationSession.id == pending.session_id)
                    .with_for_update()
                )
                principal = await self._session_service().resolve_principal(credential)
                if principal.session_id != pending.session_id:
                    raise GoogleLoginRejected()
                if pending.intent == GoogleAuthIntent.CONNECT_DRIVE:
                    subject = await self.db.scalar(
                        select(User.google_id).where(User.id == principal.authenticated_user_id)
                    )
                    if subject != identity.subject:
                        raise GoogleLoginRejected()
            elif pending.intent == GoogleAuthIntent.CONNECT_DRIVE:
                raise GoogleLoginRejected()
            user = await self._upsert_user(email, identity.subject)
            if pending.intent == GoogleAuthIntent.CONNECT_DRIVE:
                await self._upsert_token(user, credentials)
            issued = await self._session_service().issue_google(identity)
            if credential is not None:
                await self._session_service().revoke(credential)
            await self.db.commit()  # Cookie issuance is exclusively AFTER this commit.
            return issued
        except (SQLAlchemyError, SessionStoreUnavailable, OAuthCredentialFailure):
            await self.db.rollback()
            raise SessionStoreUnavailable() from None
        except (GoogleLoginRejected, InvalidApplicationSession, TimeoutError):
            await self.db.rollback()
            raise GoogleLoginRejected() from None
        except asyncio.CancelledError:
            await self.db.rollback()
            raise
