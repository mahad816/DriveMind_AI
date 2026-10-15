"""OIDC verification uses Google's real verifier with isolated signing keys."""

import json
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from google.auth import crypt, jwt
from google.oauth2.credentials import Credentials

from app.core.config import Settings
from app.security.session_helpers import SessionSecurityConfigurationError
from app.services.google_session_auth_service import (
    GoogleAuthIntent,
    GoogleLoginRejected,
    GoogleSessionAuthService,
    PendingLogin,
    validate_session_login_configuration,
    verify_google_token,
)


@pytest.fixture
def oidc(monkeypatch: pytest.MonkeyPatch, settings: Settings):
    settings.google_client_id = "client.example.invalid"
    settings.google_client_secret = "synthetic-client-secret"
    settings.google_application_sessions_enabled = True
    settings.google_session_redirect_uri = (
        settings.frontend_url + "/api/v1/auth/session/google/callback"
    )
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    signer = crypt.RSASigner.from_string(private, key_id="test-key")

    def request(url: str, **kwargs: object):
        assert url == "https://www.googleapis.com/oauth2/v1/certs"
        assert kwargs["timeout"] == 20
        return SimpleNamespace(status=200, data=json.dumps({"test-key": public.decode()}).encode())

    monkeypatch.setattr(
        "app.services.google_session_auth_service.GoogleRequest", lambda **kwargs: request
    )

    def token(**changes: object) -> Credentials:
        claims = {
            "iss": "https://accounts.google.com",
            "aud": settings.google_client_id,
            "sub": "verified-subject-a",
            "email": "a@example.invalid",
            "email_verified": True,
            "nonce": "expected-nonce",
            "iat": int(time.time()) - 5,
            "exp": int(time.time()) + 600,
        }
        claims.update(changes)
        return Credentials(token="synthetic-access", id_token=jwt.encode(signer, claims).decode())

    return token


def test_valid_google_verification(oidc, settings: Settings) -> None:
    identity, email = verify_google_token(oidc(), "expected-nonce", settings)
    assert identity.subject == "verified-subject-a" and email == "a@example.invalid"


@pytest.mark.parametrize(
    "claims",
    [
        {"aud": "other-client"},
        {"iss": "https://attacker.invalid"},
        {"exp": 1},
        {"iat": int(time.time()) + 600},
        {"nonce": "incorrect"},
        {"sub": None},
        {"sub": "demo:foreign"},
        {"email": None},
        {"email_verified": False},
        {"iat": None},
        {"exp": None},
        {"iss": None},
        {"aud": None},
        {"nonce": None},
    ],
)
def test_invalid_signed_claims_rejected(oidc, settings: Settings, claims: dict) -> None:
    with pytest.raises(GoogleLoginRejected, match="could not be verified"):
        verify_google_token(oidc(**claims), "expected-nonce", settings)


def test_invalid_signature_and_missing_id_token(oidc, settings: Settings) -> None:
    credentials = oidc()
    token = str(credentials.id_token)
    credentials = Credentials(token="synthetic", id_token=token[:-12] + "A" * 12)
    for invalid in (credentials, Credentials(token="synthetic")):
        with pytest.raises(GoogleLoginRejected):
            verify_google_token(invalid, "expected-nonce", settings)


@pytest.mark.parametrize(
    "callback",
    [
        "https://backend.example.invalid/api/v1/auth/session/google/callback",
        "https://app.example.invalid/api/v1/auth/google/callback",
        "https://app.example.invalid/api/v1/auth/session/google/callback?return=evil",
        "https://app.example.invalid/api/v1/auth/session/google/callback#fragment",
        "",
    ],
)
def test_callback_must_be_explicit_and_same_origin(oidc, settings: Settings, callback: str):
    settings.google_session_redirect_uri = callback
    with pytest.raises(SessionSecurityConfigurationError):
        validate_session_login_configuration(settings)


def test_pkce_subject_and_granted_scopes(oidc, settings: Settings, monkeypatch: pytest.MonkeyPatch):
    service = GoogleSessionAuthService(MagicMock(), settings)
    credentials = oidc()
    flow = MagicMock()
    flow.credentials = credentials
    flow.oauth2session.token = {"scope": settings.google_drive_scopes}
    monkeypatch.setattr(service, "_flow", lambda intent: flow)
    monkeypatch.setattr(
        service,
        "_fetch_google_profile",
        lambda creds: {"google_id": "verified-subject-a", "email": "a@example.invalid"},
    )
    pending = PendingLogin("pkce-verifier", "expected-nonce", GoogleAuthIntent.LOGIN, None, None)
    assert service._exchange_and_verify("code", pending)[1].subject == "verified-subject-a"
    assert flow.code_verifier == "pkce-verifier"
    flow.fetch_token.assert_called_once_with(code="code", timeout=20)
    monkeypatch.setattr(
        service,
        "_fetch_google_profile",
        lambda creds: {"google_id": "different-subject", "email": "a@example.invalid"},
    )
    with pytest.raises(GoogleLoginRejected):
        service._exchange_and_verify("code", pending)
    monkeypatch.setattr(
        service,
        "_fetch_google_profile",
        lambda creds: {"google_id": "verified-subject-a", "email": "a@example.invalid"},
    )
    pending = PendingLogin(
        "pkce-verifier", "expected-nonce", GoogleAuthIntent.CONNECT_DRIVE, None, None
    )
    flow.oauth2session.token = {"scope": "openid"}
    with pytest.raises(GoogleLoginRejected):
        service._exchange_and_verify("code", pending)


def install_token_response(monkeypatch, credentials, scopes):
    """Fake only HTTP; retain Flow.fetch_token and OAuthlib's actual token parser."""
    from requests import Request, Response

    response = Response()
    response.status_code = 200
    response.request = Request("POST", "https://oauth2.googleapis.com/token").prepare()
    response._content = json.dumps(
        {
            "access_token": "synthetic-access",
            "refresh_token": "synthetic-new-refresh",
            "id_token": credentials.id_token,
            "expires_in": 3600,
            "token_type": "Bearer",
            "scope": scopes,
        }
    ).encode()
    monkeypatch.setattr("requests.sessions.Session.request", lambda *args, **kwargs: response)
    return response


@pytest.mark.parametrize("intent", list(GoogleAuthIntent))
def test_real_oauthlib_scope_list(oidc, settings, monkeypatch, intent):
    service = GoogleSessionAuthService(MagicMock(), settings)
    flow = service._flow(intent)
    monkeypatch.setattr(service, "_flow", lambda requested_intent: flow)
    install_token_response(monkeypatch, oidc(), " ".join(flow.oauth2session.scope))
    monkeypatch.setattr(
        service,
        "_fetch_google_profile",
        lambda creds: {"google_id": "verified-subject-a", "email": "a@example.invalid"},
    )
    pending = PendingLogin("v" * 64, "expected-nonce", intent, None, None)
    assert (
        service._exchange_and_verify("synthetic-code", pending)[1].subject == "verified-subject-a"
    )
    assert isinstance(flow.oauth2session.token["scope"], list)
    assert flow.code_verifier == pending.verifier


@pytest.mark.parametrize(
    "scopes,accepted",
    [
        ("https://www.googleapis.com/auth/drive.readonly", True),
        (["https://www.googleapis.com/auth/drive.readonly"], True),
        (["openid", "https://www.googleapis.com/auth/drive.readonly", "unrelated.scope"], True),
        ("openid https://www.googleapis.com/auth/drive.readonly unrelated.scope", True),
        (Ellipsis, False),
        (None, False),
        ("", False),
        ("   ", False),
        ([], False),
        ("openid", False),
        (["openid"], False),
        ("https://www.googleapis.com/auth/drive.readonly.extra", False),
        ({"https://www.googleapis.com/auth/drive.readonly": True}, False),
        (123, False),
        ([None], False),
        ([123], False),
        ([[]], False),
        (["https://www.googleapis.com/auth/drive.readonly", ""], False),
        (["https://www.googleapis.com/auth/drive.readonly", "malformed scope"], False),
        (["https://www.googleapis.com/auth/drive.readonly", "\x00"], False),
        (["https://www.googleapis.com/auth/drive.readonly", 'bad"scope'], False),
        (["https://www.googleapis.com/auth/drive.readonly", "bad\\scope"], False),
        (["https://www.googleapis.com/auth/drive.readonly", "\u00e9"], False),
    ],
)
def test_granted_scope_representations(oidc, settings, monkeypatch, scopes, accepted):
    service = GoogleSessionAuthService(MagicMock(), settings)
    flow = MagicMock()
    # Requested scopes are not evidence that Google actually granted Drive access.
    signed = oidc()
    flow.credentials = Credentials(
        token=signed.token, id_token=signed.id_token, scopes=[settings.google_drive_scopes]
    )
    flow.oauth2session.token = {} if scopes is Ellipsis else {"scope": scopes}
    monkeypatch.setattr(service, "_flow", lambda intent: flow)
    monkeypatch.setattr(
        service,
        "_fetch_google_profile",
        lambda creds: {"google_id": "verified-subject-a", "email": "a@example.invalid"},
    )
    pending = PendingLogin("v" * 64, "expected-nonce", GoogleAuthIntent.CONNECT_DRIVE, None, None)
    if accepted:
        service._exchange_and_verify("synthetic-code", pending)
    else:
        with pytest.raises(GoogleLoginRejected):
            service._exchange_and_verify("synthetic-code", pending)


def test_all_configured_drive_scopes_required(oidc, settings, monkeypatch):
    settings.google_drive_scopes += " https://example.invalid/second-required-scope"
    service = GoogleSessionAuthService(MagicMock(), settings)
    flow = MagicMock()
    flow.credentials = oidc()
    flow.oauth2session.token = {"scope": "https://www.googleapis.com/auth/drive.readonly"}
    monkeypatch.setattr(service, "_flow", lambda intent: flow)
    monkeypatch.setattr(
        service,
        "_fetch_google_profile",
        lambda creds: {"google_id": "verified-subject-a", "email": "a@example.invalid"},
    )
    pending = PendingLogin("v" * 64, "expected-nonce", GoogleAuthIntent.CONNECT_DRIVE, None, None)
    with pytest.raises(GoogleLoginRejected):
        service._exchange_and_verify("synthetic-code", pending)


@pytest.mark.parametrize("representation", ["string", "list"])
def test_real_parser_additional_scopes(oidc, settings, monkeypatch, representation):
    monkeypatch.delenv("OAUTHLIB_RELAX_TOKEN_SCOPE", raising=False)
    service = GoogleSessionAuthService(MagicMock(), settings)
    flow = service._flow(GoogleAuthIntent.CONNECT_DRIVE)
    requested = list(flow.oauth2session.scope)
    granted = requested + ["https://www.googleapis.com/auth/calendar.readonly"]
    install_token_response(
        monkeypatch, oidc(), " ".join(granted) if representation == "string" else granted
    )
    monkeypatch.setattr(service, "_flow", lambda intent: flow)
    monkeypatch.setattr(
        service,
        "_fetch_google_profile",
        lambda creds: {"google_id": "verified-subject-a", "email": "a@example.invalid"},
    )
    pending = PendingLogin("v" * 64, "expected-nonce", GoogleAuthIntent.CONNECT_DRIVE, None, None)
    assert (
        service._exchange_and_verify("synthetic-code", pending)[1].subject == "verified-subject-a"
    )
    assert set(flow.oauth2session.token["scope"]) == set(granted)
    assert flow.code_verifier == pending.verifier
    import os

    assert "OAUTHLIB_RELAX_TOKEN_SCOPE" not in os.environ


def test_unmodified_oauthlib_raises_scope_warning(oidc, settings, monkeypatch):
    monkeypatch.delenv("OAUTHLIB_RELAX_TOKEN_SCOPE", raising=False)
    service = GoogleSessionAuthService(MagicMock(), settings)
    flow = service._flow(GoogleAuthIntent.CONNECT_DRIVE)
    scopes = list(flow.oauth2session.scope) + ["https://example.invalid/extra"]
    install_token_response(monkeypatch, oidc(), " ".join(scopes))
    flow.code_verifier = "v" * 64
    with pytest.raises(Warning, match="Scope has changed"):
        flow.fetch_token(code="synthetic-code", timeout=20)


@pytest.mark.parametrize(
    "fault",
    [
        "missing-drive",
        "missing-scope",
        "empty",
        "null",
        "dict",
        "mixed-list",
        "empty-item",
        "whitespace-item",
        "prefix",
        "nonce",
        "identity",
        "oauth-error",
        "missing-access-token",
        "transport",
        "unrelated-warning",
    ],
)
def test_real_parser_rejects_invalid_incremental_response(oidc, settings, monkeypatch, fault):
    import requests

    service = GoogleSessionAuthService(MagicMock(), settings)
    flow = service._flow(GoogleAuthIntent.CONNECT_DRIVE)
    scopes = list(flow.oauth2session.scope) + ["https://example.invalid/extra"]
    credentials = oidc(nonce="wrong-nonce") if fault == "nonce" else oidc()
    response = install_token_response(monkeypatch, credentials, " ".join(scopes))
    payload = json.loads(response.content)
    if fault == "missing-drive":
        payload["scope"] = " ".join(s for s in scopes if s != settings.google_drive_scopes)
    elif fault == "missing-scope":
        payload.pop("scope")
    elif fault in {"empty", "null", "dict", "mixed-list", "empty-item", "whitespace-item"}:
        payload["scope"] = {
            "empty": "",
            "null": None,
            "dict": {"scope": True},
            "mixed-list": scopes + [123],
            "empty-item": scopes + [""],
            "whitespace-item": scopes + ["bad scope"],
        }[fault]
    elif fault == "prefix":
        payload["scope"] = " ".join(
            s + ".extra" if s == settings.google_drive_scopes else s for s in scopes
        )
    elif fault == "oauth-error":
        payload["error"] = "invalid_grant"
    elif fault == "missing-access-token":
        payload.pop("access_token")
    response._content = json.dumps(payload).encode()
    parser = flow.oauth2session._client.parse_request_body_response
    parser_errors = []

    def observed_parser(*args, **kwargs):
        try:
            return parser(*args, **kwargs)
        except Exception as exc:
            parser_errors.append(type(exc).__name__)
            raise

    monkeypatch.setattr(flow.oauth2session._client, "parse_request_body_response", observed_parser)
    if fault == "transport":

        def fail(*args, **kwargs):
            raise requests.exceptions.ConnectionError("synthetic transport failure")

        monkeypatch.setattr("requests.sessions.Session.request", fail)
    if fault == "unrelated-warning":

        def fail(*args, **kwargs):
            raise Warning("synthetic unrelated warning")

        monkeypatch.setattr(flow, "fetch_token", fail)
    monkeypatch.setattr(service, "_flow", lambda intent: flow)
    monkeypatch.setattr(
        service,
        "_fetch_google_profile",
        lambda creds: {
            "google_id": "different-subject" if fault == "identity" else "verified-subject-a",
            "email": "a@example.invalid",
        },
    )
    pending = PendingLogin("v" * 64, "expected-nonce", GoogleAuthIntent.CONNECT_DRIVE, None, None)
    with pytest.raises(GoogleLoginRejected):
        service._exchange_and_verify("synthetic-code", pending)
    if fault in {"oauth-error", "missing-access-token"}:
        assert parser_errors == [
            "InvalidGrantError" if fault == "oauth-error" else "MissingTokenError"
        ]
