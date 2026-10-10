"""Disposable PostgreSQL migration, owner scope and inactive repository guarantees."""

import asyncio
import base64
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import event, func, insert, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.config import Settings
from app.db.models.google_oauth_token import GoogleOAuthToken
from app.db.models.user import User
from app.security.google_credential_crypto import (
    CredentialBindingMismatch,
    InvalidCredentialCiphertext,
    MissingEncryptionConfiguration,
)
from app.services.google_credential_repository import (
    CredentialNotFound,
    CredentialRecordChanged,
    CredentialStoreUnavailable,
    EncryptedCredentialsUnavailable,
    ExistingCredentialStorage,
    GoogleCredentialRepository,
    InvalidCredentialOwner,
    LegacyCredentialReadRejected,
    UnsafeCredentialDatabaseConfiguration,
)
from .conftest import USER_A, USER_B, apply_revision

REVISION = "20261010_1200"
KEY = base64.urlsafe_b64encode(bytes([1]) * 32).decode()
SCOPES = "https://www.googleapis.com/auth/drive.readonly"
EXPIRY = datetime(2030, 1, 1, tzinfo=UTC)


@pytest.fixture
async def credential_engine(pg_engine: AsyncEngine):
    async with pg_engine.begin() as connection:
        await connection.run_sync(apply_revision, "20261009_1300")
        await connection.run_sync(apply_revision, REVISION)
    return pg_engine


@pytest.fixture
def crypto_settings(settings: Settings):
    settings.google_credential_encryption_keyring = SecretStr(json.dumps({"test": KEY}))
    settings.google_credential_encryption_active_key_id = "test"
    return settings


async def write(repository: GoogleCredentialRepository, owner=USER_A, **kwargs):
    values = {
        "access_token": SecretStr("synthetic-access"),
        "refresh_token": SecretStr("synthetic-refresh"),
        "token_expiry": EXPIRY,
        "scopes": SCOPES,
    }
    values.update(kwargs)
    return await repository.write_encrypted_compatibility(owner, **values)


async def test_migration_preserves_legacy_values_ids_constraints_and_roundtrip(
    pg_engine: AsyncEngine,
):
    row_id = uuid4()
    async with pg_engine.begin() as connection:
        await connection.run_sync(apply_revision, "20261009_1300")
        await connection.execute(
            text(
                "INSERT INTO google_oauth_tokens (id,user_id,access_token,refresh_token,token_expiry,scopes) VALUES (:id,:owner,:access,:refresh,:expiry,:scopes)"
            ),
            {
                "id": row_id,
                "owner": USER_A,
                "access": "synthetic-old-access",
                "refresh": "synthetic-old-refresh",
                "expiry": EXPIRY,
                "scopes": SCOPES,
            },
        )
        before = (
            (await connection.execute(text("SELECT * FROM google_oauth_tokens"))).mappings().one()
        )
        await connection.run_sync(apply_revision, REVISION)
        after = (
            (await connection.execute(text("SELECT * FROM google_oauth_tokens"))).mappings().one()
        )
        assert after["encrypted_credentials"] is None
        assert {name: after[name] for name in before} == dict(before)
        columns = (
            (
                await connection.execute(
                    text(
                        "SELECT column_name, is_nullable, column_default, data_type FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='google_oauth_tokens'"
                    )
                )
            )
            .mappings()
            .all()
        )
        by_name = {column["column_name"]: column for column in columns}
        assert by_name["encrypted_credentials"]["data_type"] == "text"
        assert by_name["encrypted_credentials"]["is_nullable"] == "YES"
        assert by_name["encrypted_credentials"]["column_default"] is None
        assert by_name["access_token"]["is_nullable"] == "NO"
        assert by_name["refresh_token"]["is_nullable"] == "YES"
        await connection.execute(
            text("UPDATE google_oauth_tokens SET encrypted_credentials='synthetic-unused-envelope'")
        )
        await connection.run_sync(apply_revision, REVISION, downgrade=True)
        rolled_back = (
            (await connection.execute(text("SELECT * FROM google_oauth_tokens"))).mappings().one()
        )
        assert dict(rolled_back) == dict(before)
        await connection.run_sync(apply_revision, REVISION)
        assert (
            await connection.execute(text("SELECT encrypted_credentials FROM google_oauth_tokens"))
        ).scalar_one() is None


async def test_new_rows_owner_scope_uuid_binding_and_no_first_account(
    credential_engine: AsyncEngine, crypto_settings: Settings
):
    sessions = async_sessionmaker(credential_engine, expire_on_commit=False)
    async with sessions() as db:
        repo = GoogleCredentialRepository(db, crypto_settings)
        first = await write(repo)
        second = await write(repo, USER_B, access_token=SecretStr("synthetic-b-access"))
        await db.commit()
        assert first.id != second.id
        assert first.user_id == USER_A and second.user_id == USER_B
        assert (await repo.load_record(USER_A)).id == first.id
        assert (await repo.load_encrypted(USER_B)).payload.access_token == SecretStr(
            "synthetic-b-access"
        )
        a = await repo.load_encrypted(USER_A)
        assert a.payload.credential_id == first.id
        assert a.payload.user_id == USER_A and a.payload.provider == "google"
        assert a.payload.access_token == SecretStr("synthetic-access")
        assert a.record.scopes == SCOPES and a.record.token_expiry == EXPIRY
        assert await db.scalar(select(func.count()).select_from(GoogleOAuthToken)) == 2
        for owner in (None, str(USER_A), "first"):
            with pytest.raises(InvalidCredentialOwner):
                await repo.load_encrypted(owner)  # type: ignore[arg-type]
        with pytest.raises(CredentialNotFound):
            await repo.load_encrypted(uuid4())
        row = await db.get(GoogleOAuthToken, first.id)
        assert row is not None and row.user_id == USER_A
        # Compatibility mirror is intentional, not encrypted-only enforcement.
        assert row.access_token == "synthetic-access" and row.refresh_token == "synthetic-refresh"


async def test_explicit_legacy_read_and_upgrade_preserve_refresh_identity(
    credential_engine: AsyncEngine, crypto_settings: Settings
):
    row_id = uuid4()
    async with async_sessionmaker(credential_engine, expire_on_commit=False)() as db:
        db.add(
            GoogleOAuthToken(
                id=row_id,
                user_id=USER_A,
                access_token="synthetic-legacy-access",
                refresh_token="synthetic-legacy-refresh",
                token_expiry=EXPIRY,
                scopes=SCOPES,
            )
        )
        await db.commit()
        repo = GoogleCredentialRepository(db, crypto_settings)
        with pytest.raises(EncryptedCredentialsUnavailable):
            await repo.load_encrypted(USER_A)
        legacy = await repo.load_legacy(USER_A)
        assert legacy.payload.refresh_token == SecretStr("synthetic-legacy-refresh")
        with pytest.raises(EncryptedCredentialsUnavailable):
            await write(repo, refresh_token=None)
        upgraded = await write(
            repo,
            refresh_token=None,
            existing_storage=ExistingCredentialStorage.LEGACY,
            expected_record_id=row_id,
        )
        await db.commit()
        assert upgraded.id == row_id
        assert (
            await repo.load_encrypted(USER_A)
        ).payload.refresh_token == legacy.payload.refresh_token
        with pytest.raises(LegacyCredentialReadRejected):
            await repo.load_legacy(USER_A)
        changed = await write(
            repo,
            access_token=SecretStr("synthetic-new-access"),
            refresh_token=None,
            expected_record_id=row_id,
        )
        await db.commit()
        assert changed.id == row_id
        assert (
            await repo.load_encrypted(USER_A)
        ).payload.refresh_token == legacy.payload.refresh_token
        await write(repo, refresh_token=SecretStr("synthetic-replacement-refresh"))
        await db.commit()
        assert (await repo.load_encrypted(USER_A)).payload.refresh_token == SecretStr(
            "synthetic-replacement-refresh"
        )


@pytest.mark.parametrize("kind", ["owner", "row", "provider", "corrupt", "empty"])
async def test_unusable_ciphertext_never_falls_back_or_gets_overwritten(
    credential_engine: AsyncEngine, crypto_settings: Settings, kind: str
):
    async with async_sessionmaker(credential_engine, expire_on_commit=False)() as db:
        repo = GoogleCredentialRepository(db, crypto_settings)
        record = await write(repo)
        await db.commit()
        row = await db.get(GoogleOAuthToken, record.id)
        assert row is not None
        if kind == "owner":
            blob = repo.prepare_encrypted(
                USER_B, record.id, access_token=SecretStr("synthetic-other"), refresh_token=None
            ).get_secret_value()
        elif kind == "row":
            blob = repo.prepare_encrypted(
                USER_A, uuid4(), access_token=SecretStr("synthetic-other"), refresh_token=None
            ).get_secret_value()
        elif kind == "provider":
            data = {
                "version": 1,
                "key_id": "test",
                "provider": "other",
                "user_id": str(USER_A),
                "credential_id": str(record.id),
                "access_token": "synthetic-other",
                "refresh_token": None,
            }
            blob = (
                "dm-google:v1:test:"
                + Fernet(KEY.encode()).encrypt(json.dumps(data).encode()).decode()
            )
        else:
            blob = "dm-google:v1:test:corrupt" if kind == "corrupt" else ""
        row.encrypted_credentials = blob
        await db.commit()
        expected = (
            CredentialBindingMismatch
            if kind in {"owner", "row", "provider"}
            else InvalidCredentialCiphertext
        )
        with pytest.raises(expected):
            await repo.load_encrypted(USER_A)
        with pytest.raises(LegacyCredentialReadRejected):
            await repo.load_legacy(USER_A)
        with pytest.raises(expected):
            await write(repo, refresh_token=SecretStr("synthetic-new-refresh"))
        with pytest.raises(LegacyCredentialReadRejected):
            await write(repo, existing_storage=ExistingCredentialStorage.LEGACY)
        await db.rollback()
        row = await db.get(GoogleOAuthToken, record.id)
        assert row is not None and row.encrypted_credentials == blob
        assert row.access_token == "synthetic-access" and row.refresh_token == "synthetic-refresh"


@pytest.mark.parametrize("key", [None, base64.urlsafe_b64encode(bytes([2]) * 32).decode()])
async def test_missing_wrong_keys_fail_closed(
    credential_engine: AsyncEngine, crypto_settings: Settings, key: str | None
):
    async with async_sessionmaker(credential_engine)() as db:
        repo = GoogleCredentialRepository(db, crypto_settings)
        await write(repo)
        await db.commit()
        crypto_settings.google_credential_encryption_keyring = (
            SecretStr(json.dumps({"test": key})) if key else None
        )
        expected = InvalidCredentialCiphertext if key else MissingEncryptionConfiguration
        with pytest.raises(expected):
            await repo.load_encrypted(USER_A)
        with pytest.raises(expected):
            await write(repo)
        with pytest.raises(LegacyCredentialReadRejected):
            await repo.load_legacy(USER_A)
        await db.rollback()


async def test_repository_never_commits_and_rollback_restores_updates(
    credential_engine: AsyncEngine, crypto_settings: Settings
):
    sessions = async_sessionmaker(credential_engine, expire_on_commit=False)
    async with sessions() as db:
        repo = GoogleCredentialRepository(db, crypto_settings)
        record = await write(repo)
        async with sessions() as observer:
            with pytest.raises(CredentialNotFound):
                await GoogleCredentialRepository(observer, crypto_settings).load_record(USER_A)
        await db.rollback()
        with pytest.raises(CredentialNotFound):
            await repo.load_record(USER_A)
        record = await write(repo)
        await db.commit()
        before = await repo.load_encrypted(USER_A)
        await write(repo, access_token=SecretStr("synthetic-uncommitted"), refresh_token=None)
        await db.rollback()
        after = await repo.load_encrypted(USER_A)
        assert after.record.id == record.id
        assert after.payload == before.payload
        assert after.record.encrypted_credentials == before.record.encrypted_credentials


async def test_expected_record_identity_rejects_replacement_and_missing_row(
    credential_engine: AsyncEngine, crypto_settings: Settings
):
    async with async_sessionmaker(credential_engine)() as db:
        repo = GoogleCredentialRepository(db, crypto_settings)
        with pytest.raises(CredentialRecordChanged):
            await write(repo, expected_record_id=uuid4())
        await db.rollback()
        original = await write(repo)
        await db.commit()
        with pytest.raises(CredentialRecordChanged):
            await write(repo, expected_record_id=uuid4())
        await db.rollback()
        assert (await repo.load_record(USER_A)).id == original.id


async def test_cooperating_same_owner_writers_serialize_creation_and_merge(
    credential_engine: AsyncEngine, crypto_settings: Settings
):
    sessions = async_sessionmaker(credential_engine, expire_on_commit=False)
    first_flushed, allow_commit = asyncio.Event(), asyncio.Event()

    async def first():
        async with sessions() as db:
            result = await write(GoogleCredentialRepository(db, crypto_settings))
            first_flushed.set()
            await allow_commit.wait()
            await db.commit()
            return result.id

    async def second():
        await first_flushed.wait()
        async with sessions() as db:
            await db.execute(text("SET LOCAL lock_timeout = '3s'"))
            result = await write(
                GoogleCredentialRepository(db, crypto_settings),
                access_token=SecretStr("synthetic-second-access"),
                refresh_token=None,
            )
            await db.commit()
            return result.id

    task1 = asyncio.create_task(first())
    await first_flushed.wait()
    task2 = asyncio.create_task(second())
    try:
        # Real owner row lock must stop the second writer before it can flush.
        await asyncio.sleep(0.05)
        assert not task2.done()
    finally:
        allow_commit.set()
    ids = await asyncio.gather(task1, task2)
    assert ids[0] == ids[1]
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(GoogleOAuthToken)) == 1
        result = await GoogleCredentialRepository(db, crypto_settings).load_encrypted(USER_A)
        assert result.payload.access_token == SecretStr("synthetic-second-access")
        assert result.payload.refresh_token == SecretStr("synthetic-refresh")


async def test_other_owner_can_commit_while_first_owner_is_uncommitted(
    credential_engine: AsyncEngine, crypto_settings: Settings
):
    sessions = async_sessionmaker(credential_engine)
    async with sessions() as a, sessions() as b:
        await write(GoogleCredentialRepository(a, crypto_settings))
        repo_b = GoogleCredentialRepository(b, crypto_settings)
        await asyncio.wait_for(write(repo_b, USER_B), timeout=3)
        await b.commit()
        await a.rollback()
        assert (await repo_b.load_record(USER_B)).user_id == USER_B
        with pytest.raises(CredentialNotFound):
            await repo_b.load_record(USER_A)


async def test_uniqueness_foreign_keys_and_plaintext_nullability_unchanged(
    credential_engine: AsyncEngine, crypto_settings: Settings
):
    async with async_sessionmaker(credential_engine)() as db:
        record = await write(GoogleCredentialRepository(db, crypto_settings))
        await db.commit()
        assert (
            await db.scalar(select(User.google_id).where(User.id == USER_A)) == "verified-subject-a"
        )
    for values in (
        {"user_id": USER_A, "access_token": "synthetic"},
        {"user_id": uuid4(), "access_token": "synthetic"},
        {"user_id": USER_B, "access_token": None},
    ):
        with pytest.raises(IntegrityError):
            async with credential_engine.begin() as connection:
                await connection.execute(
                    insert(GoogleOAuthToken).values(id=uuid4(), scopes=SCOPES, **values)
                )
    async with async_sessionmaker(credential_engine)() as db:
        assert (
            await GoogleCredentialRepository(db, crypto_settings).load_record(USER_A)
        ).id == record.id


async def test_secret_safe_snapshots_errors_sql_owner_predicate(
    credential_engine: AsyncEngine, crypto_settings: Settings, caplog
):
    statements: list[str] = []

    def observe(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)  # Intentionally NEVER capture parameter values.

    event.listen(credential_engine.sync_engine, "before_cursor_execute", observe)
    try:
        async with async_sessionmaker(credential_engine)() as db:
            repo = GoogleCredentialRepository(db, crypto_settings)
            record = await write(repo)
            await db.commit()
            snapshot = await repo.load_encrypted(USER_A)
            visible = repr(repo) + repr(record) + repr(snapshot) + repr(snapshot.payload)
            assert "synthetic-access" not in visible and "synthetic-refresh" not in visible
            assert record.encrypted_credentials is not None
            assert record.encrypted_credentials.get_secret_value() not in visible
            assert KEY not in visible
            for error in (
                CredentialNotFound(),
                CredentialStoreUnavailable(),
                CredentialRecordChanged(),
                UnsafeCredentialDatabaseConfiguration(),
            ):
                assert KEY not in repr(error) and "synthetic-access" not in str(error)
            assert not caplog.records
            token_selects = [
                s for s in statements if s.startswith("SELECT") and "FROM google_oauth_tokens" in s
            ]
            assert token_selects and all(
                "WHERE google_oauth_tokens.user_id =" in s for s in token_selects
            )
            assert all("LIMIT" not in s for s in token_selects)
    finally:
        event.remove(credential_engine.sync_engine, "before_cursor_execute", observe)


async def test_unsafe_database_logging_rejected_without_changing_engine(
    credential_engine: AsyncEngine, crypto_settings: Settings
):
    engine = credential_engine.sync_engine
    async with async_sessionmaker(credential_engine)() as db:
        repo = GoogleCredentialRepository(db, crypto_settings)
        original = engine.hide_parameters
        engine.hide_parameters = False
        try:
            with pytest.raises(UnsafeCredentialDatabaseConfiguration):
                await repo.load_record(USER_A)
        finally:
            engine.hide_parameters = original
        logger = logging.getLogger("sqlalchemy.engine.Engine")
        original_level = logger.level
        logger.setLevel(logging.DEBUG)
        try:
            with pytest.raises(UnsafeCredentialDatabaseConfiguration):
                await repo.load_record(USER_A)
        finally:
            logger.setLevel(original_level)


async def test_database_errors_are_sanitized(
    credential_engine: AsyncEngine, crypto_settings: Settings, monkeypatch: pytest.MonkeyPatch
):
    async with async_sessionmaker(credential_engine)() as db:
        repo = GoogleCredentialRepository(db, crypto_settings)
        monkeypatch.setattr(
            db,
            "scalar",
            AsyncMock(side_effect=SQLAlchemyError("synthetic-access sensitive SQL parameter")),
        )
        with pytest.raises(CredentialStoreUnavailable) as error:
            await repo.load_record(USER_A)
        assert "synthetic-access" not in str(error.value)
        assert "SQL parameter" not in repr(error.value)


def test_repository_is_not_imported_by_active_application_paths():
    import ast

    app_dir = Path(__file__).resolve().parents[2] / "app"
    for path in app_dir.rglob("*.py"):
        if path.name == "google_credential_repository.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert "google_credential_repository" not in (node.module or "")
            elif isinstance(node, ast.Import):
                assert all("google_credential_repository" not in name.name for name in node.names)


async def test_same_owner_lock_has_real_postgresql_blocking_boundary(
    credential_engine: AsyncEngine,
    crypto_settings: Settings,
):
    sessions = async_sessionmaker(credential_engine)
    async with sessions() as a, sessions() as b:
        original = await write(GoogleCredentialRepository(a, crypto_settings))
        await b.execute(text("SET LOCAL lock_timeout = '100ms'"))
        with pytest.raises(CredentialStoreUnavailable) as failure:
            await write(GoogleCredentialRepository(b, crypto_settings), refresh_token=None)
        assert "lock timeout" not in str(failure.value)
        await b.rollback()
        await a.commit()
        updated = await write(GoogleCredentialRepository(b, crypto_settings), refresh_token=None)
        await b.commit()
        assert updated.id == original.id


async def test_repository_does_not_autoflush_unrelated_owner_changes(
    credential_engine: AsyncEngine,
    crypto_settings: Settings,
):
    async with async_sessionmaker(credential_engine, expire_on_commit=False)() as db:
        repo = GoogleCredentialRepository(db, crypto_settings)
        beta = await write(repo, USER_B, access_token=SecretStr("synthetic-beta-access"))
        await db.commit()
        unrelated = await db.get(GoogleOAuthToken, beta.id)
        assert unrelated is not None
        unrelated.access_token = "synthetic-unrelated-pending-change"
        with pytest.raises(CredentialNotFound):
            await repo.load_record(USER_A)
        statement = (
            select(GoogleOAuthToken.access_token)
            .where(GoogleOAuthToken.user_id == USER_B)
            .execution_options(autoflush=False)
        )
        assert await db.scalar(statement) == "synthetic-beta-access"
        await write(repo, USER_A)
        assert await db.scalar(statement) == "synthetic-beta-access"
        assert unrelated in db.dirty
        await db.rollback()
        assert (await repo.load_encrypted(USER_B)).payload.access_token == SecretStr(
            "synthetic-beta-access"
        )


async def test_real_write_constraint_failure_is_safe_and_requires_caller_rollback(
    credential_engine: AsyncEngine,
    crypto_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
):
    async with async_sessionmaker(credential_engine, expire_on_commit=False)() as db:
        repo = GoogleCredentialRepository(db, crypto_settings)
        alpha = await write(repo)
        await db.commit()
        # Simulate a server-side UUID collision to exercise a real failed INSERT.
        monkeypatch.setattr("app.services.google_credential_repository.uuid4", lambda: alpha.id)
        with pytest.raises(CredentialStoreUnavailable) as failure:
            await write(repo, USER_B)
        assert "synthetic-access" not in str(failure.value)
        assert "synthetic-refresh" not in repr(failure.value)
        assert str(alpha.id) not in str(failure.value)
        await db.rollback()
        assert (await repo.load_encrypted(USER_A)).record.id == alpha.id
        with pytest.raises(CredentialNotFound):
            await repo.load_record(USER_B)
