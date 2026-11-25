"""Structured failure classes on terminal jobs (Checkpoint A).

The queue may continue past a failed document only when the backend says, by this field, that the failure is
specific to the document ("document"). Everything else, and anything unrecorded, must leave the field as
anything but "document". Real PostgreSQL claims; Google, embedding and Qdrant faults are injected.
"""

import asyncio
from datetime import UTC, datetime

import pytest

from app.connectors.google_drive.client import DriveClientError
from app.db.enums import DriveFileStatus, IndexingJobStatus, IndexingOperation
from app.db.models.drive_file import DriveFile
from app.embeddings.base import EmbeddingError
from app.services.indexing_classifier import IndexingClassifier
from app.services.indexing_worker import IndexingWorker
from .conftest import USER_A
from .test_indexing_leases import expire
from .test_indexing_worker import (
    Embeddings,
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


async def one_file(w, name, mime, provider):
    async with w.factory() as db:
        f = DriveFile(
            user_id=USER_A,
            drive_file_id=provider,
            name=name,
            mime_type=mime,
            modified_at=datetime.now(UTC),
        )
        db.add(f)
        await db.commit()
        return f.id


def counters(row):
    return (row.total, row.processed, row.succeeded, row.failed, row.skipped)


async def test_corrupt_document_is_the_one_case_classified_document(world, monkeypatch):
    w = world
    original = w.google.get_file_content
    monkeypatch.setattr(
        w.google,
        "get_file_content",
        lambda client, provider, mime: (
            b"not a pdf" if provider == "corrupt" else original(client, provider, mime)
        ),
    )
    fid = await one_file(w, "broken.pdf", "application/pdf", "corrupt")
    jid = await enqueue(w, IndexingOperation.INGEST, file_id=fid)
    await w.worker.run_once()
    row = await job(w, jid)
    assert row.status == IndexingJobStatus.FAILED and counters(row) == (1, 1, 0, 1, 0)
    assert row.failure_class == "document" and not row.recovery_required


@pytest.mark.parametrize(
    "category,expected",
    [
        (None, "unknown"),
        ("unexpected_failure", "unknown"),
        ("authentication_expired", "authentication"),
        ("reauthorization_required", "authentication"),
        ("temporary_provider_failure", "provider"),
        ("configuration_error", "configuration"),
    ],
)
async def test_drive_failure_is_never_called_document_specific(
    world, monkeypatch, category, expected
):
    w = world

    def download(client, provider, mime):
        raise DriveClientError(
            "secret-provider-body", **({"category": category} if category else {})
        )

    monkeypatch.setattr(w.google, "get_file_content", download)
    jid = await enqueue(w, IndexingOperation.INGEST, file_id=w.files[USER_A])
    await w.worker.run_once()
    row = await job(w, jid)
    assert row.status == IndexingJobStatus.FAILED and counters(row) == (1, 1, 0, 1, 0)
    assert row.failure_class == expected and "secret-provider-body" not in (row.error or "")


async def test_embedding_provider_failure_reported_as_a_file_failure_is_provider(world):
    w = world

    class Down(Embeddings):
        async def embed_texts(self, texts):
            raise EmbeddingError("secret-provider-body")

    w.worker.embedding_service = Down()
    await document(w)
    jid = await enqueue(w, IndexingOperation.BUILD, file_id=w.files[USER_A])
    await w.worker.run_once()
    row = await job(w, jid)
    assert row.status == IndexingJobStatus.FAILED and counters(row)[1:4] == (1, 0, 1)
    assert row.failure_class == "provider"
    async with w.factory() as db:
        assert (await db.get(DriveFile, w.files[USER_A])).status == DriveFileStatus.FAILED


async def test_vector_store_rejection_reported_as_a_file_failure_is_provider(world, monkeypatch):
    w = world
    from qdrant_client import AsyncQdrantClient
    from qdrant_client.models import Distance, VectorParams

    await document(w)
    await w.client.create_collection(
        w.settings.qdrant_collection, vectors_config=VectorParams(size=3, distance=Distance.COSINE)
    )
    original = AsyncQdrantClient.upsert

    async def rejected(client, **kwargs):
        kwargs["points"] = [
            p.model_copy(update={"vector": [1.0, 0.0, 0.0, 0.0]}) for p in kwargs["points"]
        ]
        return await original(client, **kwargs)

    monkeypatch.setattr(AsyncQdrantClient, "upsert", rejected)
    jid = await enqueue(w, IndexingOperation.BUILD, file_id=w.files[USER_A])
    await w.worker.run_once()
    row = await job(w, jid)
    assert row.status == IndexingJobStatus.FAILED and row.failure_class == "provider"


async def test_unexpected_stage_exception_is_unknown(world, monkeypatch):
    w = world
    from app.services.chunking_service import ChunkingService

    async def boom(service, doc, **kwargs):
        raise RuntimeError("secret-marker")

    monkeypatch.setattr(ChunkingService, "_replace_chunks", boom)
    await document(w)
    jid = await enqueue(w, IndexingOperation.CHUNK, file_id=w.files[USER_A])
    await w.worker.run_once()
    row = await job(w, jid)
    assert row.status == IndexingJobStatus.FAILED and row.failure_class == "unknown"
    assert "secret-marker" not in (row.error or "")


async def test_heartbeat_failure_is_infrastructure(world):
    w = world
    entered = asyncio.Event()

    class Blocking(Embeddings):
        async def embed_texts(self, texts):
            entered.set()
            await asyncio.Event().wait()
            return []

    worker = IndexingWorker(
        w.factory, w.settings, embedding_service=Blocking(), heartbeat_seconds=0.02
    )
    original, count = worker.renew_lease, 0

    async def renew(claim):
        nonlocal count
        count += 1
        if count > 1:
            await entered.wait()
            raise RuntimeError("synthetic")
        await original(claim)

    worker.renew_lease = renew
    await document(w)
    jid = await enqueue(w, IndexingOperation.BUILD, file_id=w.files[USER_A])
    await asyncio.wait_for(worker.run_once(), 5)
    row = await job(w, jid)
    assert row.error == "Indexing heartbeat failed." and row.failure_class == "infrastructure"


async def test_interrupted_execution_is_infrastructure(world):
    w = world
    entered = asyncio.Event()

    class Blocked(Embeddings):
        async def embed_texts(self, texts):
            entered.set()
            await asyncio.Event().wait()
            return []

    w.worker.embedding_service = Blocked()
    await document(w)
    jid = await enqueue(w, IndexingOperation.BUILD, file_id=w.files[USER_A])
    task = asyncio.create_task(w.worker.run_once())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await job(w, jid)).failure_class == "infrastructure"


@pytest.mark.parametrize("operation", [IndexingOperation.INGEST, IndexingOperation.CHUNK])
async def test_lease_expiry_after_a_server_restart_is_infrastructure(world, operation):
    w = world
    await document(w)
    jid = await enqueue(w, operation, file_id=w.files[USER_A])
    claim = await w.worker.claim_next()
    assert claim is not None and claim.job_id == jid
    await expire(w, claim)
    assert await IndexingClassifier(w.worker).classify(jid) == "FAILED"
    row = await job(w, jid)
    assert row.status == IndexingJobStatus.FAILED and not row.recovery_required
    assert row.failure_class == "infrastructure"


async def test_missing_ocr_engine_is_configuration_through_the_whole_job(world, monkeypatch):
    """Regression: this used to be recorded as "document", letting the queue move past an environment fault."""
    import io

    from PIL import Image
    from pytesseract import TesseractNotFoundError

    png = io.BytesIO()
    Image.new("RGB", (4, 4)).save(png, "PNG")
    w = world
    original = w.google.get_file_content
    monkeypatch.setattr(
        w.google,
        "get_file_content",
        lambda client, provider, mime: (
            png.getvalue() if provider == "image-provider" else original(client, provider, mime)
        ),
    )

    def missing(_image):
        raise TesseractNotFoundError()

    monkeypatch.setattr("pytesseract.image_to_string", missing)
    fid = await one_file(w, "scan.png", "image/png", "image-provider")
    jid = await enqueue(w, IndexingOperation.INGEST, file_id=fid)
    await w.worker.run_once()
    row = await job(w, jid)
    assert row.status == IndexingJobStatus.FAILED and counters(row) == (1, 1, 0, 1, 0)
    assert row.failure_class == "configuration"


async def test_unexpected_extractor_fault_is_unknown_through_the_whole_job(world, monkeypatch):
    w = world
    original = w.google.get_file_content
    monkeypatch.setattr(
        w.google,
        "get_file_content",
        lambda client, provider, mime: (
            b"%PDF-1.4 x" if provider == "odd" else original(client, provider, mime)
        ),
    )

    def boom(*_args, **_kwargs):
        raise RuntimeError("secret-extractor-detail")

    monkeypatch.setattr("app.ingestion.extractors.pdf.extract_pdf_text", boom)
    fid = await one_file(w, "odd.pdf", "application/pdf", "odd")
    jid = await enqueue(w, IndexingOperation.INGEST, file_id=fid)
    await w.worker.run_once()
    row = await job(w, jid)
    assert row.status == IndexingJobStatus.FAILED and row.failure_class == "unknown"
    assert "secret-extractor-detail" not in (row.error or "")


async def test_skipped_document_completes_without_a_failure_class(world, monkeypatch):
    """The definite-skip shape the client relies on: completed, one processed, one skipped, nothing failed."""
    w = world
    original = w.google.get_file_content
    monkeypatch.setattr(
        w.google,
        "get_file_content",
        lambda client, provider, mime: (
            b"   \n " if provider == "blank" else original(client, provider, mime)
        ),
    )
    fid = await one_file(w, "blank.txt", "text/plain", "blank")
    jid = await enqueue(w, IndexingOperation.INGEST, file_id=fid)
    await w.worker.run_once()
    row = await job(w, jid)
    assert row.status == IndexingJobStatus.COMPLETED and counters(row) == (1, 1, 0, 0, 1)
    assert row.failure_class is None and not row.recovery_required
    async with w.factory() as db:
        assert (await db.get(DriveFile, fid)).status == DriveFileStatus.SKIPPED


async def test_success_and_skip_carry_no_failure_class(world):
    w = world
    await document(w)
    jid = await enqueue(w, IndexingOperation.CHUNK, file_id=w.files[USER_A])
    await w.worker.run_once()
    row = await job(w, jid)
    assert row.status == IndexingJobStatus.COMPLETED and row.failure_class is None


async def test_migration_round_trip_keeps_old_rows_unclassified(world):
    """Upgrade and downgrade both run; a row that predates the column reads as unclassified (clients pause)."""
    from sqlalchemy import text
    from .conftest import FAILURE_CLASS_REVISION, apply_revision

    w = world
    jid = await enqueue(w, IndexingOperation.CHUNK, file_id=w.files[USER_A])
    async with w.engine.begin() as connection:
        await connection.run_sync(apply_revision, FAILURE_CLASS_REVISION, downgrade=True)
        columns = await connection.scalar(
            text(
                "SELECT count(*) FROM information_schema.columns WHERE table_name='indexing_jobs' "
                "AND column_name='failure_class' AND table_schema = current_schema()"
            )
        )
        assert columns == 0
        await connection.run_sync(apply_revision, FAILURE_CLASS_REVISION)
        assert (
            await connection.scalar(
                text("SELECT failure_class FROM indexing_jobs WHERE id = :id"), {"id": jid}
            )
            is None
        )
