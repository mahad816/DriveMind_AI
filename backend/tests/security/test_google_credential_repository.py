"""Encrypted-only repository constraints, binding and transaction guarantees."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.credential_fixtures import secret_value

from app.db.models.google_oauth_token import GoogleOAuthToken
from app.security.google_credential_crypto import (
    CredentialBindingMismatch,
    InvalidCredentialCiphertext,
    MissingEncryptionConfiguration,
)
from app.services.google_credential_repository import (
    GoogleCredentialRepository,
    CredentialNotFound,
    InvalidCredentialOwner,
)
from .conftest import USER_A, USER_B
from .test_encrypted_only_credentials import final_engine, keys, grant

__all__ = ["final_engine", "keys"]


@pytest.mark.asyncio
async def test_repository_encrypted_only_and_explicit_owner(final_engine, keys):
    factory = async_sessionmaker(final_engine, expire_on_commit=False)
    first = await grant(factory, keys)
    await grant(factory, keys, USER_B, "synthetic-b")
    async with factory() as db:
        repository = GoogleCredentialRepository(db, keys)
        assert not hasattr(repository, "load_legacy")
        assert not hasattr(repository, "write_encrypted_compatibility")
        assert not hasattr(GoogleOAuthToken, "access_token")
        assert not hasattr(GoogleOAuthToken, "refresh_token")
        for owner, error in [(uuid4(), CredentialNotFound), (None, InvalidCredentialOwner)]:
            with pytest.raises(error):
                await repository.load_encrypted(owner)
        result = await repository.load_encrypted(USER_A)
        assert result.record.id == first.id
        assert secret_value(result.payload.refresh_token) == "synthetic-refresh"
        assert "synthetic-" not in repr(result)
        assert "synthetic-" not in repr(result.record)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["owner", "row", "corruption", "key", "missing"])
async def test_unusable_encryption_fails_closed(final_engine, keys, mutation):
    factory = async_sessionmaker(final_engine, expire_on_commit=False)
    first = await grant(factory, keys)
    second = await grant(factory, keys, USER_B, "synthetic-b")
    async with factory() as db:
        repository = GoogleCredentialRepository(db, keys)
        row = await db.get(GoogleOAuthToken, first.id)
        assert row is not None
        if mutation == "owner":
            other_row = await db.get(GoogleOAuthToken, second.id)
            assert other_row is not None
            row.encrypted_credentials = other_row.encrypted_credentials
        elif mutation == "row":
            row.id = uuid4()
        elif mutation == "corruption":
            row.encrypted_credentials = "damaged-synthetic-ciphertext"
        elif mutation == "key":
            keys.google_credential_encryption_keyring = SecretStr(
                json.dumps({"test": "AgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgI="})
            )
        else:
            keys.google_credential_encryption_keyring = None
        await db.commit()
        with pytest.raises(
            (CredentialBindingMismatch, InvalidCredentialCiphertext, MissingEncryptionConfiguration)
        ) as caught:
            await repository.load_encrypted(USER_A)
        assert "synthetic-refresh" not in str(caught.value)


@pytest.mark.asyncio
async def test_real_foreign_key_unique_and_not_null_constraints(final_engine, keys):
    factory = async_sessionmaker(final_engine, expire_on_commit=False)
    record = await grant(factory, keys)
    for owner, encrypted in [
        (USER_A, record.encrypted_credentials.get_secret_value()),
        (uuid4(), record.encrypted_credentials.get_secret_value()),
        (USER_B, None),
    ]:
        async with factory() as db:
            db.add(
                GoogleOAuthToken(
                    id=uuid4(), user_id=owner, encrypted_credentials=encrypted, scopes="readonly"
                )
            )
            with pytest.raises(IntegrityError):
                await db.flush()
            await db.rollback()
    async with factory() as db:
        assert len((await db.scalars(select(GoogleOAuthToken))).all()) == 1


@pytest.mark.asyncio
async def test_concurrent_first_connections_preserve_one_stable_row(final_engine, keys):
    factory = async_sessionmaker(final_engine, expire_on_commit=False)
    first, second = await __import__("asyncio").gather(grant(factory, keys), grant(factory, keys))
    assert first.id == second.id
    assert sorted([first.grant_epoch, second.grant_epoch]) == [1, 2]


@pytest.mark.asyncio
async def test_expired_prepared_claim_can_retire_without_network(final_engine, keys):
    factory = async_sessionmaker(final_engine, expire_on_commit=False)
    record = await grant(factory, keys)
    async with factory() as db:
        repository = GoogleCredentialRepository(db, keys)
        old = await repository.claim_refresh(record)
        await db.commit()
        row = await db.get(GoogleOAuthToken, record.id)
        assert row is not None
        row.refresh_claim_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
        new = await repository.claim_refresh(record)
        assert new.id != old.id
        await db.commit()
        from app.services.google_credential_repository import CredentialRecordChanged

        with pytest.raises(CredentialRecordChanged):
            await repository.submit_refresh(old)


@pytest.mark.asyncio
async def test_demo_never_accesses_google_credentials(final_engine, keys):
    factory = async_sessionmaker(final_engine, expire_on_commit=False)
    await grant(factory, keys)
    keys.demo_mode = True
    async with factory() as db:
        with pytest.raises(InvalidCredentialOwner):
            await GoogleCredentialRepository(db, keys).load_encrypted(USER_A)


@pytest.mark.asyncio
async def test_unsafe_sql_logging_is_rejected_before_query(final_engine, keys, caplog):
    from app.services.google_credential_repository import UnsafeCredentialDatabaseConfiguration

    factory = async_sessionmaker(final_engine, expire_on_commit=False)
    await grant(factory, keys)
    final_engine.sync_engine.echo = True
    try:
        async with factory() as db:
            with pytest.raises(UnsafeCredentialDatabaseConfiguration):
                await GoogleCredentialRepository(db, keys).load_encrypted(USER_A)
    finally:
        final_engine.sync_engine.echo = False
    assert "synthetic-refresh" not in caplog.text


@pytest.mark.asyncio
async def test_wrong_provider_and_unknown_key_never_fall_back(final_engine, keys):
    from cryptography.fernet import Fernet
    from app.security.google_credential_crypto import CredentialCryptoError

    factory = async_sessionmaker(final_engine, expire_on_commit=False)
    record = await grant(factory, keys)
    key = json.loads(keys.google_credential_encryption_keyring.get_secret_value())["test"]
    inner = {
        "version": 1,
        "key_id": "test",
        "provider": "other",
        "user_id": str(USER_A),
        "credential_id": str(record.id),
        "access_token": "synthetic-access",
        "refresh_token": "synthetic-refresh",
    }
    encoded = Fernet(key.encode()).encrypt(json.dumps(inner).encode()).decode()
    async with factory() as db:
        row = await db.get(GoogleOAuthToken, record.id)
        assert row is not None
        row.encrypted_credentials = "dm-google:v1:test:" + encoded
        await db.commit()
        with pytest.raises(CredentialCryptoError):
            await GoogleCredentialRepository(db, keys).load_encrypted(USER_A)


@pytest.mark.asyncio
async def test_repository_rollback_and_different_owner_transactions(final_engine, keys):
    factory = async_sessionmaker(final_engine, expire_on_commit=False)
    first = await grant(factory, keys)
    async with factory() as a, factory() as b:
        changed = await GoogleCredentialRepository(a, keys).write_verified_grant(
            USER_A,
            access_token=SecretStr("synthetic-uncommitted"),
            refresh_token=SecretStr("synthetic-replacement"),
            token_expiry=datetime.now(UTC) + timedelta(hours=1),
            scopes="readonly",
        )
        assert changed.id == first.id
        # Other owner can commit while A retains its own owner/grant locks.
        await GoogleCredentialRepository(b, keys).write_verified_grant(
            USER_B,
            access_token=SecretStr("synthetic-b"),
            refresh_token=SecretStr("synthetic-b-refresh"),
            token_expiry=datetime.now(UTC) + timedelta(hours=1),
            scopes="readonly",
        )
        await b.commit()
        await a.rollback()
    async with factory() as db:
        assert (
            secret_value(
                (
                    await GoogleCredentialRepository(db, keys).load_encrypted(USER_A)
                ).payload.refresh_token
            )
            == "synthetic-refresh"
        )
        assert (
            secret_value(
                (
                    await GoogleCredentialRepository(db, keys).load_encrypted(USER_B)
                ).payload.refresh_token
            )
            == "synthetic-b-refresh"
        )


@pytest.mark.asyncio
async def test_invalid_internal_payload_never_partially_changes_grant(final_engine, keys):
    from app.security.google_credential_crypto import InvalidCredentialPayload

    factory = async_sessionmaker(final_engine, expire_on_commit=False)
    record = await grant(factory, keys)
    async with factory() as db:
        repository = GoogleCredentialRepository(db, keys)
        with pytest.raises(InvalidCredentialPayload):
            await repository.write_verified_grant(
                USER_A,
                access_token=SecretStr(""),
                refresh_token=SecretStr("synthetic-refresh"),
                token_expiry=datetime.now(UTC) + timedelta(hours=1),
                scopes="readonly",
            )
        # Even a caller continuing the transaction cannot flush half a replacement.
        await db.commit()
        loaded = await repository.load_encrypted(USER_A)
        assert loaded.record.credential_revision == record.credential_revision
        assert loaded.record.grant_epoch == record.grant_epoch
        assert secret_value(loaded.payload.access_token) == "synthetic-access"


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["missing", "revoked", "recovery", "claimed", "corrupt"])
async def test_omitted_refresh_requires_a_valid_unclaimed_same_grant(final_engine, keys, state):
    from app.services.google_credential_repository import CredentialReauthorizationRequired
    from app.security.google_credential_crypto import InvalidCredentialCiphertext

    factory = async_sessionmaker(final_engine, expire_on_commit=False)
    record = None
    if state != "missing":
        record = await grant(factory, keys)
    async with factory() as db:
        if record is not None:
            row = await db.get(GoogleOAuthToken, record.id)
            assert row is not None
            if state == "revoked":
                row.grant_status = "REAUTH_REQUIRED"
            elif state == "recovery":
                row.grant_status = "RECOVERY_REQUIRED"
            elif state == "claimed":
                row.refresh_claim_id = uuid4()
                row.refresh_claim_state = "SUBMITTED"
                row.refresh_claim_expires_at = datetime.now(UTC) + timedelta(seconds=30)
            else:
                row.encrypted_credentials = "synthetic-corrupt-envelope"
            await db.commit()
        with pytest.raises((CredentialReauthorizationRequired, InvalidCredentialCiphertext)):
            await GoogleCredentialRepository(db, keys).write_verified_grant(
                USER_A,
                access_token=SecretStr("synthetic-new"),
                refresh_token=None,
                token_expiry=datetime.now(UTC) + timedelta(hours=1),
                scopes="readonly",
            )
        await db.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["claim", "submit", "complete", "fail"])
async def test_refresh_sql_failures_have_fixed_safe_errors(final_engine, keys, operation):
    from unittest.mock import patch
    from sqlalchemy.exc import SQLAlchemyError
    from app.services.google_credential_repository import CredentialStoreUnavailable

    factory = async_sessionmaker(final_engine, expire_on_commit=False)
    record = await grant(factory, keys)
    async with factory() as db:
        repository = GoogleCredentialRepository(db, keys)
        claim = None
        if operation != "claim":
            claim = await repository.claim_refresh(record)
            await db.commit()
            if operation in {"complete", "fail"}:
                await repository.submit_refresh(claim)
                await db.commit()
        with patch.object(db, "flush", side_effect=SQLAlchemyError("synthetic-secret-sql-driver")):
            with pytest.raises(CredentialStoreUnavailable) as caught:
                if operation == "claim":
                    await repository.claim_refresh(record)
                elif operation == "submit":
                    assert claim is not None
                    await repository.submit_refresh(claim)
                elif operation == "complete":
                    assert claim is not None
                    await repository.complete_refresh(
                        claim,
                        access_token=SecretStr("synthetic-new"),
                        refresh_token=None,
                        token_expiry=datetime.now(UTC) + timedelta(hours=1),
                        scopes="readonly",
                    )
                else:
                    assert claim is not None
                    await repository.fail_refresh(claim)
        assert "synthetic-secret-sql-driver" not in str(caught.value)
        await db.rollback()
