"""Real sessions, admission transactions, migration preservation and owner races."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from app.core.config import get_settings
from app.db.session import get_db
from app.db.enums import ApplicationSessionKind, IndexingJobStatus, IndexingOperation
from app.db.models.application_session import ApplicationSession
from app.db.models.drive_file import DriveFile
from app.db.models.indexing_job import IndexingJob
from app.main import create_app
from app.security.principal import VerifiedGoogleIdentity
from app.security.session_helpers import session_cookie_policy
from app.services.application_session_service import ApplicationSessionService
from app.services.indexing_job_service import (
    IndexingJobService,
    IndexingAdmissionConflict,
    IndexingStoreUnavailable,
)
from .conftest import USER_A, USER_B, apply_revision
from .test_encrypted_only_credentials import final_engine, keys, grant
from .test_owner_scoped_drive_identity import owner_engine

__all__ = ["final_engine", "owner_engine", "keys"]
REVISION = "20261012_1200"


@pytest.fixture
async def admission(owner_engine, keys):
    factory = async_sessionmaker(owner_engine, expire_on_commit=False)
    app = create_app()

    async def database():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_settings] = lambda: keys
    # Synthetic integration harness ONLY; production create_app never opens it.
    app.state.indexing_admission_ready = True
    # Admission-only tests do not dispatch jobs. Full real lifecycle supervision
    # and actual polling are exercised in test_indexing_lifecycle.py.
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def admission_scope(db):
        try:
            yield SimpleNamespace(authorize=lambda: None)
        finally:
            await db.close()

    app.state.indexing_supervisor = SimpleNamespace(
        admission=admission_scope, authorize_admission=AsyncMock(return_value=True)
    )
    sessions, headers, files = {}, {}, {}
    async with factory() as db:
        for uid, subject in ((USER_A, "verified-subject-a"), (USER_B, "verified-subject-b")):
            session = await ApplicationSessionService(db, keys).issue_google(
                VerifiedGoogleIdentity(subject)
            )
            token = await ApplicationSessionService(db, keys).csrf_token(
                session.credential.get_secret_value()
            )
            sessions[uid] = session
            headers[uid] = {
                "Origin": keys.frontend_url,
                "X-CSRF-Token": token.get_secret_value(),
                "Cookie": session_cookie_policy(keys).name
                + "="
                + session.credential.get_secret_value(),
            }
            file = DriveFile(
                user_id=uid,
                drive_file_id="shared-provider-id",
                name="shared.txt",
                mime_type="text/plain",
                modified_at=datetime.now(UTC),
            )
            db.add(file)
            await db.flush()
            files[uid] = file.id
        await db.commit()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://app.example.invalid"
    ) as client:
        yield SimpleNamespace(
            app=app,
            factory=factory,
            client=client,
            headers=headers,
            sessions=sessions,
            files=files,
            settings=keys,
        )


async def count_jobs(r):
    async with r.factory() as db:
        return len(list((await db.scalars(select(IndexingJob))).all()))


@pytest.mark.parametrize("stage", ["sync", "ingest", "chunk", "build"])
@pytest.mark.parametrize("state", ["missing", "malformed", "expired", "revoked", "wrong_kind"])
async def test_session_failures_precede_work(admission, monkeypatch, stage, state):
    r = admission
    provider = AsyncMock(side_effect=AssertionError("No provider boundary may be reached"))
    monkeypatch.setattr("app.services.drive_sync_service.DriveSyncService.is_connected", provider)
    headers = dict(r.headers[USER_A])
    if state == "missing":
        headers.pop("Cookie")
    elif state == "malformed":
        headers["Cookie"] = session_cookie_policy(r.settings).name + "=invalid"
    else:
        values = {"revoked_at": datetime.now(UTC)}
        if state == "expired":
            values = {
                "expires_at": datetime.now(UTC) - timedelta(days=1),
                "created_at": datetime.now(UTC) - timedelta(days=2),
            }
        if state == "wrong_kind":
            values = {"kind": ApplicationSessionKind.DEMO_VISITOR, "user_id": None}
        async with r.factory() as db:
            await db.execute(
                update(ApplicationSession)
                .where(ApplicationSession.id == r.sessions[USER_A].session_id)
                .values(**values)
            )
            await db.commit()
    response = await r.client.post("/api/v1/index/" + stage, headers=headers)
    assert response.status_code == 401, response.text
    assert await count_jobs(r) == 0
    provider.assert_not_called()


@pytest.mark.parametrize(
    "change", ["missing_origin", "foreign_origin", "missing_csrf", "wrong_csrf"]
)
async def test_mutation_protection(admission, change):
    r = admission
    headers = dict(r.headers[USER_A])
    if change == "missing_origin":
        headers.pop("Origin")
    if change == "foreign_origin":
        headers["Origin"] = "https://attacker.invalid"
    if change == "missing_csrf":
        headers.pop("X-CSRF-Token")
    if change == "wrong_csrf":
        headers["X-CSRF-Token"] = r.headers[USER_B]["X-CSRF-Token"]
    response = await r.client.post("/api/v1/index/build", headers=headers)
    assert response.status_code == 403 and await count_jobs(r) == 0


@pytest.mark.parametrize("stage", ["sync", "ingest", "chunk", "build"])
async def test_committed_inputs_and_exact_owner_poll(admission, stage):
    r = admission
    if stage in ("sync", "ingest"):
        await grant(r.factory, r.settings, USER_A)
    params = (
        {"user_id": str(USER_B), "full": "true"}
        if stage == "sync"
        else {"file_id": str(r.files[USER_A]), "user_id": str(USER_B)}
    )
    response = await r.client.post(
        "/api/v1/index/" + stage,
        params=params,
        headers=r.headers[USER_A],
        json={"user_id": str(USER_B)},
    )
    assert response.status_code == 202, response.text
    payload = response.json()
    assert payload["status"] == "queued"
    async with r.factory() as db:
        job = await db.get(IndexingJob, payload["job_id"])
        assert job is not None and job.user_id == USER_A and job.operation == stage.upper()
        assert job.status == IndexingJobStatus.QUEUED and job.started_at is None
        assert job.file_id == (None if stage == "sync" else r.files[USER_A])
        assert job.full_sync == (stage == "sync") and job.total == 0 and not job.recovery_required
    # No credentials are needed to see one's accepted job after disconnect.
    from app.db.models.google_oauth_token import GoogleOAuthToken

    async with r.factory() as db:
        await db.execute(delete(GoogleOAuthToken).where(GoogleOAuthToken.user_id == USER_A))
        await db.commit()
    response = await r.client.get(
        "/api/v1/index/status",
        params={"job_id": payload["job_id"], "user_id": str(USER_B)},
        headers=r.headers[USER_A],
    )
    assert response.status_code == 200 and response.json()["job"]["id"] == payload["job_id"]
    assert response.json()["connected"] is False
    foreign = await r.client.get(
        "/api/v1/index/status", params={"job_id": payload["job_id"]}, headers=r.headers[USER_B]
    )
    missing = await r.client.get(
        "/api/v1/index/status", params={"job_id": str(uuid4())}, headers=r.headers[USER_B]
    )
    assert foreign.status_code == missing.status_code == 404 and foreign.json() == missing.json()


@pytest.mark.parametrize("target", ["foreign", "missing", "deleted"])
async def test_target_never_becomes_all_files(admission, target):
    r = admission
    file_id = r.files[USER_B] if target == "foreign" else uuid4()
    if target == "deleted":
        file_id = r.files[USER_A]
        async with r.factory() as db:
            await db.execute(delete(DriveFile).where(DriveFile.id == file_id))
            await db.commit()
    response = await r.client.post(
        "/api/v1/index/chunk", params={"file_id": str(file_id)}, headers=r.headers[USER_A]
    )
    assert response.status_code == 404 and await count_jobs(r) == 0


async def test_gate_closed_even_with_valid_session(admission, monkeypatch):
    r = admission
    r.app.state.indexing_admission_ready = False
    provider = AsyncMock()
    monkeypatch.setattr("app.services.drive_sync_service.DriveSyncService.is_connected", provider)
    for stage in ("sync", "ingest", "chunk", "build"):
        response = await r.client.post("/api/v1/index/" + stage, headers=r.headers[USER_A])
        assert response.status_code == 503
    assert await count_jobs(r) == 0
    provider.assert_not_called()
    assert create_app().state.indexing_admission_ready is False


async def test_required_connection_is_owner_specific(admission):
    r = admission
    await grant(r.factory, r.settings, USER_B)
    for stage in ("sync", "ingest"):
        response = await r.client.post("/api/v1/index/" + stage, headers=r.headers[USER_A])
        assert response.status_code == 503
    assert await count_jobs(r) == 0


async def test_commit_failure_is_safe_503(admission, monkeypatch, caplog):
    r = admission

    async def fail(self):
        raise OperationalError(
            "synthetic-secret-statement", {}, Exception("synthetic-secret-password")
        )

    monkeypatch.setattr(AsyncSession, "commit", fail)
    response = await r.client.post("/api/v1/index/chunk", headers=r.headers[USER_A])
    assert response.status_code == 503 and "synthetic-secret" not in response.text
    assert "synthetic-secret" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
    assert await count_jobs(r) == 0


async def test_owner_concurrency_and_independence(admission):
    r = admission
    start = asyncio.Event()

    async def submit(uid):
        await start.wait()
        return await r.client.post("/api/v1/index/chunk", headers=r.headers[uid])

    tasks = [asyncio.create_task(submit(uid)) for uid in (USER_A, USER_A, USER_B)]
    start.set()
    responses = await asyncio.gather(*tasks)
    assert sorted(x.status_code for x in responses[:2]) == [202, 409]
    assert responses[2].status_code == 202
    assert await count_jobs(r) == 2


@pytest.mark.parametrize(
    "status", [IndexingJobStatus.QUEUED, IndexingJobStatus.RUNNING, IndexingJobStatus.FAILED]
)
async def test_database_exclusion_and_recovery(admission, status):
    r = admission
    async with r.factory() as db:
        db.add(
            IndexingJob(
                user_id=USER_A,
                operation=IndexingOperation.BUILD,
                status=status,
                recovery_required=status == IndexingJobStatus.FAILED,
            )
        )
        await db.commit()
    response = await r.client.post("/api/v1/index/chunk", headers=r.headers[USER_A])
    assert response.status_code == 409
    async with r.factory() as db:
        db.add(
            IndexingJob(
                user_id=USER_A, operation=IndexingOperation.CHUNK, status=IndexingJobStatus.QUEUED
            )
        )
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()


async def test_pending_and_historical_error_are_private(admission):
    r = admission
    async with r.factory() as db:
        db.add(
            IndexingJob(
                user_id=USER_A,
                status=IndexingJobStatus.FAILED,
                error="synthetic-credential-private",
            )
        )
        await db.commit()
    response = await r.client.get("/api/v1/index/status", headers=r.headers[USER_A])
    assert response.status_code == 200 and "synthetic-credential-private" not in response.text
    assert response.json()["job"]["error"]
    other = await r.client.get("/api/v1/index/status", headers=r.headers[USER_B])
    assert other.json()["job"] is None
    async with r.factory() as db:
        await db.execute(
            update(DriveFile).where(DriveFile.user_id == USER_B).values(status="skipped")
        )
        await db.commit()
    for uid, expected in ((USER_A, 1), (USER_B, 0)):
        response = await r.client.get(
            "/api/v1/index/pending",
            params={"user_id": str(USER_B if uid == USER_A else USER_A)},
            headers=r.headers[uid],
        )
        assert response.status_code == 200 and response.json()["to_ingest"] == expected


@pytest.mark.parametrize("path", ["status", "pending"])
async def test_reads_require_session(admission, path):
    assert (await admission.client.get("/api/v1/index/" + path)).status_code == 401


async def test_migration_preserves_unknown_jobs_and_refuses_loss(owner_engine):
    async with owner_engine.begin() as conn:
        await conn.run_sync(apply_revision, REVISION, downgrade=True)
        historical_id = uuid4()
        await conn.execute(
            text(
                "INSERT INTO indexing_jobs (id,user_id,status,error,started_at) VALUES (:id,:owner,'RUNNING',:error,now())"
            ),
            {"id": historical_id, "owner": USER_A, "error": "historical"},
        )
        before = (
            (
                await conn.execute(
                    text("SELECT * FROM indexing_jobs WHERE id=:id"), {"id": historical_id}
                )
            )
            .mappings()
            .one()
        )
        await conn.run_sync(apply_revision, REVISION)
        after = (
            (
                await conn.execute(
                    text("SELECT * FROM indexing_jobs WHERE id=:id"), {"id": historical_id}
                )
            )
            .mappings()
            .one()
        )
        assert all(after[key] == value for key, value in before.items())
        assert after["operation"] is None and not after["recovery_required"] and after["total"] == 0
    factory = async_sessionmaker(owner_engine, expire_on_commit=False)
    async with factory() as db:
        with pytest.raises(IndexingAdmissionConflict):
            await IndexingJobService(db).admit(
                USER_A, IndexingOperation.CHUNK, authorize=lambda: None
            )
    async with factory() as db:
        db.add(
            IndexingJob(
                user_id=USER_B, operation=IndexingOperation.CHUNK, status=IndexingJobStatus.QUEUED
            )
        )
        await db.commit()
    with pytest.raises(Exception, match="Cannot remove managed"):
        async with owner_engine.begin() as conn:
            await conn.run_sync(apply_revision, REVISION, downgrade=True)
    async with factory() as db:
        historical = await db.get(IndexingJob, historical_id)
        assert historical is not None and historical.operation is None


async def test_durable_assertion_detects_removed_commit(admission, monkeypatch):
    r = admission

    async def only_flush(self):
        await self.flush()

    monkeypatch.setattr(AsyncSession, "commit", only_flush)
    response = await r.client.post("/api/v1/index/chunk", headers=r.headers[USER_A])
    assert response.status_code == 202
    with pytest.raises(AssertionError):
        async with r.factory() as db:
            assert await db.get(IndexingJob, response.json()["job_id"]) is not None


async def test_poll_assertion_detects_removed_owner_predicate(admission, monkeypatch):
    r = admission
    response = await r.client.post("/api/v1/index/chunk", headers=r.headers[USER_A])
    job_id = response.json()["job_id"]

    async def global_read(self, user_id, job_id=None):
        return await self.db.scalar(select(IndexingJob).where(IndexingJob.id == job_id))

    monkeypatch.setattr(IndexingJobService, "get_job", global_read)
    response = await r.client.get(
        "/api/v1/index/status", params={"job_id": job_id}, headers=r.headers[USER_B]
    )
    with pytest.raises(AssertionError):
        assert response.status_code == 404


async def test_only_admission_unique_violation_is_conflict(admission, monkeypatch):
    r = admission
    async with r.factory() as db:
        db.add(
            IndexingJob(
                user_id=USER_A, operation=IndexingOperation.CHUNK, status=IndexingJobStatus.QUEUED
            )
        )
        await db.commit()
    async with r.factory() as db:
        original = db.scalar
        calls = 0

        async def hide_existing(statement, *args, **kwargs):
            nonlocal calls
            calls += 1
            return None if calls == 2 else await original(statement, *args, **kwargs)

        monkeypatch.setattr(db, "scalar", hide_existing)
        with pytest.raises(IndexingAdmissionConflict):
            await IndexingJobService(db).admit(
                USER_A, IndexingOperation.BUILD, authorize=lambda: None
            )
    # An unrelated FK violation must be operational failure, not a false 409.
    async with r.factory() as db:
        original = db.scalar
        calls = 0
        missing_owner = uuid4()

        async def pretend_owner(statement, *args, **kwargs):
            nonlocal calls
            calls += 1
            return missing_owner if calls == 1 else await original(statement, *args, **kwargs)

        monkeypatch.setattr(db, "scalar", pretend_owner)
        with pytest.raises(IndexingStoreUnavailable):
            await IndexingJobService(db).admit(
                missing_owner, IndexingOperation.CHUNK, authorize=lambda: None
            )


async def test_deleted_accepted_target_remains_explicit(admission):
    r = admission
    response = await r.client.post(
        "/api/v1/index/chunk", params={"file_id": str(r.files[USER_A])}, headers=r.headers[USER_A]
    )
    assert response.status_code == 202
    async with r.factory() as db:
        await db.execute(delete(DriveFile).where(DriveFile.id == r.files[USER_A]))
        await db.commit()
    async with r.factory() as db:
        job = await db.get(IndexingJob, response.json()["job_id"])
        assert job.file_id == r.files[USER_A]  # Never NULL/all files on deletion.


async def test_service_target_authorization_is_independent_of_api(admission):
    from app.services.indexing_job_service import IndexingTargetNotFound

    r = admission
    async with r.factory() as db:
        with pytest.raises(IndexingTargetNotFound):
            await IndexingJobService(db).admit(
                USER_A, IndexingOperation.CHUNK, authorize=lambda: None, file_id=r.files[USER_B]
            )
    response = await r.client.post(
        "/api/v1/index/chunk", params={"file_id": str(r.files[USER_B])}, headers=r.headers[USER_B]
    )
    assert response.status_code == 202
    async with r.factory() as db:
        job = await db.get(IndexingJob, response.json()["job_id"])
        assert job is not None and job.user_id == USER_B and job.file_id == r.files[USER_B]
