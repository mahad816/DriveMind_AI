"""Read-only inventory against disposable PostgreSQL 16 and Qdrant 1.18."""

from datetime import UTC, datetime
import argparse
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from qdrant_client.models import Distance, PointStruct, VectorParams
from sqlalchemy import delete, select, event
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.enums import DriveFileStatus
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.db.models.user import User
from app.ops.qdrant_tenant_inventory import (
    classify,
    inventory,
    refuse_demo,
    InventoryError,
    run_cli,
)
from .conftest import USER_A, USER_B, DEMO_USER
from .test_owner_scoped_drive_identity import owner_engine, final_engine
from .test_qdrant_tenant_io import qdrant_client

__all__ = ["owner_engine", "final_engine", "qdrant_client"]


@pytest.fixture
async def world(owner_engine, qdrant_client, settings):
    settings.qdrant_collection = "tenant_inventory_test_" + uuid4().hex
    factory = async_sessionmaker(owner_engine, expire_on_commit=False)
    ids, points = [], []
    async with factory() as db:
        await db.execute(delete(User).where(User.id == DEMO_USER))
        for owner in (USER_A, USER_B):
            file = DriveFile(
                id=uuid4(),
                user_id=owner,
                drive_file_id="shared-provider-id",
                name="private.txt",
                mime_type="text/plain",
                modified_at=datetime.now(UTC),
                status=DriveFileStatus.INDEXED,
            )
            db.add(file)
            await db.flush()
            doc = Document(
                id=uuid4(),
                drive_file_id=file.id,
                extracted_text="PRIVATE-SYNTHETIC",
                extracted_text_hash="synthetic-hash",
            )
            db.add(doc)
            await db.flush()
            for index in range(3):
                chunk = Chunk(
                    id=uuid4(),
                    document_id=doc.id,
                    chunk_index=index,
                    text="PRIVATE-SYNTHETIC",
                    metadata_json={"extracted_text_hash": "synthetic-hash"},
                )
                db.add(chunk)
                ids.append(chunk.id)
                points.append(
                    PointStruct(
                        id=str(chunk.id),
                        vector=[1.0, 0.0, 0.0],
                        payload={
                            "chunk_id": str(chunk.id),
                            "drive_file_id": str(file.id),
                            "chunk_index": index,
                            "extracted_text_hash": "synthetic-hash",
                            "user_id": str(owner),
                            "extra": "preserved",
                        },
                    )
                )
        await db.commit()
    await qdrant_client.create_collection(
        settings.qdrant_collection, vectors_config=VectorParams(size=3, distance=Distance.COSINE)
    )
    await qdrant_client.upsert(settings.qdrant_collection, points, wait=True)
    yield SimpleNamespace(
        engine=owner_engine,
        client=qdrant_client,
        settings=settings,
        points=points,
        ids=ids,
        factory=factory,
    )
    await qdrant_client.delete_collection(settings.qdrant_collection)


async def scan(w):
    return await inventory(w.engine, w.client, w.settings, batch_size=2)


async def test_clean_paginated_deterministic_read_only(world):
    w = world
    before = await w.client.retrieve(
        w.settings.qdrant_collection, [str(i) for i in w.ids], with_vectors=True
    )
    query = select(Chunk.id, Chunk.text, Chunk.metadata_json)
    async with w.factory() as db:
        sql_before = (await db.execute(query.order_by(Chunk.id))).all()

    def read_only_sql(conn, cursor, statement, parameters, context, executemany):
        assert statement.lstrip().upper().startswith(("SELECT", "SET TRANSACTION"))

    event.listen(w.engine.sync_engine, "before_cursor_execute", read_only_sql)
    try:
        # Real read operations continue; any accidental mutation is a test failure.
        with (
            patch.object(
                w.client, "set_payload", AsyncMock(side_effect=AssertionError("write prohibited"))
            ),
            patch.object(
                w.client, "upsert", AsyncMock(side_effect=AssertionError("write prohibited"))
            ),
            patch.object(
                w.client, "delete", AsyncMock(side_effect=AssertionError("write prohibited"))
            ),
            patch.object(
                w.client,
                "create_payload_index",
                AsyncMock(side_effect=AssertionError("write prohibited")),
            ),
        ):
            report = await scan(w)
    finally:
        event.remove(w.engine.sync_engine, "before_cursor_execute", read_only_sql)
    assert report.as_dict()["clean"] and report.expected_points == report.scanned_points == 6
    assert (await scan(w)).as_dict() == report.as_dict()
    after = await w.client.retrieve(
        w.settings.qdrant_collection, [str(i) for i in w.ids], with_vectors=True
    )
    assert before == after
    async with w.factory() as db:
        assert (await db.execute(query.order_by(Chunk.id))).all() == sql_before
    assert "PRIVATE-SYNTHETIC" not in str(report.as_dict())


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("user_id", None, "missing_owner"),
        ("user_id", str(USER_B), "wrong_owner"),
        ("user_id", "secret-invalid-owner", "invalid_owner"),
        ("drive_file_id", str(uuid4()), "wrong_file_id"),
        ("extracted_text_hash", "bad", "wrong_hash"),
        ("chunk_id", None, "missing_provenance"),
        ("chunk_index", True, "wrong_chunk_index"),
    ],
)
async def test_payload_defects(world, field, value, code):
    point = world.points[0].model_copy(deep=True)
    point.payload[field] = value
    await world.client.upsert(world.settings.qdrant_collection, [point], wait=True)
    report = await scan(world)
    assert report.complete and report.issues[code] == 1 and not report.as_dict()["clean"]
    assert "secret-invalid-owner" not in str(report.as_dict())
    sample = next(s for s in report.samples if s["point_id"] == str(point.id))
    assert sample["owner_only_repairable"] == (code in {"missing_owner", "wrong_owner"})


async def test_equal_counts_different_identities(world):
    await world.client.delete(world.settings.qdrant_collection, [str(world.ids[0])], wait=True)
    point = world.points[0].model_copy(update={"id": str(uuid4())})
    await world.client.upsert(world.settings.qdrant_collection, [point], wait=True)
    report = await scan(world)
    assert report.expected_points == report.scanned_points
    assert report.issues == {"missing_point": 1, "orphan_point": 1}


async def test_ineligible_and_deleted(world):
    async with world.factory() as db:
        file = await db.scalar(select(DriveFile).where(DriveFile.user_id == USER_A))
        file.status = DriveFileStatus.SKIPPED
        await db.execute(delete(Chunk).where(Chunk.id == world.ids[-1]))
        await db.commit()
    report = await scan(world)
    assert report.issues["ineligible_point"] == 3 and report.issues["orphan_point"] == 1
    assert report.expected_points == 2


async def test_invalid_numeric_point(world):
    await world.client.upsert(
        world.settings.qdrant_collection,
        [PointStruct(id=17, vector=[1.0, 0.0, 0.0], payload={})],
        wait=True,
    )
    assert (await scan(world)).issues["invalid_point_id"] == 1


async def test_empty_and_storage_unavailable(world):
    async with world.factory() as db:
        await db.execute(delete(DriveFile))
        await db.commit()
    await world.client.delete(
        world.settings.qdrant_collection, [str(i) for i in world.ids], wait=True
    )
    report = await scan(world)
    assert report.as_dict()["empty"] and report.as_dict()["clean"]
    with patch.object(
        world.client, "scroll", AsyncMock(side_effect=RuntimeError("secret-provider"))
    ):
        report = await scan(world)
        assert not report.complete and report.error == "Storage inspection failed"
        assert "secret-provider" not in str(report.as_dict())
    with patch.object(type(world.engine), "connect", side_effect=RuntimeError("secret-database")):
        assert (await scan(world)).error == "Storage inspection failed"


async def test_premature_pagination(world):
    original = world.client.scroll

    async def short(*args, **kwargs):
        records, _ = await original(*args, **kwargs)
        return records, None

    with patch.object(world.client, "scroll", short):
        report = await scan(world)
    assert not report.complete and report.error == "Incomplete or changing collection inventory"


async def test_demo_target_rejected(world):
    world.settings.demo_mode = True
    assert (await scan(world)).error == "Demo targets are prohibited"
    world.settings.demo_mode = False
    async with world.factory() as db:
        db.add(User(id=DEMO_USER, google_id="demo:synthetic", email="demo@invalid.test"))
        await db.commit()
    assert (await scan(world)).error == "Demo targets are prohibited"
    world.settings.qdrant_collection = "harbordesk_demo"
    with pytest.raises(InventoryError, match="Demo targets"):
        refuse_demo(world.settings)
    world.settings.qdrant_collection = "tenant_inventory_test_unused"


def test_inconsistent_lineage_pure():
    row = SimpleNamespace(
        owner=None,
        file_id=None,
        document_id=None,
        status=None,
        chunk_hash="old",
        document_hash="new",
        chunk_index=0,
    )
    assert "inconsistent_lineage" in classify(uuid4(), {}, row)


async def test_missing_vector_and_chunk_link(world):
    point = world.points[0].model_copy(deep=True)
    point.vector = {}
    point.payload["chunk_id"] = str(world.ids[1])
    await world.client.upsert(world.settings.qdrant_collection, [point], wait=True)
    report = await scan(world)
    assert report.issues["invalid_vector"] == 1
    assert report.issues["wrong_chunk_link"] == 1


async def test_cli_json_and_exit_codes(world, monkeypatch, capsys):
    args = argparse.Namespace(
        command="verify",
        database_env="INVENTORY_TEST_DATABASE",
        qdrant_url="http://127.0.0.1:56335",
        collection=world.settings.qdrant_collection,
        batch_size=2,
        max_samples=1,
    )
    # Real isolated schema connection; CLI configuration, JSON and cleanup execute normally.
    monkeypatch.setenv(args.database_env, world.engine.url.render_as_string(hide_password=False))
    with patch("app.ops.qdrant_tenant_inventory.create_async_engine", return_value=world.engine):
        assert await run_cli(args) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["clean"] and output["complete"] and output["correct_points"] == 6
    assert "password" not in output["target"]
    point = world.points[0].model_copy(deep=True)
    point.payload["user_id"] = str(USER_B)
    await world.client.upsert(world.settings.qdrant_collection, [point], wait=True)
    with patch("app.ops.qdrant_tenant_inventory.create_async_engine", return_value=world.engine):
        assert await run_cli(args) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["issue_counts"] == {"wrong_owner": 1}
    monkeypatch.delenv(args.database_env)
    assert await run_cli(args) == 2
    assert not json.loads(capsys.readouterr().out)["complete"]


async def test_nonprogressing_pagination_and_bounded_samples(world):
    original = world.client.scroll
    first, offset = await original(world.settings.qdrant_collection, limit=2, with_vectors=True)
    with patch.object(world.client, "scroll", AsyncMock(return_value=(first, offset))):
        report = await scan(world)
    assert not report.complete and report.error == "Non-progressing point pagination"
    for point in world.points:
        point.payload["user_id"] = None
    await world.client.upsert(world.settings.qdrant_collection, world.points, wait=True)
    report = await inventory(world.engine, world.client, world.settings, 2, 1)
    assert report.issues["missing_owner"] == 6 and len(report.samples) == 1
    assert report.as_dict()["samples_truncated"]


async def test_collection_identified_as_demo_by_payload(world):
    from app.demo.manifest import load_manifest

    point = world.points[0].model_copy(deep=True)
    point.payload["drive_file_id"] = str(load_manifest().files[0].id)
    await world.client.upsert(world.settings.qdrant_collection, [point], wait=True)
    assert (await scan(world)).error == "Demo targets are prohibited"
