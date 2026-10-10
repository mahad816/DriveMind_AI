"""Google credential encryption. No storage, network or key generation.

All identity arguments must come from trusted application code. Encryption does
not establish ownership, revoke Google grants or authenticate an API request.
"""

import base64
import json
import re
from dataclasses import dataclass, field
from typing import NoReturn, cast
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr

from app.core.config import Settings

MAX_KEYRING_CHARS = 8192
MAX_KEYS = 16
MAX_TOKEN_BYTES = 8192
MAX_PAYLOAD_BYTES = 16384
MAX_ENVELOPE_CHARS = 32768
_KEY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}", re.ASCII)
_BASE64 = re.compile(r"[A-Za-z0-9_-]+={0,2}", re.ASCII)
_FIELDS = {
    "version",
    "key_id",
    "provider",
    "user_id",
    "credential_id",
    "access_token",
    "refresh_token",
}


class CredentialCryptoError(RuntimeError):
    """Fixed messages only: never include values from settings or ciphertext."""

    message = "Google credential encryption failed."

    def __init__(self) -> None:
        super().__init__(self.message)


class MissingEncryptionConfiguration(CredentialCryptoError):
    message = "Google credential encryption is not configured."


class InvalidEncryptionConfiguration(CredentialCryptoError):
    message = "Google credential encryption configuration is invalid."


class UnknownEncryptionKey(CredentialCryptoError):
    message = "Google credential encryption key is unavailable."


class InvalidCredentialCiphertext(CredentialCryptoError):
    message = "Encrypted Google credentials are invalid."


class CredentialBindingMismatch(CredentialCryptoError):
    message = "Encrypted Google credential identity could not be verified."


class UnsupportedCredentialEnvelope(CredentialCryptoError):
    message = "Encrypted Google credential version is unsupported."


class InvalidCredentialPayload(CredentialCryptoError):
    message = "Google credential payload is invalid."


def _reject_constant(value: str) -> NoReturn:
    raise ValueError()


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def _json_object(value: str | bytes) -> dict[str, object]:
    parsed = json.loads(value, object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
    if not isinstance(parsed, dict):
        raise ValueError()
    return cast(dict[str, object], parsed)


def _canonical_base64(value: str) -> bytes:
    if not _BASE64.fullmatch(value):
        raise ValueError()
    raw = base64.b64decode(value, altchars=b"-_", validate=True)
    if base64.urlsafe_b64encode(raw).decode("ascii") != value:
        raise ValueError()
    return raw


def _token_value(token: SecretStr | None) -> str | None:
    if token is None:
        return None
    if not isinstance(token, SecretStr):
        raise InvalidCredentialPayload()
    value = token.get_secret_value()
    # Bound characters before allocating a UTF-8 copy or stripping input.
    if not 1 <= len(value) <= MAX_TOKEN_BYTES or not value.strip():
        raise InvalidCredentialPayload()
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError:
        raise InvalidCredentialPayload() from None
    if size > MAX_TOKEN_BYTES:
        raise InvalidCredentialPayload()
    return value


@dataclass(frozen=True)
class GoogleCredentialPayload:
    user_id: UUID = field(repr=False)
    credential_id: UUID = field(repr=False)
    access_token: SecretStr | None = field(default=None, repr=False)
    refresh_token: SecretStr | None = field(default=None, repr=False)
    provider: str = "google"

    def __post_init__(self) -> None:
        if (
            not isinstance(self.provider, str)
            or self.provider != "google"
            or not isinstance(self.user_id, UUID)
            or not isinstance(self.credential_id, UUID)
        ):
            raise InvalidCredentialPayload()
        access, refresh = _token_value(self.access_token), _token_value(self.refresh_token)
        if access is None and refresh is None:
            raise InvalidCredentialPayload()


class GoogleCredentialCrypto:
    """Explicitly constructed backend keyring; no singleton or automatic activation.

    Ciphertext age does not expire a stored Google grant. Google token expiry and
    application authorization are separate responsibilities of later integration.
    """

    __slots__ = ("_keys", "_active_key_id")

    def __init__(self, keyring: SecretStr | None, active_key_id: str) -> None:
        if keyring is None or (isinstance(keyring, SecretStr) and not keyring.get_secret_value()):
            raise MissingEncryptionConfiguration()
        if not active_key_id:
            raise MissingEncryptionConfiguration()
        if (
            not isinstance(keyring, SecretStr)
            or not isinstance(active_key_id, str)
            or not _KEY_ID.fullmatch(active_key_id)
        ):
            raise InvalidEncryptionConfiguration()
        raw = keyring.get_secret_value()
        if len(raw) > MAX_KEYRING_CHARS:
            raise InvalidEncryptionConfiguration()
        try:
            values = _json_object(raw)
            if not 1 <= len(values) <= MAX_KEYS:
                raise ValueError()
            keys: dict[str, Fernet] = {}
            for key_id, key in values.items():
                if not _KEY_ID.fullmatch(key_id) or not isinstance(key, str) or len(key) != 44:
                    raise ValueError()
                if len(_canonical_base64(key)) != 32:
                    raise ValueError()
                keys[key_id] = Fernet(key.encode("ascii"))
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise InvalidEncryptionConfiguration() from None
        if active_key_id not in keys:
            raise UnknownEncryptionKey()
        self._keys = keys
        self._active_key_id = active_key_id

    @classmethod
    def from_settings(cls, settings: Settings) -> "GoogleCredentialCrypto":
        return cls(
            settings.google_credential_encryption_keyring,
            settings.google_credential_encryption_active_key_id,
        )

    def encrypt(self, payload: GoogleCredentialPayload) -> SecretStr:
        if not isinstance(payload, GoogleCredentialPayload):
            raise InvalidCredentialPayload()
        data = {
            "version": 1,
            "key_id": self._active_key_id,
            "provider": payload.provider,
            "user_id": str(payload.user_id),
            "credential_id": str(payload.credential_id),
            "access_token": _token_value(payload.access_token),
            "refresh_token": _token_value(payload.refresh_token),
        }
        raw = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
        if len(raw) > MAX_PAYLOAD_BYTES:
            raise InvalidCredentialPayload()
        token = self._keys[self._active_key_id].encrypt(raw).decode("ascii")
        return SecretStr(f"dm-google:v1:{self._active_key_id}:{token}")

    def decrypt(
        self,
        envelope: str | SecretStr,
        *,
        user_id: UUID,
        credential_id: UUID,
        provider: str = "google",
    ) -> GoogleCredentialPayload:
        if (
            not isinstance(user_id, UUID)
            or not isinstance(credential_id, UUID)
            or not isinstance(provider, str)
            or provider != "google"
        ):
            raise CredentialBindingMismatch()
        value = envelope.get_secret_value() if isinstance(envelope, SecretStr) else envelope
        if not isinstance(value, str) or not 1 <= len(value) <= MAX_ENVELOPE_CHARS:
            raise InvalidCredentialCiphertext()
        parts = value.split(":")
        if len(parts) != 4 or parts[0] != "dm-google":
            raise InvalidCredentialCiphertext()
        _, version, key_id, token = parts
        if version != "v1":
            raise UnsupportedCredentialEnvelope()
        if not _KEY_ID.fullmatch(key_id):
            raise InvalidCredentialCiphertext()
        key = self._keys.get(key_id)
        if key is None:
            raise UnknownEncryptionKey()
        try:
            if len(token) < 100:
                raise ValueError()
            _canonical_base64(token)
            raw = key.decrypt(token.encode("ascii"))
            if len(raw) > MAX_PAYLOAD_BYTES:
                raise ValueError()
            data = _json_object(raw)
            if (
                set(data) != _FIELDS
                or type(data["version"]) is not int
                or data["version"] != 1
                or data["key_id"] != key_id
            ):
                raise ValueError()
            for name in ("provider", "user_id", "credential_id"):
                if not isinstance(data[name], str):
                    raise ValueError()
            # Exact canonical UUID strings prevent permissive alternate representations.
            if (
                data["provider"] != provider
                or data["user_id"] != str(user_id)
                or data["credential_id"] != str(credential_id)
            ):
                raise CredentialBindingMismatch()
            for name in ("access_token", "refresh_token"):
                if data[name] is not None and not isinstance(data[name], str):
                    raise ValueError()
            access, refresh = data["access_token"], data["refresh_token"]
            return GoogleCredentialPayload(
                user_id=user_id,
                credential_id=credential_id,
                provider=provider,
                access_token=SecretStr(access) if isinstance(access, str) else None,
                refresh_token=SecretStr(refresh) if isinstance(refresh, str) else None,
            )
        except CredentialBindingMismatch:
            raise
        except (
            InvalidToken,
            InvalidCredentialPayload,
            ValueError,
            TypeError,
            UnicodeError,
            RecursionError,
        ):
            raise InvalidCredentialCiphertext() from None
