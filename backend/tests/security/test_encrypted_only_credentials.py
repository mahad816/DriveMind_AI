"""Final schema and real PostgreSQL grant/refresh fencing. Synthetic data only."""

import asyncio
import base64
import json
import threading
from datetime import UTC, datetime, timedelta
from uuid import uuid4
from unittest.mock import patch

import pytest
from google.auth.transport import Response
from pydantic import SecretStr
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from tests.credential_fixtures import secret_value

from app.db.models.google_oauth_token import GoogleOAuthToken
from app.services.google_credential_repository import (
    GoogleCredentialRepository,
    CredentialRecordChanged,
    CredentialRecoveryRequired,
    CredentialRefreshBusy,
    CredentialStoreUnavailable,
)
from app.services.google_credential_service import GoogleCredentialService
from .conftest import USER_A, USER_B, apply_revision

OLD = "20261010_1200"
NEW = "20261011_1200"


@pytest.fixture
async def final_engine(pg_engine: AsyncEngine):
    async with pg_engine.begin() as connection:
        await connection.run_sync(apply_revision, "20261009_1300")
        await connection.run_sync(apply_revision, OLD)
        await connection.run_sync(apply_revision, NEW)
        # Job-model columns used by all current services. This additive revision
        # is independent of the Drive constraint under test in owner_engine.
        await connection.run_sync(apply_revision, "20261012_1200")
    return pg_engine


@pytest.fixture
def keys(settings):
    settings.google_credential_encryption_keyring = SecretStr(
        json.dumps({"test": base64.urlsafe_b64encode(bytes([1]) * 32).decode()})
    )
    settings.google_credential_encryption_active_key_id = "test"
    settings.google_client_id = "synthetic-client"
    settings.google_client_secret = "synthetic-client-secret"
    return settings


async def grant(factory, keys, owner=USER_A, refresh="synthetic-refresh"):
    async with factory() as db:
        record = await GoogleCredentialRepository(db, keys).write_verified_grant(
            owner,
            access_token=SecretStr("synthetic-access"),
            refresh_token=SecretStr(refresh) if refresh else None,
            token_expiry=datetime.now(UTC) - timedelta(hours=1),
            scopes="readonly",
        )
        await db.commit()
        return record


@pytest.mark.asyncio
async def test_schema_and_safe_downgrade(final_engine: AsyncEngine):
    async with final_engine.begin() as connection:
        columns = await connection.run_sync(
            lambda c: {v["name"] for v in inspect(c).get_columns("google_oauth_tokens")}
        )
        assert "access_token" not in columns and "refresh_token" not in columns
        assert "encrypted_credentials" in columns
        await connection.run_sync(apply_revision, NEW, downgrade=True)
        await connection.run_sync(apply_revision, NEW)
        assert await connection.scalar(text("SELECT count(*) FROM users")) == 3


@pytest.mark.asyncio
async def test_populated_migration_refuses_and_rolls_back(pg_engine: AsyncEngine):
    async with pg_engine.begin() as connection:
        await connection.run_sync(apply_revision, "20261009_1300")
        await connection.run_sync(apply_revision, OLD)
        await connection.execute(
            text(
                "INSERT INTO google_oauth_tokens (id,user_id,access_token,refresh_token,scopes) VALUES (:id,:owner,'synthetic-access','synthetic-refresh','readonly')"
            ),
            {"id": uuid4(), "owner": USER_A},
        )
    with pytest.raises(Exception):
        async with pg_engine.begin() as connection:
            await connection.run_sync(apply_revision, NEW)
    async with pg_engine.connect() as connection:
        assert await connection.scalar(text("SELECT count(*) FROM google_oauth_tokens")) == 1
        assert await connection.scalar(text("SELECT count(*) FROM users")) == 3
        assert "access_token" in await connection.run_sync(
            lambda c: {v["name"] for v in inspect(c).get_columns("google_oauth_tokens")}
        )


@pytest.mark.asyncio
async def test_owner_scope_reconnect_omission_rollback(final_engine, keys):
    factory = async_sessionmaker(final_engine, expire_on_commit=False)
    first = await grant(factory, keys)
    other = await grant(factory, keys, USER_B, "synthetic-other-refresh")
    async with factory() as db:
        repository = GoogleCredentialRepository(db, keys)
        before = await repository.load_encrypted(USER_A)
        assert secret_value(before.payload.refresh_token) == "synthetic-refresh"
        second = await repository.write_verified_grant(
            USER_A,
            access_token=SecretStr("synthetic-reconnect"),
            refresh_token=None,
            token_expiry=datetime.now(UTC) + timedelta(hours=1),
            scopes="readonly",
        )
        assert second.id == first.id and second.grant_epoch == 2
        await db.rollback()
    async with factory() as db:
        restored = await GoogleCredentialRepository(db, keys).load_encrypted(USER_A)
        assert restored.record.grant_epoch == 1
        assert (await GoogleCredentialRepository(db, keys).load_record(USER_B)).id == other.id


@pytest.mark.asyncio
async def test_claim_fencing_reconnect_and_late_result(final_engine, keys):
    factory = async_sessionmaker(final_engine, expire_on_commit=False)
    record = await grant(factory, keys)
    async with factory() as db:
        repository = GoogleCredentialRepository(db, keys)
        claim = await repository.claim_refresh(record)
        await db.commit()
        await repository.submit_refresh(claim)
        await db.commit()
    async with factory() as db:
        with pytest.raises(CredentialRefreshBusy):
            await GoogleCredentialRepository(db, keys).claim_refresh(record)
    replacement = await grant(factory, keys, refresh="synthetic-new-grant")
    assert replacement.id == record.id and replacement.grant_epoch == 2
    async with factory() as db:
        with pytest.raises(CredentialRecordChanged):
            await GoogleCredentialRepository(db, keys).complete_refresh(
                claim,
                access_token=SecretStr("synthetic-stale"),
                refresh_token=SecretStr("synthetic-stale-refresh"),
                token_expiry=datetime.now(UTC) + timedelta(hours=1),
                scopes="readonly",
            )
    async with factory() as db:
        result = await GoogleCredentialRepository(db, keys).load_encrypted(USER_A)
        assert secret_value(result.payload.refresh_token) == "synthetic-new-grant"


@pytest.mark.asyncio
async def test_expired_submitted_claim_not_stolen_and_late_completion_recovers(final_engine, keys):
    factory = async_sessionmaker(final_engine, expire_on_commit=False)
    record = await grant(factory, keys)
    async with factory() as db:
        repository = GoogleCredentialRepository(db, keys)
        claim = await repository.claim_refresh(record)
        await db.commit()
        await repository.submit_refresh(claim)
        await db.commit()
        row = await db.get(GoogleOAuthToken, record.id)
        assert row is not None
        row.refresh_claim_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
    async with factory() as db:
        with pytest.raises(CredentialRecoveryRequired):
            await GoogleCredentialRepository(db, keys).claim_refresh(record)
    async with factory() as db:
        result = await GoogleCredentialRepository(db, keys).complete_refresh(
            claim,
            access_token=SecretStr("synthetic-late"),
            refresh_token=None,
            token_expiry=datetime.now(UTC) + timedelta(hours=1),
            scopes="readonly",
        )
        await db.commit()
        assert result.record.id == record.id and result.record.grant_epoch == 1
        assert secret_value(result.payload.refresh_token) == "synthetic-refresh"
        assert result.record.grant_status == "ACTIVE" and result.record.refresh_claim_id is None


class FakeResponse(Response):
    def __init__(self, status=200, data=None):
        self._status = status
        self._data = (
            data
            if data is not None
            else {
                "access_token": "synthetic-refreshed",
                "refresh_token": "synthetic-rotated",
                "expires_in": 3600,
                "token_type": "Bearer",
            }
        )

    @property
    def status(self):
        return self._status

    @property
    def headers(self):
        return {}

    @property
    def data(self):
        return json.dumps(self._data).encode()


@pytest.mark.asyncio
async def test_sdk_refresh_late_thread_persists_after_caller_cancellation(final_engine, keys):
    factory = async_sessionmaker(final_engine, expire_on_commit=False)
    await grant(factory, keys)
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def network(*args, **kwargs):
        started.set()
        assert release.wait(5)
        assert kwargs["timeout"] == (5, 10)
        return FakeResponse()

    async with factory() as db:
        coordinator = GoogleCredentialService(db, keys)
        client = coordinator.client(await coordinator.load(USER_A))

        def work():
            try:
                return client._ensure_credentials()
            finally:
                finished.set()

        with patch("app.services.google_credential_service.Request", return_value=network):
            task = asyncio.create_task(asyncio.to_thread(work))
            try:
                assert await asyncio.to_thread(started.wait, 5)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                release.set()
                assert await asyncio.to_thread(finished.wait, 5)
            finally:
                release.set()
    async with factory() as db:
        result = await GoogleCredentialRepository(db, keys).load_encrypted(USER_A)
        assert result.record.credential_revision == 2
        assert secret_value(result.payload.refresh_token) == "synthetic-rotated"
        assert result.record.refresh_claim_id is None


@pytest.mark.asyncio
async def test_unrelated_index_data_and_cursor_survive_cutover(pg_engine):
    from app.db.models.drive_file import DriveFile
    from app.db.models.document import Document
    from app.db.models.drive_sync_state import DriveSyncState
    from app.db.enums import DriveFileStatus
    from sqlalchemy import insert

    file_id, document_id = uuid4(), uuid4()
    async with pg_engine.begin() as connection:
        await connection.execute(
            insert(DriveFile),
            {
                "id": file_id,
                "user_id": USER_A,
                "drive_file_id": "synthetic-file",
                "name": "synthetic.txt",
                "mime_type": "text/plain",
                "modified_at": datetime.now(UTC),
                "status": DriveFileStatus.INDEXED,
            },
        )
        await connection.execute(
            insert(Document),
            {
                "id": document_id,
                "drive_file_id": file_id,
                "extracted_text": "synthetic text",
                "extracted_text_hash": "synthetic-hash",
            },
        )
        await connection.execute(
            insert(DriveSyncState), {"user_id": USER_A, "changes_page_token": "synthetic-cursor"}
        )
        await connection.run_sync(apply_revision, "20261009_1300")
        await connection.run_sync(apply_revision, OLD)
        await connection.run_sync(apply_revision, NEW)
        assert await connection.scalar(text("SELECT count(*) FROM users")) == 3
        assert await connection.scalar(text("SELECT id FROM documents")) == document_id
        assert (
            await connection.scalar(text("SELECT changes_page_token FROM drive_sync_states"))
            == "synthetic-cursor"
        )
        assert await connection.scalar(text("SELECT status FROM drive_files")) == "INDEXED"


@pytest.mark.asyncio
async def test_populated_downgrade_never_exposes_tokens(final_engine, keys):
    factory = async_sessionmaker(final_engine, expire_on_commit=False)
    record = await grant(factory, keys)
    with pytest.raises(Exception):
        async with final_engine.begin() as connection:
            await connection.run_sync(apply_revision, NEW, downgrade=True)
    async with factory() as db:
        result = await GoogleCredentialRepository(db, keys).load_encrypted(USER_A)
        assert result.record.id == record.id
    async with final_engine.connect() as connection:
        assert "access_token" not in await connection.run_sync(
            lambda c: {v["name"] for v in inspect(c).get_columns("google_oauth_tokens")}
        )


@pytest.mark.asyncio
async def test_concurrent_refreshes_share_one_provider_call(final_engine, keys):
    factory = async_sessionmaker(final_engine, expire_on_commit=False)
    await grant(factory, keys)
    started, release = threading.Event(), threading.Event()
    calls = []

    def network(*args, **kwargs):
        calls.append(1)
        started.set()
        assert release.wait(5)
        return FakeResponse()

    async with factory() as db:
        service = GoogleCredentialService(db, keys)
        snapshot = await service.load(USER_A)
        first, second = service.client(snapshot), service.client(snapshot)
        with patch("app.services.google_credential_service.Request", return_value=network):
            a = asyncio.create_task(asyncio.to_thread(first._ensure_credentials))
            try:
                assert await asyncio.to_thread(started.wait, 5)
                b = asyncio.create_task(asyncio.to_thread(second._ensure_credentials))
                await asyncio.sleep(0.1)
                release.set()
                results = await asyncio.wait_for(asyncio.gather(a, b), 5)
            finally:
                release.set()
        assert len(calls) == 1
        assert [v.token for v in results] == ["synthetic-refreshed"] * 2


@pytest.mark.asyncio
async def test_late_refresh_cannot_overwrite_reconnect(final_engine, keys):
    from app.connectors.google_drive.client import DriveClientError

    factory = async_sessionmaker(final_engine, expire_on_commit=False)
    await grant(factory, keys)
    started, release = threading.Event(), threading.Event()

    def network(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return FakeResponse()

    async with factory() as db:
        service = GoogleCredentialService(db, keys)
        client = service.client(await service.load(USER_A))
        with patch("app.services.google_credential_service.Request", return_value=network):
            task = asyncio.create_task(asyncio.to_thread(client._ensure_credentials))
            try:
                assert await asyncio.to_thread(started.wait, 5)
                new = await grant(factory, keys, refresh="synthetic-reconnected-refresh")
                release.set()
                with pytest.raises(DriveClientError):
                    await asyncio.wait_for(task, 5)
            finally:
                release.set()
    async with factory() as db:
        result = await GoogleCredentialRepository(db, keys).load_encrypted(USER_A)
        assert result.record.grant_epoch == new.grant_epoch
        assert result.record.grant_status == "ACTIVE"
        assert secret_value(result.payload.refresh_token) == "synthetic-reconnected-refresh"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["invalid_grant", "timeout", "nonrotation", "before_send"])
async def test_provider_failure_and_refresh_outcome_states(final_engine, keys, kind, caplog):
    from app.connectors.google_drive.client import DriveClientError

    factory = async_sessionmaker(final_engine, expire_on_commit=False)
    await grant(factory, keys)

    class ProviderResponse(FakeResponse):
        def __init__(self):
            super().__init__(
                400 if kind == "invalid_grant" else 200,
                {"error": "invalid_grant", "error_description": "synthetic-secret-provider"}
                if kind == "invalid_grant"
                else {"access_token": "synthetic-new", "expires_in": 3600, "token_type": "Bearer"},
            )

    def network(*args, **kwargs):
        if kind == "timeout":
            raise TimeoutError("synthetic-secret-provider")
        return ProviderResponse()

    async with factory() as db:
        service = GoogleCredentialService(db, keys)
        client = service.client(await service.load(USER_A))
        with (
            patch("app.services.google_credential_service.Request", return_value=network),
            patch(
                "app.services.google_credential_service.GoogleCredentialService._submit",
                side_effect=CredentialStoreUnavailable(),
            )
            if kind == "before_send"
            else patch("app.services.google_credential_service.Request", return_value=network),
        ):
            if kind == "nonrotation":
                await asyncio.to_thread(client._ensure_credentials)
            else:
                with pytest.raises(DriveClientError) as caught:
                    await asyncio.to_thread(client._ensure_credentials)
                assert "synthetic-secret-provider" not in str(caught.value)
                if kind == "invalid_grant":
                    assert caught.value.category == "reauthorization_required"
    async with factory() as db:
        result = await GoogleCredentialRepository(db, keys).load_encrypted(USER_A)
        assert (
            result.record.grant_status
            == {
                "invalid_grant": "REAUTH_REQUIRED",
                "timeout": "RECOVERY_REQUIRED",
                "nonrotation": "ACTIVE",
                "before_send": "ACTIVE",
            }[kind]
        )
        assert secret_value(result.payload.refresh_token) == "synthetic-refresh"
    assert "synthetic-secret-provider" not in caplog.text


@pytest.mark.asyncio
async def test_sdk_401_implicit_refresh_persists_before_failed_drive_call(
    final_engine, keys, caplog
):
    import httplib2
    from google_auth_httplib2 import AuthorizedHttp
    from googleapiclient.errors import HttpError
    from unittest.mock import MagicMock
    from app.connectors.google_drive.client import DriveClientError

    factory = async_sessionmaker(final_engine, expire_on_commit=False)
    record = await grant(factory, keys)
    async with factory() as db:
        row = await db.get(GoogleOAuthToken, record.id)
        assert row is not None
        row.token_expiry = datetime.now(UTC) + timedelta(hours=1)
        await db.commit()

    class FakeHttp:
        def __init__(self):
            self.calls = 0

        def request(self, *args, **kwargs):
            self.calls += 1
            return httplib2.Response(
                {"status": "401" if self.calls == 1 else "403"}
            ), b'{"error":"synthetic-secret-provider"}'

    http = FakeHttp()
    network_calls = []

    def token_request(*args, **kwargs):
        network_calls.append(1)
        return FakeResponse()

    def build(*args, **kwargs):
        credentials = kwargs["credentials"]
        assert credentials.refresh_token is None
        authorized = AuthorizedHttp(credentials, http=http)

        def execute():
            response, content = authorized.request("https://example.invalid/drive")
            raise HttpError(response, content)

        service = MagicMock()
        service.files.return_value.get.return_value.execute.side_effect = execute
        return service

    async with factory() as db:
        service = GoogleCredentialService(db, keys)
        client = service.client(await service.load(USER_A))
        with (
            patch("app.services.google_credential_service.Request", return_value=token_request),
            patch("app.connectors.google_drive.client.build", side_effect=build),
        ):
            with pytest.raises(DriveClientError) as caught:
                await asyncio.to_thread(client.get_file_metadata, "synthetic-file")
        assert "synthetic-secret-provider" not in str(caught.value)
    async with factory() as db:
        result = await GoogleCredentialRepository(db, keys).load_encrypted(USER_A)
        assert secret_value(result.payload.refresh_token) == "synthetic-rotated"
        assert result.record.credential_revision == 2 and result.record.id == record.id
    assert len(network_calls) == 1 and http.calls == 2
    assert "synthetic-secret-provider" not in caplog.text


@pytest.mark.asyncio
async def test_process_restart_observer_does_not_retry_expired_submission(final_engine, keys):
    from app.connectors.google_drive.client import DriveClientError

    factory = async_sessionmaker(final_engine, expire_on_commit=False)
    record = await grant(factory, keys)
    async with factory() as db:
        repository = GoogleCredentialRepository(db, keys)
        claim = await repository.claim_refresh(record)
        await db.commit()
        await repository.submit_refresh(claim)
        await db.commit()
        row = await db.get(GoogleOAuthToken, record.id)
        assert row is not None
        row.refresh_claim_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
    # Fresh service/sessions have no in-memory worker state: persisted claim is authoritative.
    async with factory() as db:
        service = GoogleCredentialService(db, keys)
        with patch("app.services.google_credential_service.Request") as request:
            with pytest.raises(DriveClientError) as caught:
                await service.load(USER_A)
            request.assert_not_called()
        assert caught.value.category == "temporary_provider_failure"
        state = await GoogleCredentialRepository(db, keys).load_record(USER_A)
        assert state.refresh_claim_id == claim.id
        assert state.grant_status != "REAUTH_REQUIRED"


@pytest.mark.asyncio
async def test_old_refresh_cannot_resurrect_deleted_grant(final_engine, keys):
    from sqlalchemy import delete
    from app.services.google_credential_repository import CredentialNotFound

    factory = async_sessionmaker(final_engine, expire_on_commit=False)
    record = await grant(factory, keys)
    async with factory() as db:
        repository = GoogleCredentialRepository(db, keys)
        claim = await repository.claim_refresh(record)
        await db.commit()
        await repository.submit_refresh(claim)
        await db.commit()
    async with factory() as db:
        await db.execute(delete(GoogleOAuthToken).where(GoogleOAuthToken.user_id == USER_A))
        await db.commit()
        with pytest.raises(CredentialNotFound):
            await GoogleCredentialRepository(db, keys).complete_refresh(
                claim,
                access_token=SecretStr("synthetic-late"),
                refresh_token=None,
                token_expiry=datetime.now(UTC) + timedelta(hours=1),
                scopes="readonly",
            )
    new = await grant(factory, keys)
    assert new.id != record.id


@pytest.mark.asyncio
async def test_active_key_rotation_on_refresh(final_engine, keys):
    factory = async_sessionmaker(final_engine, expire_on_commit=False)
    record = await grant(factory, keys)
    old = json.loads(keys.google_credential_encryption_keyring.get_secret_value())["test"]
    keys.google_credential_encryption_keyring = SecretStr(
        json.dumps({"test": old, "next": base64.urlsafe_b64encode(bytes([2]) * 32).decode()})
    )
    keys.google_credential_encryption_active_key_id = "next"
    async with factory() as db:
        repository = GoogleCredentialRepository(db, keys)
        assert (await repository.load_encrypted(USER_A)).record.id == record.id
        claim = await repository.claim_refresh(record)
        await db.commit()
        await repository.submit_refresh(claim)
        await db.commit()
        refreshed = await repository.complete_refresh(
            claim,
            access_token=SecretStr("synthetic-new"),
            refresh_token=None,
            token_expiry=datetime.now(UTC) + timedelta(hours=1),
            scopes="readonly",
        )
        await db.commit()
        assert refreshed.record.encrypted_credentials.get_secret_value().startswith(
            "dm-google:v1:next:"
        )
        assert refreshed.record.grant_epoch == record.grant_epoch
        assert secret_value(refreshed.payload.refresh_token) == "synthetic-refresh"


@pytest.mark.asyncio
async def test_fresh_empty_schema_upgrade_all_migrations(pg_engine):
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from .conftest import BACKEND

    schema = "head_test_" + uuid4().hex
    async with pg_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        try:
            await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            config = Config(str(BACKEND / "alembic.ini"))
            config.set_main_option("path_separator", "os")
            scripts = ScriptDirectory.from_config(config)
            for revision in reversed(list(scripts.walk_revisions("base", NEW))):
                await connection.run_sync(apply_revision, revision.revision)
            assert await connection.scalar(text("SELECT count(*) FROM users")) == 0
            assert await connection.scalar(text("SELECT count(*) FROM google_oauth_tokens")) == 0
            columns = await connection.run_sync(
                lambda c: {v["name"] for v in inspect(c).get_columns("google_oauth_tokens")}
            )
            assert "access_token" not in columns and "refresh_token" not in columns
        finally:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "column,value",
    [
        ("grant_status", "INVALID"),
        ("credential_revision", 0),
        ("grant_epoch", 0),
        ("refresh_claim_state", "INVALID"),
    ],
)
async def test_real_grant_and_claim_constraints(final_engine, keys, column, value):
    from sqlalchemy.exc import IntegrityError

    factory = async_sessionmaker(final_engine, expire_on_commit=False)
    record = await grant(factory, keys)
    async with factory() as db:
        row = await db.get(GoogleOAuthToken, record.id)
        assert row is not None
        setattr(row, column, value)
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()


@pytest.mark.asyncio
async def test_legacy_oauth_callback_creates_ciphertext_for_verified_new_owner(final_engine, keys):
    from google.oauth2.credentials import Credentials
    from unittest.mock import AsyncMock
    from app.services.google_oauth_service import GoogleOAuthService
    from app.db.models.user import User
    from sqlalchemy import select

    factory = async_sessionmaker(final_engine, expire_on_commit=False)
    credentials = Credentials(
        token="synthetic-access", refresh_token="synthetic-refresh", scopes=["readonly"]
    )
    async with factory() as db:
        service = GoogleOAuthService(db, keys)
        with (
            patch.object(
                service, "_pop_code_verifier", new_callable=AsyncMock, return_value="verifier"
            ),
            patch.object(service, "_fetch_credentials", return_value=credentials),
            patch.object(
                service,
                "_fetch_google_profile",
                return_value={
                    "email": "new-owner@example.invalid",
                    "google_id": "verified-new-subject",
                },
            ),
        ):
            result = await service.handle_callback("synthetic-code", "synthetic-state")
        user = await db.scalar(select(User).where(User.id == result.user_id))
        assert user is not None and user.google_id == "verified-new-subject"
        stored = await GoogleCredentialRepository(db, keys).load_encrypted(user.id)
        assert "synthetic-access" not in stored.record.encrypted_credentials.get_secret_value()
        assert secret_value(stored.payload.refresh_token) == "synthetic-refresh"


@pytest.mark.asyncio
async def test_temporary_http_failure_never_retries_old_refresh_token(final_engine, keys):
    from app.connectors.google_drive.client import DriveClientError

    factory = async_sessionmaker(final_engine, expire_on_commit=False)
    await grant(factory, keys)
    calls = []

    def network(*args, **kwargs):
        calls.append(1)
        return FakeResponse(
            503,
            {"error": "temporarily_unavailable", "error_description": "synthetic-provider-secret"},
        )

    async with factory() as db:
        service = GoogleCredentialService(db, keys)
        client = service.client(await service.load(USER_A))
        with patch("app.services.google_credential_service.Request", return_value=network):
            with pytest.raises(DriveClientError) as caught:
                await asyncio.to_thread(client._ensure_credentials)
        assert caught.value.category == "temporary_provider_failure"
        assert "synthetic-provider-secret" not in str(caught.value)
    assert len(calls) == 1
    async with factory() as db:
        state = await GoogleCredentialRepository(db, keys).load_record(USER_A)
        assert state.grant_status == "RECOVERY_REQUIRED" and state.refresh_claim_id is not None


@pytest.mark.asyncio
async def test_new_coordinator_missing_keys_and_configuration_fail_before_provider(
    final_engine, keys
):
    from app.connectors.google_drive.client import DriveClientError

    factory = async_sessionmaker(final_engine, expire_on_commit=False)
    await grant(factory, keys)
    async with factory() as db:
        service = GoogleCredentialService(db, keys)
        snapshot = await service.load(USER_A)
        keys.google_client_secret = ""
        with patch("app.services.google_credential_service.Request") as request:
            with pytest.raises(DriveClientError) as caught:
                service.client(snapshot)
            request.assert_not_called()
        assert caught.value.category == "configuration_error"
        keys.google_credential_encryption_keyring = None
        with pytest.raises(DriveClientError) as caught:
            await service.load(USER_A)
        assert caught.value.category == "configuration_error"
        state = await GoogleCredentialRepository(db, keys).load_record(USER_A)
        assert state.refresh_claim_id is None and state.grant_status == "ACTIVE"
