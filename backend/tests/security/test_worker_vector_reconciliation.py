"""Real-store BUILD reconciliation and collection compatibility regressions."""

from uuid import UUID, uuid4
from datetime import UTC, datetime

import pytest
from qdrant_client.models import Distance, PointStruct, VectorParams
from sqlalchemy import select, update

from app.db.enums import DriveFileStatus, IndexingJobStatus, IndexingOperation
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.services.chunking_service import ChunkingService
from .conftest import DEMO_USER, USER_A, USER_B
from .test_indexing_worker import (
    document,
    enqueue,
    final_engine,
    job,
    keys,
    owner_engine,
    qdrant_client,
    world,
)

__all__ = ["world", "final_engine", "keys", "owner_engine", "qdrant_client"]


async def prepare(w, owner):
    document_id = await document(w, owner)
    async with w.factory() as db:
        doc = await db.get(Document, document_id)
        await ChunkingService(db, w.settings)._replace_chunks(doc)
        await db.commit()
        return list((await db.scalars(select(Chunk).where(Chunk.document_id == doc.id))).all())


def payload(w, owner, chunk):
    return {
        "chunk_id": str(chunk.id),
        "drive_file_id": str(w.files[owner]),
        "user_id": str(owner),
        "extracted_text_hash": chunk.metadata_json["extracted_text_hash"],
        "extra": "synthetic-preserved-metadata",
    }


async def points(w):
    records, offset = await w.client.scroll(
        w.settings.qdrant_collection, limit=100, with_vectors=True
    )
    assert offset is None
    return {str(record.id): record.model_dump() for record in records}


@pytest.mark.parametrize("variant", ["foreign_payload", "owned_payload", "foreign_sql"])
async def test_malformed_point_cannot_redirect_reconciliation(world, variant):
    w = world
    a = (await prepare(w, USER_A))[0]
    b = (await prepare(w, USER_B))[0]
    await w.client.create_collection(
        w.settings.qdrant_collection, vectors_config=VectorParams(size=3, distance=Distance.COSINE)
    )
    # The SQL variant spoofs all payload fields on B's actual point. Only
    # authoritative SQL lineage can distinguish it from an orphaned stale point.
    malformed_id = b.id if variant == "foreign_sql" else uuid4()
    malformed = payload(w, USER_A, a)
    malformed["chunk_id"] = str(a.id if variant == "owned_payload" else b.id)
    initial = [PointStruct(id=str(b.id), vector=[1.0, 0.0, 0.0], payload=payload(w, USER_B, b))]
    if variant == "foreign_sql":
        initial = []
    initial.append(PointStruct(id=str(malformed_id), vector=[1.0, 0.0, 0.0], payload=malformed))
    await w.client.upsert(w.settings.qdrant_collection, points=initial, wait=True)
    async with w.factory() as db:
        await db.execute(
            update(DriveFile)
            .where(DriveFile.id == w.files[USER_B])
            .values(status=DriveFileStatus.INDEXED)
        )
        await db.commit()
    before = await points(w)
    jid = await enqueue(w, IndexingOperation.BUILD, file_id=w.files[USER_A])
    await w.worker.run_once()
    result = await job(w, jid)
    assert result.status == IndexingJobStatus.FAILED
    assert result.recovery_required
    assert await points(w) == before
    async with w.factory() as db:
        assert (await db.get(DriveFile, w.files[USER_A])).status == DriveFileStatus.FAILED
        assert (await db.get(DriveFile, w.files[USER_B])).status == DriveFileStatus.INDEXED


@pytest.mark.parametrize("configuration", ["dimension", "distance", "named", "compatible"])
@pytest.mark.parametrize("unchanged", [True, False])
async def test_existing_collection_is_validated_before_any_point_mutation(
    world, configuration, unchanged, caplog
):
    w = world
    a = (await prepare(w, USER_A))[0]
    b = (await prepare(w, USER_B))[0]
    size = 4 if configuration == "dimension" else 3
    params = VectorParams(
        size=size, distance=Distance.DOT if configuration == "distance" else Distance.COSINE
    )
    await w.client.create_collection(
        w.settings.qdrant_collection,
        vectors_config={"other": params} if configuration == "named" else params,
    )
    initial = []
    for owner, chunk in [(USER_A, a), (USER_B, b)]:
        if owner == USER_A and not unchanged:
            continue
        vector = [1.0] + [0.0] * (size - 1)
        initial.append(
            PointStruct(
                id=str(chunk.id),
                vector={"other": vector} if configuration == "named" else vector,
                payload=payload(w, owner, chunk),
            )
        )
    await w.client.upsert(w.settings.qdrant_collection, points=initial, wait=True)
    before = await points(w)
    calls = []
    original_embed = w.worker.embedding_service.embed_texts

    async def embed(texts):
        calls.extend(texts)
        return await original_embed(texts)

    w.worker.embedding_service.embed_texts = embed
    jid = await enqueue(w, IndexingOperation.BUILD, file_id=w.files[USER_A])
    await w.worker.run_once()
    result = await job(w, jid)
    after = await points(w)
    assert after[str(b.id)] == before[str(b.id)]
    async with w.factory() as db:
        status = (await db.get(DriveFile, w.files[USER_A])).status
    if configuration != "compatible":
        assert result.status == IndexingJobStatus.FAILED
        assert status == DriveFileStatus.FAILED
        assert not result.recovery_required  # No point mutation was attempted.
        assert before == after
        assert not calls
        assert "unnamed COSINE vectors matching the configured embedding dimension" in caplog.text
    else:
        assert result.status == IndexingJobStatus.COMPLETED
        assert status == DriveFileStatus.INDEXED
        assert bool(calls) == (not unchanged)
        if unchanged:
            assert before == after


@pytest.mark.parametrize("legacy_owner", [None, "foreign"])
async def test_healthy_stale_cleanup_is_owner_scoped_and_preserves_legacy_points(
    world, legacy_owner
):
    w = world
    a = (await prepare(w, USER_A))[0]
    b = (await prepare(w, USER_B))[0]
    await w.client.create_collection(
        w.settings.qdrant_collection, vectors_config=VectorParams(size=3, distance=Distance.COSINE)
    )
    stale_id, excluded_id = uuid4(), uuid4()
    stale = payload(w, USER_A, a) | {"chunk_id": str(stale_id)}
    excluded = payload(w, USER_A, a) | {"chunk_id": str(excluded_id)}
    if legacy_owner is None:
        del excluded["user_id"]
    else:
        excluded["user_id"] = str(USER_B)
    # A's current point is ownerless but conclusively linked in SQL: ordinary
    # unchanged-point repair must remain supported, without re-embedding it.
    current = payload(w, USER_A, a)
    del current["user_id"]
    await w.client.upsert(
        w.settings.qdrant_collection,
        points=[
            PointStruct(id=str(i), vector=[1.0, 0.0, 0.0], payload=p)
            for i, p in [
                (a.id, current),
                (b.id, payload(w, USER_B, b)),
                (stale_id, stale),
                (excluded_id, excluded),
            ]
        ],
        wait=True,
    )
    before = await points(w)

    async def forbidden_embedding(texts):
        pytest.fail("Unchanged vectors must not be re-embedded")

    w.worker.embedding_service.embed_texts = forbidden_embedding
    jid = await enqueue(w, IndexingOperation.BUILD, file_id=w.files[USER_A])
    await w.worker.run_once()
    assert (await job(w, jid)).status == IndexingJobStatus.COMPLETED
    after = await points(w)
    assert str(stale_id) not in after
    assert after[str(b.id)] == before[str(b.id)]
    assert after[str(excluded_id)] == before[str(excluded_id)]
    expected = before[str(a.id)]
    expected["payload"]["user_id"] = str(USER_A)
    assert after[str(a.id)] == expected


@pytest.mark.parametrize("defect", ["file", "hash"])
async def test_current_point_with_inconsistent_provenance_is_not_repaired(world, defect):
    w = world
    a = (await prepare(w, USER_A))[0]
    await w.client.create_collection(
        w.settings.qdrant_collection, vectors_config=VectorParams(size=3, distance=Distance.COSINE)
    )
    malformed = payload(w, USER_A, a)
    if defect == "file":
        malformed["drive_file_id"] = str(w.files[USER_B])
    else:
        malformed["extracted_text_hash"] = None
    await w.client.upsert(
        w.settings.qdrant_collection,
        points=[PointStruct(id=str(a.id), vector=[1.0, 0.0, 0.0], payload=malformed)],
        wait=True,
    )
    before = await points(w)
    jid = await enqueue(w, IndexingOperation.BUILD, file_id=w.files[USER_A])
    await w.worker.run_once()
    result = await job(w, jid)
    assert result.status == IndexingJobStatus.FAILED and result.recovery_required
    assert await points(w) == before


async def test_unconfirmed_cleanup_is_failed_and_keeps_recovery_required(world, monkeypatch):
    from qdrant_client import AsyncQdrantClient
    from qdrant_client.models import UpdateResult, UpdateStatus
    from app.services.indexing_job_service import IndexingAdmissionConflict

    w = world
    a = (await prepare(w, USER_A))[0]
    b = (await prepare(w, USER_B))[0]
    await w.client.create_collection(
        w.settings.qdrant_collection, vectors_config=VectorParams(size=3, distance=Distance.COSINE)
    )
    stale_id = uuid4()
    await w.client.upsert(
        w.settings.qdrant_collection,
        points=[
            PointStruct(id=str(b.id), vector=[1.0, 0.0, 0.0], payload=payload(w, USER_B, b)),
            PointStruct(
                id=str(stale_id),
                vector=[1.0, 0.0, 0.0],
                payload=payload(w, USER_A, a) | {"chunk_id": str(stale_id)},
            ),
        ],
        wait=True,
    )
    before = await points(w)
    original = AsyncQdrantClient.delete

    async def uncertain(client, **kwargs):
        await original(client, **kwargs)  # Actual deletion precedes the uncertain response.
        return UpdateResult(operation_id=1, status=UpdateStatus.ACKNOWLEDGED)

    monkeypatch.setattr(AsyncQdrantClient, "delete", uncertain)
    jid = await enqueue(w, IndexingOperation.BUILD, file_id=w.files[USER_A])
    await w.worker.run_once()
    result = await job(w, jid)
    assert result.status == IndexingJobStatus.FAILED and result.recovery_required
    after = await points(w)
    assert str(stale_id) not in after
    assert after[str(b.id)] == before[str(b.id)]
    with pytest.raises(IndexingAdmissionConflict):
        await enqueue(w, IndexingOperation.BUILD)


async def test_configuration_rejection_cannot_clear_earlier_uncertain_write(world, monkeypatch):
    from qdrant_client import AsyncQdrantClient
    from qdrant_client.models import UpdateResult, UpdateStatus
    from app.embeddings.vector_store import CollectionCompatibilityError, QdrantVectorStore

    w = world
    await prepare(w, USER_A)
    async with w.factory() as db:
        extra = DriveFile(
            id=UUID(int=500),
            user_id=USER_A,
            drive_file_id="extra-provider",
            name="extra.txt",
            mime_type="text/plain",
            status=DriveFileStatus.INDEXING,
            modified_at=datetime(2026, 10, 12, tzinfo=UTC),
        )
        db.add(extra)
        await db.flush()
        db.add(
            Document(
                drive_file_id=extra.id,
                extracted_text="Extra owned text.",
                extracted_text_hash="extra-hash",
            )
        )
        await db.commit()
    original_ensure = QdrantVectorStore.ensure_collection
    original_upsert = AsyncQdrantClient.upsert
    ensures = 0

    async def ensure(store, **kwargs):
        nonlocal ensures
        ensures += 1
        if ensures == 2:
            raise CollectionCompatibilityError("Synthetic second-file configuration rejection")
        await original_ensure(store, **kwargs)

    async def uncertain(client, **kwargs):
        await original_upsert(client, **kwargs)
        return UpdateResult(operation_id=1, status=UpdateStatus.ACKNOWLEDGED)

    monkeypatch.setattr(QdrantVectorStore, "ensure_collection", ensure)
    monkeypatch.setattr(AsyncQdrantClient, "upsert", uncertain)
    jid = await enqueue(w, IndexingOperation.BUILD)
    await w.worker.run_once()
    result = await job(w, jid)
    assert ensures == 2
    assert result.status == IndexingJobStatus.FAILED and result.recovery_required
    assert result.processed == result.failed == 2
    assert (await w.client.count(w.settings.qdrant_collection, exact=True)).count == 1


async def test_concurrent_creation_cannot_hide_incompatible_configuration(world, monkeypatch):
    from app.embeddings.vector_store import CollectionCompatibilityError, QdrantVectorStore

    w = world
    original = w.client.create_collection

    async def competing_create(**kwargs):
        # Another creator wins between collection_exists and our create request.
        await original(
            w.settings.qdrant_collection,
            vectors_config=VectorParams(size=4, distance=Distance.COSINE),
        )
        return await original(**kwargs)  # Genuine server-side already-exists response.

    monkeypatch.setattr(w.client, "create_collection", competing_create)
    store = QdrantVectorStore(w.settings, client=w.client)
    with pytest.raises(CollectionCompatibilityError):
        await store.ensure_collection(vector_size=3)
    info = await w.client.get_collection(w.settings.qdrant_collection)
    assert not info.payload_schema
    assert (await w.client.count(w.settings.qdrant_collection, exact=True)).count == 0


async def test_offline_demo_build_preserves_ownerless_payloads_and_removes_stale_points(world):
    from app.embeddings.vector_store import QdrantVectorStore
    from app.services.indexing_service import IndexingService
    from .test_indexing_worker import Embeddings

    w = world
    settings = w.settings.model_copy(
        update={
            "demo_mode": True,
            "demo_user_id": str(DEMO_USER),
            "qdrant_collection": "drivemind_demo_reconciliation_test_" + uuid4().hex,
        }
    )
    async with w.factory() as db:
        file = DriveFile(
            user_id=DEMO_USER,
            drive_file_id="synthetic-demo-file",
            name="demo.txt",
            mime_type="text/plain",
            modified_at=datetime(2026, 10, 12, tzinfo=UTC),
            status=DriveFileStatus.INDEXING,
        )
        db.add(file)
        await db.flush()
        doc = Document(
            drive_file_id=file.id,
            extracted_text="Synthetic demo text.",
            extracted_text_hash="demo-hash",
        )
        db.add(doc)
        await db.flush()
        await ChunkingService(db, settings)._replace_chunks(doc)
        await db.commit()
        chunk = await db.scalar(select(Chunk).where(Chunk.document_id == doc.id))
        file_id, chunk_id = file.id, chunk.id
    store = QdrantVectorStore(settings, client=w.client, verify_writes=True)
    await store.ensure_collection(vector_size=3)
    try:
        stale_id = uuid4()
        await w.client.upsert(
            settings.qdrant_collection,
            points=[
                PointStruct(
                    id=str(i),
                    vector=[1.0, 0.0, 0.0],
                    payload={
                        "chunk_id": str(i),
                        "drive_file_id": str(file_id),
                        "extracted_text_hash": "demo-hash",
                    },
                )
                for i in (chunk_id, stale_id)
            ],
            wait=True,
        )
        async with w.factory() as db:
            result = await IndexingService(
                db,
                settings,
                embedding_service=Embeddings(),
                vector_store=store,
            ).build_index(user_id=DEMO_USER, file_id=file_id)
        assert result.failed == result.embedded == 0
        assert result.unchanged == result.removed == 1
        records, offset = await w.client.scroll(settings.qdrant_collection, with_vectors=True)
        assert offset is None and len(records) == 1
        assert records[0].id == str(chunk_id)
        assert "user_id" not in records[0].payload
        assert records[0].vector == [1.0, 0.0, 0.0]
    finally:
        await w.client.delete_collection(settings.qdrant_collection)
