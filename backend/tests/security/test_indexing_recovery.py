"""Disposable real-store operator recovery, uncertainty and maintenance boundaries."""

from uuid import UUID, uuid4

import pytest
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, PointIdsList, PointStruct, VectorParams
from sqlalchemy import delete, update

from app.db.enums import DriveFileStatus, IndexingJobStatus, IndexingOperation
from app.db.models.drive_file import DriveFile
from app.db.models.indexing_job import IndexingJob
from app.db.models.user import User
from app.services.indexing_recovery import IndexingRecovery, MaintenanceAttestation, RecoveryBlocked
from app.services.indexing_job_service import IndexingAdmissionUnavailable
from .conftest import DEMO_USER, USER_A, USER_B, apply_revision
from .test_indexing_worker import (
    document,
    enqueue,
    job,
    final_engine,
    keys,
    owner_engine,
    qdrant_client,
    world,
)
from .test_worker_vector_reconciliation import points
from .test_qdrant_tenant_inventory import subprocess_target

__all__ = ["world", "final_engine", "keys", "owner_engine", "qdrant_client", "subprocess_target"]
ATTEST = MaintenanceAttestation("synthetic-maintenance-1", True, True, True, True)


async def failed_build(w, monkeypatch):
    await document(w)
    await document(w, USER_B)
    # Build B normally first; its healthy vectors are competitive preservation controls.
    bid = await enqueue(w, IndexingOperation.BUILD, owner=USER_B)
    await w.worker.run_once()
    assert (await job(w, bid)).status == IndexingJobStatus.COMPLETED
    original = AsyncQdrantClient.upsert

    async def lost(client, *args, **kwargs):
        await original(client, *args, **kwargs)
        raise TimeoutError("synthetic lost acknowledgement")

    with monkeypatch.context() as m:
        m.setattr(AsyncQdrantClient, "upsert", lost)
        jid = await enqueue(w, IndexingOperation.BUILD)
        await w.worker.run_once()
    row = await job(w, jid)
    assert row.status == IndexingJobStatus.FAILED and row.recovery_required
    async with w.factory() as db:
        # Full normal-mode inventory intentionally refuses demo-containing stores.
        await db.execute(delete(User).where(User.id == DEMO_USER))
        await db.commit()
    return jid


def service(w):
    return IndexingRecovery(w.engine, w.client, w.settings, w.worker.embedding_service)


async def test_lost_ack_recovery_preserves_foreign_owner_and_original_attempt(world, monkeypatch):
    w = world
    jid = await failed_build(w, monkeypatch)
    original = (await job(w, jid)).attempt_manifest
    before = await points(w)
    b = {i: p for i, p in before.items() if p["payload"]["user_id"] == str(USER_B)}
    result = await service(w).apply(USER_A, jid, ATTEST)
    assert result["released"]
    assert isinstance(result["inventory"], dict) and result["inventory"]["clean"]
    row = await job(w, jid)
    assert row.status == IndexingJobStatus.FAILED and not row.recovery_required
    assert row.attempt_manifest == original
    assert row.recovery_manifest["state"] == "VERIFIED"
    assert {i: p for i, p in (await points(w)).items() if i in b} == b
    async with w.factory() as db:
        assert (await db.get(DriveFile, w.files[USER_A])).status == DriveFileStatus.INDEXED


@pytest.mark.parametrize(
    "missing",
    ["admission_closed", "writers_terminated", "outstanding_requests_settled", "collection_frozen"],
)
async def test_no_release_without_complete_external_boundary(world, monkeypatch, missing):
    from dataclasses import replace

    w = world
    jid = await failed_build(w, monkeypatch)
    before = await points(w)
    with pytest.raises(RecoveryBlocked):
        await service(w).apply(USER_A, jid, replace(ATTEST, **{missing: False}))
    row = await job(w, jid)
    assert row.recovery_required and row.recovery_manifest is None
    assert await points(w) == before


@pytest.mark.parametrize(
    "kind",
    [
        "dimension",
        "distance",
        "named",
        "manifest",
        "foreign_owner",
        "changed_hash",
        "changed_metadata",
        "missing_index",
    ],
)
async def test_pre_mutation_rejections_preserve_blocked_state(world, monkeypatch, kind):
    from app.db.models.document import Document

    w = world
    jid = await failed_build(w, monkeypatch)
    if kind in {"dimension", "distance", "named"}:
        await w.client.delete_collection(w.settings.qdrant_collection)
        config = VectorParams(
            size=4 if kind == "dimension" else 3,
            distance=Distance.DOT if kind == "distance" else Distance.COSINE,
        )
        await w.client.create_collection(
            w.settings.qdrant_collection,
            vectors_config={"named": config} if kind == "named" else config,
        )
    elif kind == "manifest":
        async with w.factory() as db:
            await db.execute(
                update(IndexingJob)
                .where(IndexingJob.id == jid)
                .values(attempt_manifest={"version": 99})
            )
            await db.commit()
    elif kind == "changed_hash":
        async with w.factory() as db:
            await db.execute(
                update(Document)
                .where(Document.drive_file_id == w.files[USER_A])
                .values(extracted_text_hash="changed")
            )
            await db.commit()
    if kind == "changed_metadata":
        async with w.factory() as db:
            await db.execute(
                update(DriveFile)
                .where(DriveFile.id == w.files[USER_A])
                .values(name="changed-synthetic.txt")
            )
            await db.commit()
    elif kind == "missing_index":
        await w.client.delete_payload_index(w.settings.qdrant_collection, "user_id", wait=True)
    before = await points(w)
    with pytest.raises(Exception):
        await service(w).apply(USER_B if kind == "foreign_owner" else USER_A, jid, ATTEST)
    assert (await job(w, jid)).recovery_required
    assert (await job(w, jid)).recovery_manifest is None
    assert await points(w) == before


async def test_missing_and_stale_actual_ids_repaired_without_foreign_deletion(world, monkeypatch):
    w = world
    jid = await failed_build(w, monkeypatch)
    before = await points(w)
    a = next(p for p in before.values() if p["payload"]["user_id"] == str(USER_A))
    await w.client.delete(w.settings.qdrant_collection, PointIdsList(points=[a["id"]]), wait=True)
    stale = uuid4()
    await w.client.upsert(
        w.settings.qdrant_collection,
        points=[
            PointStruct(
                id=str(stale),
                vector=[1.0, 0.0, 0.0],
                payload=a["payload"] | {"chunk_id": str(stale)},
            )
        ],
        wait=True,
    )
    native = AsyncQdrantClient.upsert
    checked = []

    async def checked_issue(client, *args, **kwargs):
        row = await job(
            w, jid
        )  # Independent SQL connection proves intent COMMITTED before dispatch.
        entry = row.recovery_manifest["operations"][-1]
        assert entry["operation"] == "upsert" and entry["outcome"] == "UNKNOWN"
        checked.append(entry)
        return await native(client, *args, **kwargs)

    monkeypatch.setattr(AsyncQdrantClient, "upsert", checked_issue)
    assert (await service(w).apply(USER_A, jid, ATTEST))["released"]
    after = await points(w)
    assert str(stale) not in after and a["id"] in after and checked
    assert {i: p for i, p in before.items() if p["payload"]["user_id"] == str(USER_B)} == {
        i: p for i, p in after.items() if p["payload"]["user_id"] == str(USER_B)
    }


async def test_recovery_lost_ack_requires_new_attestation_and_exact_resume(world, monkeypatch):
    w = world
    jid = await failed_build(w, monkeypatch)
    a = next(p for p in (await points(w)).values() if p["payload"]["user_id"] == str(USER_A))
    await w.client.delete(w.settings.qdrant_collection, PointIdsList(points=[a["id"]]), wait=True)
    native = AsyncQdrantClient.upsert
    with monkeypatch.context() as m:

        async def lost(client, *args, **kwargs):
            await native(client, *args, **kwargs)
            raise TimeoutError("synthetic acknowledgement loss")

        m.setattr(AsyncQdrantClient, "upsert", lost)
        with pytest.raises(TimeoutError):
            await service(w).apply(USER_A, jid, ATTEST)
    row = await job(w, jid)
    assert row.recovery_required and row.recovery_manifest["operations"][-1]["outcome"] == "UNKNOWN"
    with pytest.raises(RecoveryBlocked):
        await service(w).apply(USER_A, jid, ATTEST)
    rid = UUID(row.recovery_manifest["id"])
    assert (await service(w).apply(USER_A, jid, ATTEST, resume_id=rid))["released"]
    assert (await job(w, jid)).recovery_manifest["operations"][-1]["outcome"] == "RECONCILED"


async def test_database_barrier_blocks_competing_operators_and_managed_writers(world, monkeypatch):
    w = world
    jid = await failed_build(w, monkeypatch)
    operator = service(w)
    async with operator._maintenance(ATTEST):
        with pytest.raises(RecoveryBlocked):
            async with service(w)._maintenance(ATTEST):
                pytest.fail("Competing operator obtained authority")
        with pytest.raises(IndexingAdmissionUnavailable):
            await enqueue(w, IndexingOperation.CHUNK, owner=USER_B)
        assert await w.worker.claim_next() is None
    assert (await job(w, jid)).recovery_required


async def test_dry_run_and_downgrade_preserve_evidence(world, monkeypatch):
    w = world
    jid = await failed_build(w, monkeypatch)
    before = await points(w)
    result = await service(w).audit(USER_A, jid)
    assert not result["mutation"] and not result["ready_to_release"]
    assert (await job(w, jid)).recovery_manifest is None and await points(w) == before
    await service(w).apply(USER_A, jid, ATTEST)
    with pytest.raises(RuntimeError, match="Retain operator recovery"):
        async with w.engine.begin() as conn:
            await conn.run_sync(apply_revision, "20261014_1200", downgrade=True)
    assert (await job(w, jid)).recovery_manifest["state"] == "VERIFIED"


async def test_partial_multi_file_scope_does_not_promote_unrelated_failed_files(world, monkeypatch):
    from datetime import UTC, datetime
    from app.db.models.document import Document

    w = world
    await document(w)
    await document(w, USER_B)
    bid = await enqueue(w, IndexingOperation.BUILD, owner=USER_B)
    await w.worker.run_once()
    assert (await job(w, bid)).status == IndexingJobStatus.COMPLETED
    async with w.factory() as db:
        other = DriveFile(
            user_id=USER_A,
            drive_file_id="second-synthetic",
            name="second.txt",
            mime_type="text/plain",
            modified_at=datetime.now(UTC),
            status=DriveFileStatus.INDEXING,
        )
        unrelated = DriveFile(
            user_id=USER_A,
            drive_file_id="unrelated-failed",
            name="failed.txt",
            mime_type="text/plain",
            modified_at=datetime.now(UTC),
            status=DriveFileStatus.FAILED,
        )
        db.add_all([other, unrelated])
        await db.flush()
        db.add(
            Document(
                drive_file_id=other.id,
                extracted_text="Second synthetic file.",
                extracted_text_hash="second-hash",
            )
        )
        await db.execute(delete(User).where(User.id == DEMO_USER))
        await db.commit()
        other_id, unrelated_id = other.id, unrelated.id
    native = AsyncQdrantClient.upsert
    calls = 0
    with monkeypatch.context() as m:

        async def second_lost(client, *args, **kwargs):
            nonlocal calls
            calls += 1
            result = await native(client, *args, **kwargs)
            if calls == 2:
                raise TimeoutError("second file acknowledgement lost")
            return result

        m.setattr(AsyncQdrantClient, "upsert", second_lost)
        jid = await enqueue(w, IndexingOperation.BUILD)
        await w.worker.run_once()
    row = await job(w, jid)
    assert row.recovery_required and len(row.attempt_manifest["files"]) == 2
    assert {f["file_id"] for f in row.attempt_manifest["files"]} == {
        str(w.files[USER_A]),
        str(other_id),
    }
    assert (await service(w).apply(USER_A, jid, ATTEST))["released"]
    async with w.factory() as db:
        assert (await db.get(DriveFile, unrelated_id)).status == DriveFileStatus.FAILED
        assert (await db.get(DriveFile, other_id)).status == DriveFileStatus.INDEXED


async def test_actual_point_identity_rejects_foreign_payload_redirect(world, monkeypatch):
    w = world
    jid = await failed_build(w, monkeypatch)
    before = await points(w)
    b = next(p for p in before.values() if p["payload"]["user_id"] == str(USER_B))
    malformed = uuid4()
    await w.client.upsert(
        w.settings.qdrant_collection,
        points=[
            PointStruct(
                id=str(malformed),
                vector=[1.0, 0.0, 0.0],
                payload=b["payload"]
                | {"drive_file_id": str(w.files[USER_A]), "user_id": str(USER_A)},
            )
        ],
        wait=True,
    )
    with pytest.raises(RecoveryBlocked, match="contradictory"):
        await service(w).apply(USER_A, jid, ATTEST)
    assert (await points(w))[b["id"]] == b
    assert (await job(w, jid)).recovery_required


async def test_pagination_and_multiple_delete_intents_are_complete(world, monkeypatch):
    w = world
    jid = await failed_build(w, monkeypatch)
    a = next(p for p in (await points(w)).values() if p["payload"]["user_id"] == str(USER_A))
    stale = [uuid4() for _ in range(205)]
    await w.client.upsert(
        w.settings.qdrant_collection,
        points=[
            PointStruct(
                id=str(i), vector=[1.0, 0.0, 0.0], payload=a["payload"] | {"chunk_id": str(i)}
            )
            for i in stale
        ],
        wait=True,
    )
    assert (await service(w).apply(USER_A, jid, ATTEST))["released"]
    row = await job(w, jid)
    operations = row.recovery_manifest["operations"]
    assert [len(op["point_ids"]) for op in operations] == [100, 100, 5]
    assert {i for op in operations for i in op["point_ids"]} == {str(i) for i in stale}
    assert all(op["outcome"] == "ACKNOWLEDGED" for op in operations)


@pytest.mark.parametrize("boundary", ["intent", "receipt", "publication", "verification"])
async def test_interruption_retains_exclusion_and_resumes_idempotently(
    world, monkeypatch, boundary
):
    import app.services.indexing_recovery as module

    w = world
    jid = await failed_build(w, monkeypatch)
    a = next(p for p in (await points(w)).values() if p["payload"]["user_id"] == str(USER_A))
    await w.client.delete(w.settings.qdrant_collection, PointIdsList(points=[a["id"]]), wait=True)
    native_issue = AsyncQdrantClient.upsert
    # Transaction contexts use transaction.commit; inject the authoritative
    # callback/publish boundaries instead of pretending session.commit covers them.
    with monkeypatch.context() as m:
        if boundary == "intent":

            async def never_issue(*args, **kwargs):
                assert (await job(w, jid)).recovery_manifest["operations"][-1][
                    "outcome"
                ] == "UNKNOWN"
                raise TimeoutError("crash after intent before dispatch")

            m.setattr(AsyncQdrantClient, "upsert", never_issue)
        elif boundary == "receipt":

            async def lost_receipt(client, *args, **kwargs):
                await native_issue(client, *args, **kwargs)
                raise TimeoutError("crash after dispatch")

            m.setattr(AsyncQdrantClient, "upsert", lost_receipt)
        elif boundary == "publication":
            from sqlalchemy.ext.asyncio import AsyncSession
            from sqlalchemy.sql.dml import Update

            execute = AsyncSession.execute

            async def blocked_publish(db, statement, *args, **kwargs):
                if (
                    isinstance(statement, Update)
                    and getattr(statement.table, "name", None) == "drive_files"
                ):
                    raise TimeoutError("crash after acknowledged repair before SQL publication")
                return await execute(db, statement, *args, **kwargs)

            m.setattr(AsyncSession, "execute", blocked_publish)
        else:

            async def lost_verification(*args, **kwargs):
                row = await job(w, jid)
                assert row.recovery_manifest["state"] == "VERIFYING"
                raise TimeoutError("crash before release")

            m.setattr(module, "inventory", lost_verification)
        with pytest.raises(TimeoutError):
            await service(w).apply(USER_A, jid, ATTEST)
    row = await job(w, jid)
    assert row.status == IndexingJobStatus.FAILED and row.recovery_required
    assert (
        await service(w).apply(USER_A, jid, ATTEST, resume_id=UUID(row.recovery_manifest["id"]))
    )["released"]
    assert (await job(w, jid)).status == IndexingJobStatus.FAILED


async def test_readiness_is_read_only_and_never_claims_operational_quiescence(world, monkeypatch):
    from app.ops.indexing_recovery import cutover_report
    from sqlalchemy import text

    w = world
    jid = await failed_build(w, monkeypatch)
    await service(w).apply(USER_A, jid, ATTEST)
    async with w.engine.begin() as conn:
        # Fixture revisions are applied directly; create version metadata in the generated schema only.
        await conn.execute(
            text("CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)")
        )
        await conn.execute(text("INSERT INTO alembic_version VALUES ('20261014_1200')"))
    before = await points(w)
    result = await cutover_report(w.engine, w.client, w.settings, 3)
    checks = result["checks"]
    assert isinstance(checks, dict)
    assert checks["schema_current"] and checks["inventory_clean"]
    assert not result["ready"] and not result["activation_authorized"] and not result["mutation"]
    prerequisites = result["external_prerequisites"]
    assert isinstance(prerequisites, dict) and prerequisites["old_writers_drained"] == "UNKNOWN"
    assert await points(w) == before


async def test_recovery_is_not_an_http_route_and_demo_cannot_construct_it(world):
    from app.main import create_app

    assert not any("recovery" in path for path in create_app().openapi()["paths"])
    with pytest.raises(Exception):
        IndexingRecovery(
            world.engine,
            world.client,
            world.settings.model_copy(update={"demo_mode": True}),
            world.worker.embedding_service,
        )


async def test_manifest_cannot_select_foreign_authoritative_sql_snapshot(world, monkeypatch):
    w = world
    jid = await failed_build(w, monkeypatch)
    async with w.factory() as db:
        from sqlalchemy import select

        b = await db.scalar(select(IndexingJob).where(IndexingJob.user_id == USER_B))
        a = await db.get(IndexingJob, jid)
        altered = dict(a.attempt_manifest)
        altered["files"] = b.attempt_manifest["files"]
        a.attempt_manifest = altered
        await db.commit()
    with pytest.raises(RecoveryBlocked, match="belongs"):
        await service(w).audit(USER_A, jid)
    assert (await job(w, jid)).recovery_required


async def test_live_claim_prevents_recovery_without_changing_healthy_work(world, monkeypatch):
    w = world
    jid = await failed_build(w, monkeypatch)
    bid = await enqueue(w, IndexingOperation.CHUNK, owner=USER_B)
    claim = await w.worker.claim_next()
    assert claim.job_id == bid
    with pytest.raises(RecoveryBlocked, match="drained"):
        await service(w).apply(USER_A, jid, ATTEST)
    await w.worker.renew_lease(claim)
    assert (await job(w, bid)).status == IndexingJobStatus.RUNNING
    assert (await job(w, jid)).recovery_manifest is None


async def test_upgrade_preserves_historical_jobs_and_no_evidence_is_invented(world):
    from sqlalchemy import text

    w = world
    async with w.factory() as db:
        historical = IndexingJob(
            user_id=USER_A, status=IndexingJobStatus.FAILED, error="synthetic historical error"
        )
        db.add(historical)
        await db.commit()
        hid = historical.id
    async with w.engine.begin() as conn:
        before = (
            await conn.execute(
                text(
                    "SELECT id, user_id, status, error, operation, attempt_manifest FROM indexing_jobs"
                )
            )
        ).all()
        await conn.run_sync(apply_revision, "20261014_1200", downgrade=True)
        await conn.run_sync(apply_revision, "20261014_1200")
        after = (
            await conn.execute(
                text(
                    "SELECT id, user_id, status, error, operation, attempt_manifest FROM indexing_jobs"
                )
            )
        ).all()
    assert before == after
    assert (await job(w, hid)).recovery_manifest is None


async def test_real_cli_invalid_confirmation_refuses_before_storage_mutation(world, monkeypatch):
    import asyncio
    import json
    import os
    import sys

    w = world
    jid = await failed_build(w, monkeypatch)
    before = await points(w)
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "app.ops.indexing_recovery",
        "apply",
        "--database-env",
        "SESSION_TEST_DATABASE_URL",
        "--qdrant-url",
        w.settings.qdrant_url,
        "--collection",
        w.settings.qdrant_collection,
        "--embedding-model",
        "text-embedding-3-small",
        "--owner",
        str(USER_A),
        "--job",
        str(jid),
        "--confirm-target",
        "incorrect",
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    result = json.loads(stdout)
    assert process.returncode == 2 and not result["released"] and not result["complete"]
    assert not stderr and "synthetic-only" not in stdout.decode()
    assert (await job(w, jid)).recovery_manifest is None and await points(w) == before


async def test_real_cli_audit_apply_and_readiness_without_paid_transports(
    world, monkeypatch, subprocess_target
):
    import asyncio
    import json
    import sys
    from sqlalchemy import text
    from sqlalchemy.engine import make_url
    from app.ops.qdrant_tenant_repair import confirmation_target

    w = world

    class FakeConfiguredEmbeddings:
        model_name = "text-embedding-3-small"
        embedding_dimension = 1536

        async def embed_texts(self, texts):
            return [[1.0] + [0.0] * 1535 for _ in texts]

    w.worker.embedding_service = FakeConfiguredEmbeddings()
    jid = await failed_build(w, monkeypatch)
    before = await points(w)
    env = subprocess_target
    url = make_url(env["INVENTORY_SUBPROCESS_DATABASE"])
    base = [sys.executable, "-m", "app.ops.indexing_recovery"]
    flags = [
        "--database-env",
        "INVENTORY_SUBPROCESS_DATABASE",
        "--qdrant-url",
        w.settings.qdrant_url,
        "--collection",
        w.settings.qdrant_collection,
        "--embedding-model",
        "text-embedding-3-small",
    ]

    async def invoke(command, extra):
        process = await asyncio.create_subprocess_exec(
            *base,
            command,
            *flags,
            *extra,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), 30)
        assert not stderr and "synthetic-cli-only" not in stdout.decode()
        return process.returncode, json.loads(stdout)

    owner = ["--owner", str(USER_A), "--job", str(jid)]
    code, result = await invoke("audit", owner)
    assert code == 0 and result["complete"] and not result["mutation"]
    assert result["files"] == [str(w.files[USER_A])]
    assert await points(w) == before and (await job(w, jid)).recovery_manifest is None
    async with w.engine.begin() as conn:
        schema = await conn.scalar(text("SELECT current_schema()"))
        role = url.username
        assert isinstance(role, str) and role.startswith("inventory_cli_")
        assert isinstance(schema, str) and schema.startswith("session_test_")
        await conn.execute(text(f'ALTER ROLE "{role}" SET default_transaction_read_only TO off'))
        await conn.execute(text(f'GRANT UPDATE ON ALL TABLES IN SCHEMA "{schema}" TO "{role}"'))
    code, result = await invoke(
        "apply",
        owner
        + [
            "--confirm-target",
            confirmation_target(w.settings, database_target=url),
            "--maintenance-reference",
            "synthetic-cli-maintenance",
            "--admission-closed",
            "--writers-terminated",
            "--outstanding-requests-settled",
            "--collection-frozen",
        ],
    )
    assert code == 0 and result["released"] and result["inventory"]["clean"]
    assert (await job(w, jid)).status == IndexingJobStatus.FAILED
    async with w.engine.begin() as conn:
        await conn.execute(
            text("CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)")
        )
        await conn.execute(text("INSERT INTO alembic_version VALUES ('20261014_1200')"))
        await conn.execute(text(f'GRANT SELECT ON alembic_version TO "{role}"'))
    code, result = await invoke("readiness", [])
    assert code == 1 and result["complete"] and not result["ready"]
    assert result["checks"]["schema_current"] and result["checks"]["inventory_clean"]


@pytest.mark.parametrize("missing", ["embedding_model", "vector_dimension", "metadata_digest"])
async def test_historical_configuration_and_metadata_are_never_invented(
    world, monkeypatch, missing
):
    w = world
    jid = await failed_build(w, monkeypatch)
    async with w.factory() as db:
        row = await db.get(IndexingJob, jid)
        data = dict(row.attempt_manifest)
        if missing == "metadata_digest":
            data["files"] = [dict(f) for f in data["files"]]
            data["files"][0].pop(missing)
        else:
            data.pop(missing)
        row.attempt_manifest = data
        await db.commit()
    before = await points(w)
    with pytest.raises(RecoveryBlocked, match="unknown"):
        await service(w).apply(USER_A, jid, ATTEST)
    assert (await job(w, jid)).recovery_required and await points(w) == before


async def test_exhaustive_verification_blocks_release_on_unrelated_collection_anomaly(
    world, monkeypatch
):
    w = world
    jid = await failed_build(w, monkeypatch)
    before = await points(w)
    b = next(p for p in before.values() if p["payload"]["user_id"] == str(USER_B))
    orphan = uuid4()
    await w.client.upsert(
        w.settings.qdrant_collection,
        points=[
            PointStruct(
                id=str(orphan),
                vector=[1.0, 0.0, 0.0],
                payload=b["payload"] | {"chunk_id": str(orphan)},
            )
        ],
        wait=True,
    )
    snapshot = await points(w)
    with pytest.raises(RecoveryBlocked, match="exhaustive"):
        await service(w).apply(USER_A, jid, ATTEST)
    assert (await job(w, jid)).recovery_required
    assert (await points(w))[str(orphan)] == snapshot[str(orphan)]
    assert (await points(w))[b["id"]] == b


async def test_metadata_repair_preserves_verified_vector_without_reembedding(world, monkeypatch):
    w = world
    jid = await failed_build(w, monkeypatch)
    a = next(p for p in (await points(w)).values() if p["payload"]["user_id"] == str(USER_A))
    await w.client.set_payload(
        w.settings.qdrant_collection,
        {"filename": "synthetic-wrong-filename", "mime_type": "image/png"},
        points=[a["id"]],
        wait=True,
    )

    async def no_embedding(texts):
        raise AssertionError("Verified unchanged vector must be preserved")

    monkeypatch.setattr(w.worker.embedding_service, "embed_texts", no_embedding)
    assert (await service(w).apply(USER_A, jid, ATTEST))["released"]
    after = (await points(w))[a["id"]]
    assert after["vector"] == a["vector"]
    assert (
        after["payload"]["filename"] == "shared.txt"
        and after["payload"]["mime_type"] == "text/plain"
    )
    assert (await job(w, jid)).recovery_manifest["operations"][-1]["outcome"] == "ACKNOWLEDGED"


@pytest.mark.parametrize("field", ["document", "chunk"])
async def test_text_drift_without_hash_change_cannot_release_owner(world, monkeypatch, field):
    from app.db.models.chunk import Chunk
    from app.db.models.document import Document
    from sqlalchemy import select

    w = world
    jid = await failed_build(w, monkeypatch)
    async with w.factory() as db:
        doc = await db.scalar(select(Document).where(Document.drive_file_id == w.files[USER_A]))
        if field == "document":
            doc.extracted_text = "Changed synthetic body with unchanged declared hash."
        else:
            chunk = await db.scalar(select(Chunk).where(Chunk.document_id == doc.id).limit(1))
            chunk.text = "Changed synthetic chunk with unchanged metadata hash."
        await db.commit()
    before = await points(w)
    with pytest.raises(RecoveryBlocked, match="lineage"):
        await service(w).apply(USER_A, jid, ATTEST)
    assert (await job(w, jid)).recovery_required and (await job(w, jid)).recovery_manifest is None
    assert await points(w) == before
