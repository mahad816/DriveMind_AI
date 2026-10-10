"""Synthetic encrypted ORM fixtures; never use production credentials or settings."""

import base64
import json
from typing import Any
from uuid import uuid4

from pydantic import SecretStr

from app.core.config import Settings
from app.db.models.google_oauth_token import GoogleOAuthToken
from app.security.google_credential_crypto import GoogleCredentialCrypto, GoogleCredentialPayload

KEYRING = SecretStr(json.dumps({"test": base64.urlsafe_b64encode(bytes([1]) * 32).decode()}))


def synthetic_oauth_row(**values: Any) -> GoogleOAuthToken:
    credential_id = values.setdefault("id", uuid4())
    access = values.pop("access_token", "synthetic-access")
    refresh = values.pop("refresh_token", "synthetic-refresh")
    values.setdefault(
        "encrypted_credentials",
        GoogleCredentialCrypto(KEYRING, "test")
        .encrypt(
            GoogleCredentialPayload(
                values["user_id"],
                credential_id,
                SecretStr(access) if access else None,
                SecretStr(refresh) if refresh else None,
            )
        )
        .get_secret_value(),
    )
    values.setdefault("credential_revision", 1)
    values.setdefault("grant_epoch", 1)
    values.setdefault("grant_status", "ACTIVE")
    return GoogleOAuthToken(**values)


def configure_test_keys(settings: Settings) -> Settings:
    settings.google_credential_encryption_keyring = KEYRING
    settings.google_credential_encryption_active_key_id = "test"
    return settings


def secret_value(value: SecretStr | None) -> str:
    assert value is not None
    return value.get_secret_value()
