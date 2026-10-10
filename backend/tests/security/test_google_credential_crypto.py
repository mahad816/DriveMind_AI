"""Synthetic-only Fernet, strict parser, record binding and inactive integration tests."""

import ast
import base64
import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from cryptography.fernet import Fernet
from google.oauth2.credentials import Credentials
from pydantic import SecretStr

from app.connectors.google_drive.client import DriveTokens
from app.core.config import Settings
from app.db.models.user import User
from app.main import create_app
from app.security.google_credential_crypto import (
    MAX_ENVELOPE_CHARS,
    MAX_KEYRING_CHARS,
    MAX_KEYS,
    MAX_PAYLOAD_BYTES,
    MAX_TOKEN_BYTES,
    CredentialBindingMismatch,
    CredentialCryptoError,
    GoogleCredentialCrypto,
    GoogleCredentialPayload,
    InvalidCredentialCiphertext,
    InvalidCredentialPayload,
    InvalidEncryptionConfiguration,
    MissingEncryptionConfiguration,
    UnknownEncryptionKey,
    UnsupportedCredentialEnvelope,
)
from app.services.google_oauth_service import GoogleOAuthService

# Deliberately public test material, never a deployment key or Google credential.
OLD_KEY = base64.urlsafe_b64encode(bytes([1]) * 32).decode()
NEW_KEY = base64.urlsafe_b64encode(bytes([2]) * 32).decode()
USER = UUID(int=101)
ROW = UUID(int=201)
ACCESS = "synthetic-access-token"
REFRESH = "synthetic-refresh-token"


def crypto(active: str = "old", keys: dict[str, str] | None = None) -> GoogleCredentialCrypto:
    return GoogleCredentialCrypto(SecretStr(json.dumps(keys or {"old": OLD_KEY})), active)


def payload(access: str | None = ACCESS, refresh: str | None = REFRESH) -> GoogleCredentialPayload:
    return GoogleCredentialPayload(
        USER,
        ROW,
        SecretStr(access) if access is not None else None,
        SecretStr(refresh) if refresh is not None else None,
    )


def decrypt(service: GoogleCredentialCrypto, encrypted: str | SecretStr) -> GoogleCredentialPayload:
    return service.decrypt(encrypted, user_id=USER, credential_id=ROW)


def authenticated_document(**changes: object) -> SecretStr:
    data = {
        "version": 1,
        "key_id": "old",
        "provider": "google",
        "user_id": str(USER),
        "credential_id": str(ROW),
        "access_token": ACCESS,
        "refresh_token": REFRESH,
    }
    data.update(changes)
    return authenticated_bytes(json.dumps(data).encode())


def authenticated_bytes(raw: bytes) -> SecretStr:
    return SecretStr("dm-google:v1:old:" + Fernet(OLD_KEY.encode()).encrypt(raw).decode())


@pytest.mark.parametrize(
    "access,refresh",
    [(ACCESS, REFRESH), (ACCESS, None), (None, REFRESH), ("a" * MAX_TOKEN_BYTES, None)],
)
def test_roundtrip_tokens_and_bounded_large_token(access: str | None, refresh: str | None):
    service = crypto()
    original = payload(access, refresh)
    encrypted = service.encrypt(original)
    assert decrypt(service, encrypted) == original
    assert encrypted.get_secret_value().startswith("dm-google:v1:old:")
    for token in (access, refresh):
        if token:
            assert token not in encrypted.get_secret_value()


def test_nondeterministic_authenticated_encryption():
    service = crypto()
    first, second = service.encrypt(payload()), service.encrypt(payload())
    assert first != second
    assert decrypt(service, first) == decrypt(service, second)


@pytest.mark.parametrize(
    "binding",
    [
        {"user_id": UUID(int=102)},
        {"credential_id": UUID(int=202)},
        {"provider": "other"},
        {"user_id": str(USER)},
        {"credential_id": None},
    ],
)
def test_wrong_expected_binding_rejected(binding: dict):
    expected = {"user_id": USER, "credential_id": ROW, "provider": "google"}
    expected.update(binding)
    service = crypto()
    with pytest.raises(CredentialBindingMismatch):
        service.decrypt(service.encrypt(payload()), **expected)


@pytest.mark.parametrize(
    "changes",
    [
        {"user_id": str(UUID(int=102))},
        {"credential_id": str(UUID(int=202))},
        {"provider": "other"},
        {"user_id": USER.hex},
    ],
)
def test_authenticated_payload_binding_is_checked(changes: dict):
    with pytest.raises(CredentialBindingMismatch):
        decrypt(crypto(), authenticated_document(**changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"version": True},
        {"version": 2},
        {"version": "1"},
        {"key_id": "new"},
        {"access_token": 7},
        {"refresh_token": {}},
        {"access_token": ""},
        {"access_token": None, "refresh_token": None},
        {"extra_field": "unexpected"},
        {"provider": None},
        {"user_id": None},
        {"credential_id": 1},
    ],
)
def test_authenticated_invalid_payload_rejected(changes: dict):
    with pytest.raises(InvalidCredentialCiphertext):
        decrypt(crypto(), authenticated_document(**changes))


@pytest.mark.parametrize(
    "raw",
    [
        b"not-json",
        b"[]",
        b"{}",
        b'{"version":1,"version":1}',
        b'{"version":NaN}',
        b"x" * (MAX_PAYLOAD_BYTES + 1),
    ],
)
def test_authenticated_invalid_or_oversized_plaintext_rejected(raw: bytes):
    with pytest.raises(InvalidCredentialCiphertext):
        decrypt(crypto(), authenticated_bytes(raw))


def test_wrong_key_and_corruption_are_rejected():
    encrypted = crypto().encrypt(payload())
    with pytest.raises(InvalidCredentialCiphertext):
        decrypt(crypto(keys={"old": NEW_KEY}), encrypted)
    prefix, token = encrypted.get_secret_value().rsplit(":", 1)
    raw = bytearray(base64.urlsafe_b64decode(token))
    raw[30] ^= 1
    tampered = prefix + ":" + base64.urlsafe_b64encode(raw).decode()
    with pytest.raises(InvalidCredentialCiphertext):
        decrypt(crypto(), tampered)


@pytest.mark.parametrize(
    "value",
    [
        ACCESS,
        "",
        "dm-google",
        "dm-google:v1:old",
        "dm-google:v1:old:",
        "other:v1:old:" + "A" * 100,
        "dm-google:v1:bad.id:" + "A" * 100,
        "dm-google:v1:old:" + "!" * 100,
        "dm-google:v1:old:" + "A" * 101,
        "dm-google:v1:old:" + "A" * 100 + "===",
        "x" * (MAX_ENVELOPE_CHARS + 1),
        None,
        b"dm-google:v1:old:invalid",
    ],
)
def test_plaintext_malformed_truncated_oversized_envelopes_rejected(value):
    with pytest.raises(InvalidCredentialCiphertext):
        decrypt(crypto(), value)


@pytest.mark.parametrize("version", ["v2", "v0", "v01", "", "synthetic-secret-version"])
def test_unknown_version_rejected_without_echo(version: str):
    encrypted = crypto().encrypt(payload()).get_secret_value().replace(":v1:", f":{version}:")
    with pytest.raises(UnsupportedCredentialEnvelope) as error:
        decrypt(crypto(), encrypted)
    assert "synthetic-secret-version" not in str(error.value)


def test_unknown_key_and_relabelled_header_rejected():
    encrypted = crypto().encrypt(payload()).get_secret_value()
    with pytest.raises(UnknownEncryptionKey):
        decrypt(crypto(), encrypted.replace(":old:", ":unknown:"))
    # Even aliases with identical key material cannot bypass authenticated key-ID binding.
    service = crypto(keys={"old": OLD_KEY, "alias": OLD_KEY})
    with pytest.raises(InvalidCredentialCiphertext):
        decrypt(service, encrypted.replace(":old:", ":alias:"))


@pytest.mark.parametrize(
    "raw",
    [
        "not-json",
        "[]",
        "{}",
        '{"old":42}',
        '{"old":null}',
        '{"old":{}}',
        json.dumps({"bad.id": OLD_KEY}),
        json.dumps({"a" * 33: OLD_KEY}),
        json.dumps({"old": "x" * 44}),
        json.dumps({"old": OLD_KEY.rstrip("=")}),
        json.dumps({"old": OLD_KEY + "="}),
        '{"old":"' + OLD_KEY + '","old":"' + NEW_KEY + '"}',
        json.dumps({"old": OLD_KEY[:-2] + "F="}),
        json.dumps({str(i): OLD_KEY for i in range(MAX_KEYS + 1)}),
        "x" * (MAX_KEYRING_CHARS + 1),
        '{"old":NaN}',
    ],
)
def test_malformed_duplicate_or_noncanonical_configuration_rejected(raw: str):
    with pytest.raises(InvalidEncryptionConfiguration) as failure:
        GoogleCredentialCrypto(SecretStr(raw), "old")
    assert OLD_KEY not in str(failure.value) and NEW_KEY not in repr(failure.value)


@pytest.mark.parametrize(
    "keyring,active,error",
    [
        (None, "", MissingEncryptionConfiguration),
        (SecretStr(""), "old", MissingEncryptionConfiguration),
        (SecretStr(json.dumps({"old": OLD_KEY})), "", MissingEncryptionConfiguration),
        (SecretStr(json.dumps({"old": OLD_KEY})), "missing", UnknownEncryptionKey),
        (SecretStr(json.dumps({"old": OLD_KEY})), "bad.id", InvalidEncryptionConfiguration),
        (json.dumps({"old": OLD_KEY}), "old", InvalidEncryptionConfiguration),
    ],
)
def test_missing_partial_untrusted_key_configuration(keyring, active, error):
    with pytest.raises(error):
        GoogleCredentialCrypto(keyring, active)


def test_old_key_read_new_key_write_and_retirement():
    original = crypto().encrypt(payload())
    rotated_service = crypto("new", {"old": OLD_KEY, "new": NEW_KEY})
    assert decrypt(rotated_service, original) == payload()
    rotated = rotated_service.encrypt(decrypt(rotated_service, original))
    assert rotated.get_secret_value().startswith("dm-google:v1:new:")
    assert decrypt(crypto("new", {"new": NEW_KEY}), rotated) == payload()
    with pytest.raises(UnknownEncryptionKey):
        decrypt(crypto("new", {"new": NEW_KEY}), original)


@pytest.mark.parametrize(
    "access,refresh",
    [
        ("", None),
        (None, None),
        ("   ", None),
        ("x" * (MAX_TOKEN_BYTES + 1), None),
        ("\ud800", None),
    ],
)
def test_invalid_plaintext_tokens_rejected_safely(access, refresh):
    with pytest.raises(InvalidCredentialPayload):
        payload(access, refresh)


def test_total_payload_budget_and_runtime_types():
    with pytest.raises(InvalidCredentialPayload):
        crypto().encrypt(payload("a" * MAX_TOKEN_BYTES, "b" * MAX_TOKEN_BYTES))
    with pytest.raises(InvalidCredentialPayload):
        GoogleCredentialPayload(USER, ROW, access_token=ACCESS)  # type: ignore[arg-type]
    with pytest.raises(InvalidCredentialPayload):
        GoogleCredentialPayload(str(USER), ROW, access_token=SecretStr(ACCESS))  # type: ignore[arg-type]
    with pytest.raises(InvalidCredentialPayload):
        GoogleCredentialPayload(USER, ROW, access_token=SecretStr(ACCESS), provider="other")
    with pytest.raises(InvalidCredentialPayload):
        crypto().encrypt({"access_token": ACCESS})  # type: ignore[arg-type]


def test_secret_safe_representations_errors_settings_and_drive_tokens(settings: Settings, caplog):
    settings.google_credential_encryption_keyring = SecretStr(json.dumps({"old": OLD_KEY}))
    settings.google_credential_encryption_active_key_id = "old"
    service = GoogleCredentialCrypto.from_settings(settings)
    original = payload()
    encrypted = service.encrypt(original)
    tokens = DriveTokens(ACCESS, REFRESH, datetime.now(UTC), "openid")
    visible = " ".join(
        (
            str(original),
            repr(original),
            str(encrypted),
            repr(encrypted),
            repr(service),
            repr(settings),
            settings.model_dump_json(),
            str(tokens),
            repr(tokens),
        )
    )
    for secret in (ACCESS, REFRESH, OLD_KEY, encrypted.get_secret_value()):
        assert secret not in visible
    assert "google_credential_encryption_keyring" not in settings.model_dump()
    assert tokens.access_token == ACCESS and tokens.refresh_token == REFRESH
    for error_type in (
        MissingEncryptionConfiguration,
        InvalidEncryptionConfiguration,
        UnknownEncryptionKey,
        InvalidCredentialCiphertext,
        CredentialBindingMismatch,
        UnsupportedCredentialEnvelope,
        InvalidCredentialPayload,
    ):
        error = error_type()
        assert isinstance(error, CredentialCryptoError)
        for secret in (ACCESS, REFRESH, OLD_KEY, encrypted.get_secret_value()):
            assert secret not in str(error) and secret not in repr(error)
    assert not caplog.records
    with pytest.raises(FrozenInstanceError):
        original.provider = "other"  # type: ignore[misc]


def test_app_without_keys_and_crypto_imports_stay_in_credential_boundary(settings: Settings):
    assert settings.google_credential_encryption_keyring is None
    assert settings.google_credential_encryption_active_key_id == ""
    assert create_app().routes
    with pytest.raises(MissingEncryptionConfiguration):
        GoogleCredentialCrypto.from_settings(settings)
    app_dir = Path(__file__).resolve().parents[2] / "app"
    for path in app_dir.rglob("*.py"):
        if path.name in {
            "google_credential_crypto.py",
            "google_credential_repository.py",
            "google_credential_service.py",
            "google_oauth_service.py",
        }:
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert "google_credential_crypto" not in (node.module or "")
            elif isinstance(node, ast.Import):
                assert all("google_credential_crypto" not in alias.name for alias in node.names)


async def test_existing_oauth_writer_uses_encrypted_repository(settings: Settings):
    from unittest.mock import patch
    from app.services.google_credential_repository import GoogleCredentialRepository

    db = AsyncMock()
    user = User(id=USER, google_id="verified-synthetic-subject", email="synthetic@example.invalid")
    with patch.object(
        GoogleCredentialRepository, "write_verified_grant", new_callable=AsyncMock
    ) as write:
        await GoogleOAuthService(db, settings)._upsert_token(
            user, Credentials(token=ACCESS, refresh_token=None, scopes=["openid"])
        )
    assert write.await_args is not None
    assert write.await_args.kwargs["access_token"].get_secret_value() == ACCESS
    assert write.await_args.kwargs["refresh_token"] is None
    assert write.await_args.args[0] == USER
    db.commit.assert_not_awaited()


def test_no_key_generation_and_safe_failure_logs(monkeypatch: pytest.MonkeyPatch, caplog):
    def forbidden():
        raise AssertionError("Application keys must never be generated automatically")

    monkeypatch.setattr(Fernet, "generate_key", forbidden)
    service = crypto()
    assert decrypt(service, service.encrypt(payload())) == payload()
    malformed = SecretStr('{"old":"' + ACCESS + '"}')
    with pytest.raises(InvalidEncryptionConfiguration):
        GoogleCredentialCrypto(malformed, "old")
    with pytest.raises(InvalidCredentialCiphertext):
        decrypt(service, REFRESH)
    with pytest.raises(CredentialBindingMismatch):
        service.decrypt(service.encrypt(payload()), user_id=UUID(int=102), credential_id=ROW)
    assert not caplog.records


def test_backend_environment_keyring_loading(settings: Settings, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GOOGLE_CREDENTIAL_ENCRYPTION_KEYRING", json.dumps({"old": OLD_KEY}))
    monkeypatch.setenv("GOOGLE_CREDENTIAL_ENCRYPTION_ACTIVE_KEY_ID", "old")
    configured = Settings()
    assert isinstance(configured.google_credential_encryption_keyring, SecretStr)
    service = GoogleCredentialCrypto.from_settings(configured)
    assert decrypt(service, service.encrypt(payload())) == payload()
    assert OLD_KEY not in repr(configured) and OLD_KEY not in configured.model_dump_json()


def test_malformed_keyring_does_not_activate_or_break_settings(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("GOOGLE_CREDENTIAL_ENCRYPTION_KEYRING", "invalid-synthetic-secret-json")
    monkeypatch.setenv("GOOGLE_CREDENTIAL_ENCRYPTION_ACTIVE_KEY_ID", "old")
    configured = Settings()
    assert "invalid-synthetic-secret-json" not in repr(configured)
    with pytest.raises(InvalidEncryptionConfiguration) as error:
        GoogleCredentialCrypto.from_settings(configured)
    assert "invalid-synthetic-secret-json" not in str(error.value)
