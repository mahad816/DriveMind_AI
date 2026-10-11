"""Controlled repair against disposable PostgreSQL/Qdrant; no real corpora."""

import asyncio
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

import httpx
import pytest
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import PointStruct, Filter, FieldCondition, MatchValue, StrictModeConfig
from sqlalchemy.engine import make_url
from sqlalchemy import delete, select, update

from app.core.config import Settings
from app.db.enums import DriveFileStatus
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.ops.qdrant_tenant_inventory import inventory
from app.ops.qdrant_tenant_repair import apply_repair, confirmation_target
from .conftest import USER_A, USER_B
from .test_qdrant_tenant_inventory import (
    world,
    owner_engine,
    final_engine,
    qdrant_client,
    subprocess_target,
)

__all__ = ["world", "owner_engine", "final_engine", "qdrant_client", "subprocess_target"]


async def missing_owners(w, indices=(0, 3)):
    for index in indices:
        w.points[index].payload.pop("user_id", None)
    await w.client.upsert(w.settings.qdrant_collection, [w.points[i] for i in indices], wait=True)


async def snapshot(w):
    return await w.client.retrieve(
        w.settings.qdrant_collection, [str(i) for i in w.ids], with_vectors=True
    )


async def test_repair_preserves_and_idempotently_verifies(world):
    w = world
    await missing_owners(w, (0,))
    w.points[3].payload["user_id"] = str(USER_A)
    await w.client.upsert(w.settings.qdrant_collection, [w.points[3]], wait=True)
    before = {r.id: r for r in await snapshot(w)}
    result, code = await apply_repair(w.engine, w.client, w.settings, 2)
    assert code == 0 and result["complete"] and result["verification"]["clean"]
    assert result["changed"] == 2 and result["already_correct"] == 4
    assert result["preflight"]["issue_counts"] == {"missing_owner": 1, "wrong_owner": 1}
    after = {r.id: r for r in await snapshot(w)}
    for i, record in after.items():
        assert record.vector == before[i].vector
        assert {k: v for k, v in record.payload.items() if k != "user_id"} == {
            k: v for k, v in before[i].payload.items() if k != "user_id"
        }
    for owner, expected in ((USER_A, w.ids[:3]), (USER_B, w.ids[3:])):
        hits = await w.client.query_points(
            w.settings.qdrant_collection,
            query=[1.0, 0.0, 0.0],
            query_filter=Filter(
                must=[FieldCondition(key="user_id", match=MatchValue(value=str(owner)))]
            ),
            limit=10,
        )
        assert {p.id for p in hits.points} == {str(i) for i in expected}
    second, code = await apply_repair(w.engine, w.client, w.settings, 2)
    assert code == 0 and second["changed"] == 0 and second["already_correct"] == 6
    assert await snapshot(w) == list(after.values())
    assert (await inventory(w.engine, w.client, w.settings, 2)).as_dict()["clean"]


@pytest.mark.parametrize(
    "defect",
    [
        "orphan",
        "missing_point",
        "vector",
        "file",
        "hash",
        "json",
        "ineligible",
        "deleted",
        "invalid_owner",
    ],
)
async def test_non_owner_preflight_blocks_all_writes(world, defect):
    w = world
    await missing_owners(w, (0,))
    point = w.points[3].model_copy(deep=True)
    if defect == "orphan":
        point.id = str(uuid4())
    elif defect == "missing_point":
        await w.client.delete(w.settings.qdrant_collection, [point.id], wait=True)
    elif defect == "vector":
        point.vector = {}
    elif defect == "file":
        point.payload["drive_file_id"] = str(uuid4())
    elif defect == "hash":
        point.payload["extracted_text_hash"] = "bad"
    elif defect == "invalid_owner":
        point.payload["user_id"] = [str(USER_B)]
    else:
        async with w.factory() as db:
            if defect == "json":
                await db.execute(
                    update(Chunk)
                    .where(Chunk.id == w.ids[3])
                    .values(metadata_json={"extracted_text_hash": 123})
                )
            elif defect == "deleted":
                await db.execute(delete(Chunk).where(Chunk.id == w.ids[3]))
            else:
                await db.execute(
                    update(DriveFile)
                    .where(DriveFile.user_id == USER_B)
                    .values(status=DriveFileStatus.SKIPPED)
                )
            await db.commit()
    if defect in {"orphan", "vector", "file", "hash", "invalid_owner"}:
        await w.client.upsert(w.settings.qdrant_collection, [point], wait=True)
    before = await snapshot(w)
    result, code = await apply_repair(w.engine, w.client, w.settings, 2)
    assert code == 1 and not result["complete"] and result["changed"] == 0
    assert result["preflight_blockers"]
    assert await snapshot(w) == before


class FaultTransport(httpx.AsyncBaseTransport):
    """Forward real Qdrant HTTP I/O, with deterministic transport faults/race barriers."""

    def __init__(self, hook):
        self.inner = httpx.AsyncHTTPTransport()
        self.hook = hook
        self.writes = 0
        self.counts = 0
        self.retrieves = 0

    async def handle_async_request(self, request):
        if request.url.path.endswith("/payload"):
            self.writes += 1
        if request.url.path.endswith("/count"):
            self.counts += 1
        if request.method == "POST" and request.url.path.endswith("/points"):
            self.retrieves += 1
        await self.hook(self, request, "before")
        response = await self.inner.handle_async_request(request)
        await self.hook(self, request, "after")
        return response

    async def aclose(self):
        await self.inner.aclose()


@pytest.mark.parametrize("lost_ack", [False, True])
async def test_transport_failure_and_rerun_converges(world, lost_ack):
    w = world
    await missing_owners(w, tuple(range(6)))

    async def hook(t, request, phase):
        if (
            request.url.path.endswith("/payload")
            and t.writes == 1
            and phase == ("after" if lost_ack else "before")
        ):
            raise httpx.ReadError("synthetic-provider-failure", request=request)

    client = AsyncQdrantClient(
        url=os.environ["QDRANT_TEST_URL"], transport=FaultTransport(hook), check_compatibility=False
    )
    try:
        result, code = await apply_repair(w.engine, client, w.settings, 2)
        assert code == 2 and not result["complete"] and result["failed"] > 0
        assert "synthetic-provider-failure" not in json.dumps(result)
    finally:
        await client.close()
    assert not (await inventory(w.engine, w.client, w.settings, 2)).as_dict()["clean"]
    result, code = await apply_repair(w.engine, w.client, w.settings, 2)
    assert code == 0 and result["verification"]["clean"]


async def test_conditional_partial_update_is_not_success(world):
    w = world
    await missing_owners(w, tuple(range(6)))
    changed_id = None

    async def hook(t, request, phase):
        nonlocal changed_id
        if request.url.path.endswith("/payload") and t.writes == 1 and phase == "before":
            body = json.loads(request.content)
            changed_id = body["filter"]["should"][0]["must"][0]["has_id"][0]
            await w.client.set_payload(
                w.settings.qdrant_collection,
                payload={"extracted_text_hash": "raced-hash"},
                points=[changed_id],
                wait=True,
            )

    client = AsyncQdrantClient(
        url=os.environ["QDRANT_TEST_URL"], transport=FaultTransport(hook), check_compatibility=False
    )
    try:
        result, code = await apply_repair(w.engine, client, w.settings, 6)
        assert code == 2 and not result["complete"]
        assert result["changed"] == 2 and result["failed"] == 1
    finally:
        await client.close()
    point = (await w.client.retrieve(w.settings.qdrant_collection, [changed_id]))[0]
    assert point.payload.get("user_id") is None
    assert (await inventory(w.engine, w.client, w.settings, 2)).issues["wrong_hash"] == 1


@pytest.mark.parametrize("race", ["preflight_hash", "sql_owner", "disappear", "already_correct"])
async def test_revalidation_uses_current_authority(world, race):
    w = world
    await missing_owners(w, tuple(range(6)))
    triggered = False

    async def hook(t, request, phase):
        nonlocal triggered
        if triggered:
            return
        if (
            race == "preflight_hash"
            and request.url.path.endswith("/count")
            and t.counts == 2
            and phase == "after"
        ):
            triggered = True
            async with w.factory() as db:
                await db.execute(
                    update(Chunk)
                    .where(Chunk.id == w.ids[0])
                    .values(metadata_json={"extracted_text_hash": "changed"})
                )
                await db.commit()
        if (
            race != "preflight_hash"
            and request.method == "POST"
            and request.url.path.endswith("/points")
            and phase == "after"
        ):
            body = json.loads(request.content)
            if not body.get("with_vector"):
                return
            triggered = True
            target = body["ids"][0]
            if race == "sql_owner":
                async with w.factory() as db:
                    doc_id = await db.scalar(select(Chunk.document_id).where(Chunk.id == target))
                    file_id = await db.scalar(
                        select(Document.drive_file_id).where(Document.id == doc_id)
                    )
                    # A distinct internal file remains; only change the owner for the race probe.
                    file = await db.get(DriveFile, file_id)
                    file.drive_file_id = "distinct-race-provider"
                    file.user_id = USER_B if file.user_id == USER_A else USER_A
                    await db.commit()
            elif race == "disappear":
                await w.client.delete(w.settings.qdrant_collection, [target], wait=True)
            else:
                async with w.factory() as db:
                    row = await db.execute(
                        select(DriveFile.user_id)
                        .join(Document)
                        .join(Chunk)
                        .where(Chunk.id == target)
                    )
                    owner = row.scalar_one()
                await w.client.set_payload(
                    w.settings.qdrant_collection,
                    payload={"user_id": str(owner)},
                    points=[target],
                    wait=True,
                )

    client = AsyncQdrantClient(
        url=os.environ["QDRANT_TEST_URL"], transport=FaultTransport(hook), check_compatibility=False
    )
    try:
        result, code = await apply_repair(w.engine, client, w.settings, 6)
        assert triggered
        if race == "already_correct":
            assert code == 0 and result["already_correct"] == 1 and result["changed"] == 5
        else:
            assert code == 1 and not result["complete"] and result["changed"] == 0
    finally:
        await client.close()


async def run_apply_cli(w, env, *, confirmed=True, drained=True, command="apply", collection=None):
    chosen = collection or w.settings.qdrant_collection
    settings = Settings(
        database_url=env["INVENTORY_SUBPROCESS_DATABASE"],
        qdrant_url=os.environ["QDRANT_TEST_URL"],
        qdrant_collection=chosen,
    )
    args = [
        sys.executable,
        "-m",
        "app.ops.qdrant_tenant_inventory",
        command,
        "--database-env",
        "INVENTORY_SUBPROCESS_DATABASE",
        "--qdrant-url",
        settings.qdrant_url,
        "--collection",
        chosen,
        "--batch-size",
        "2",
    ]
    if command == "apply":
        args += ["--confirm-target", confirmation_target(settings) if confirmed else "wrong-target"]
        if drained:
            args += ["--writers-stopped"]
    process = await asyncio.create_subprocess_exec(
        *args,
        env=env,
        cwd=Path(__file__).resolve().parents[2],
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(process.communicate(), 30)
    except TimeoutError:
        process.kill()
        await process.communicate()
        raise
    assert "synthetic-cli-only" not in out.decode() + err.decode()
    assert "PRIVATE-SYNTHETIC" not in out.decode() + err.decode()
    return process.returncode, json.loads(out)


async def test_actual_cli_interlocks_apply_and_standalone_verify(world, subprocess_target):
    w = world
    await missing_owners(w)
    before = await snapshot(w)
    for confirmed, drained, collection in (
        (False, True, None),
        (True, False, None),
        (True, True, "harbordesk_demo"),
    ):
        code, report = await run_apply_cli(
            w, subprocess_target, confirmed=confirmed, drained=drained, collection=collection
        )
        assert code == 2 and not report["complete"]
        assert await snapshot(w) == before
    code, report = await run_apply_cli(w, subprocess_target, command="audit")
    assert code == 1 and report["issue_counts"] == {"missing_owner": 2}
    assert await snapshot(w) == before
    code, report = await run_apply_cli(w, subprocess_target)
    assert code == 0 and report["changed"] == 2 and report["verification"]["clean"]
    code, report = await run_apply_cli(w, subprocess_target, command="verify")
    assert code == 0 and report["clean"]
    code, report = await run_apply_cli(w, subprocess_target)
    assert code == 0 and report["changed"] == 0


async def test_actual_cli_blockers_and_unavailable_target(world, subprocess_target):
    w = world
    await missing_owners(w)
    await w.client.set_payload(
        w.settings.qdrant_collection,
        payload={"drive_file_id": str(uuid4())},
        points=[str(w.ids[1])],
        wait=True,
    )
    before = await snapshot(w)
    code, report = await run_apply_cli(w, subprocess_target)
    assert code == 1 and not report["complete"] and report["changed"] == 0
    assert await snapshot(w) == before
    code, report = await run_apply_cli(
        w, subprocess_target, collection="unavailable_" + uuid4().hex
    )
    assert code == 2 and not report["complete"]
    env = dict(subprocess_target)
    env["INVENTORY_SUBPROCESS_DATABASE"] = (
        make_url(env["INVENTORY_SUBPROCESS_DATABASE"])
        .set(database="drivemind_session_test_absent_" + uuid4().hex)
        .render_as_string(hide_password=False)
    )
    code, report = await run_apply_cli(w, env)
    assert code == 2 and not report["complete"]
    env = dict(subprocess_target, DEMO_MODE="true")
    code, report = await run_apply_cli(w, env)
    assert code == 2 and not report["complete"]


async def test_actual_cli_payload_update_failure(world, subprocess_target):
    w = world
    await missing_owners(w)
    before = await snapshot(w)
    # Real server rejects unindexed conditional writes, while inventory reads still work.
    await w.client.update_collection(
        w.settings.qdrant_collection,
        strict_mode_config=StrictModeConfig(enabled=True, unindexed_filtering_update=False),
    )
    try:
        code, report = await run_apply_cli(w, subprocess_target)
        assert code == 2 and not report["complete"] and report["failed"] > 0
        assert report["error"] == "Payload update failed or uncertain"
        assert await snapshot(w) == before
    finally:
        await w.client.update_collection(
            w.settings.qdrant_collection, strict_mode_config=StrictModeConfig(enabled=False)
        )


async def test_new_exhaustive_verifier_detects_unattempted_orphan(world):
    w = world
    await missing_owners(w, (0,))
    added = False

    async def hook(t, request, phase):
        nonlocal added
        if request.url.path.endswith("/payload") and phase == "after" and not added:
            added = True
            await w.client.upsert(
                w.settings.qdrant_collection,
                [PointStruct(id=str(uuid4()), vector=[1.0, 0.0, 0.0], payload={})],
                wait=True,
            )

    client = AsyncQdrantClient(
        url=os.environ["QDRANT_TEST_URL"], transport=FaultTransport(hook), check_compatibility=False
    )
    try:
        result, code = await apply_repair(w.engine, client, w.settings, 6)
        assert added and code == 1 and not result["complete"]
        assert result["changed"] == 1
        assert (
            result["verification"]["complete"]
            and result["verification"]["issue_counts"]["orphan_point"] == 1
        )
    finally:
        await client.close()


async def test_second_owner_group_revalidates_after_first_write(world):
    w = world
    await missing_owners(w, tuple(range(6)))
    changed = False

    async def hook(t, request, phase):
        nonlocal changed
        if request.url.path.endswith("/payload") and phase == "after" and not changed:
            changed = True
            first_owner = json.loads(request.content)["payload"]["user_id"]
            other_owner = USER_B if first_owner == str(USER_A) else USER_A
            new_owner = USER_A if other_owner == USER_B else USER_B
            async with w.factory() as db:
                await db.execute(
                    update(DriveFile)
                    .where(DriveFile.user_id == other_owner)
                    .values(user_id=new_owner, drive_file_id="second-owner-race")
                )
                await db.commit()

    client = AsyncQdrantClient(
        url=os.environ["QDRANT_TEST_URL"], transport=FaultTransport(hook), check_compatibility=False
    )
    try:
        result, code = await apply_repair(w.engine, client, w.settings, 6)
        assert changed and code == 1 and not result["complete"]
        assert result["changed"] == 3 and result["blocked"] == 3
        records = await snapshot(w)
        assert sum(r.payload.get("user_id") is None for r in records) == 3
    finally:
        await client.close()
