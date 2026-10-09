"""Bounded credentials, cookies and request-origin checks for future routes."""

import base64
import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

from pydantic import SecretStr
from starlette.responses import Response

from app.core.config import Settings

_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}", re.ASCII)
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class InvalidApplicationSession(ValueError):
    def __init__(self) -> None:
        super().__init__("Your application session is invalid or expired.")


class SessionStoreUnavailable(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Application sessions are temporarily unavailable.")


class InvalidSessionRequest(ValueError):
    def __init__(self) -> None:
        super().__init__("Application session request could not be verified.")


class SessionSecurityConfigurationError(ValueError):
    def __init__(self) -> None:
        super().__init__("Application session security configuration is unavailable.")


def encode_token(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def parse_token(value: str | None) -> bytes:
    """Accept only canonical encodings of exactly 32 random bytes, not UUIDs."""
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        raise InvalidApplicationSession()
    decoded = base64.urlsafe_b64decode(value + "=")
    if len(decoded) != 32 or encode_token(decoded) != value:
        raise InvalidApplicationSession()
    return decoded


def credential_digest(value: str | None) -> bytes:
    return hashlib.sha256(parse_token(value)).digest()


def verify_csrf_secret(secret: bytes, value: str | None) -> None:
    try:
        supplied = parse_token(value)
    except InvalidApplicationSession:
        raise InvalidSessionRequest() from None
    if len(secret) != 32 or not hmac.compare_digest(secret, supplied):
        raise InvalidSessionRequest()


def _origin(value: str, *, configured: bool = False) -> tuple[str, str, int]:
    try:
        if (
            not value
            or len(value) > 2048
            or any(c.isspace() for c in value)
            or "?" in value
            or "#" in value
        ):
            raise ValueError()
        parsed = urlsplit(value)
        if (
            parsed.scheme not in ("https", "http")
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in (("", "/") if configured else ("",))
        ):
            raise ValueError()
        host = parsed.hostname.encode("idna").decode("ascii").lower()
        if not re.fullmatch(r"[a-z0-9.-]+|::1", host, re.ASCII):
            raise ValueError()
        port = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
        if not 1 <= port <= 65535:
            raise ValueError()
        return parsed.scheme, host, port
    except (ValueError, UnicodeError):
        raise InvalidSessionRequest() from None


def trusted_origin(settings: Settings) -> tuple[str, str, int]:
    try:
        origin = _origin(settings.frontend_url, configured=True)
    except InvalidSessionRequest:
        raise SessionSecurityConfigurationError() from None
    if origin[0] == "http" and not (
        settings.app_env == "development" and settings.debug and origin[1] in _LOCAL_HOSTS
    ):
        raise SessionSecurityConfigurationError()
    return origin


def verify_origin(value: str | None, settings: Settings) -> None:
    expected = trusted_origin(settings)
    if not isinstance(value, str) or _origin(value) != expected:
        raise InvalidSessionRequest()


@dataclass(frozen=True)
class SessionCookiePolicy:
    name: str
    secure: bool


def session_cookie_policy(settings: Settings) -> SessionCookiePolicy:
    secure = trusted_origin(settings)[0] == "https"
    realm = "demo-session" if settings.demo_mode else "session"
    return SessionCookiePolicy(
        name=f"__Host-drivemind-{realm}" if secure else f"drivemind-local-{realm}",
        secure=secure,
    )


def set_session_cookie(
    response: Response,
    *,
    credential: SecretStr,
    expires_at: datetime,
    settings: Settings,
) -> None:
    """The future issuer sends the bearer ONLY as an HttpOnly cookie, never JSON."""
    parse_token(credential.get_secret_value())
    if expires_at.tzinfo is None or expires_at <= datetime.now(UTC):
        raise InvalidApplicationSession()
    policy = session_cookie_policy(settings)
    response.set_cookie(
        policy.name,
        credential.get_secret_value(),
        expires=expires_at.astimezone(UTC),
        secure=policy.secure,
        httponly=True,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response, *, settings: Settings) -> None:
    policy = session_cookie_policy(settings)
    response.delete_cookie(
        policy.name,
        path="/",
        secure=policy.secure,
        httponly=True,
        samesite="lax",
    )
