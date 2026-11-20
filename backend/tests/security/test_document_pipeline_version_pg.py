"""The extraction pipeline version, against a real PostgreSQL (disposable, isolated schema).

What must hold:

* the migration marks every existing document as produced by the first pipeline (version 1) and is
  reversible;
* an indexed file read by an older pipeline is found again (ingest list and pending counts agree),
  while up-to-date, unindexed or document-less files are not;
* re-reading it replaces the text and queues re-chunking when the new reader finds more, and only
  stamps the version (file stays indexed, chunks untouched) when the text is identical;
* a current file is never downloaded again.
"""

from datetime import UTC, datetime
from io import BytesIO
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from docx import Document as WordDocument
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.connectors.google_drive.constants import DOCX_MIME, GOOGLE_DOC_MIME, TXT_MIME
from app.core.config import Settings
from app.db.enums import DriveFileStatus
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.ingestion.extractors import register_builtin_extractors
from app.ingestion.hash_util import compute_extracted_text_hash
from app.ingestion.pipeline_version import EXTRACTION_PIPELINE_VERSION
from app.services.drive_content_service import DriveFileContent
from app.services.drive_sync_service import DriveSyncService
from app.services.ingestion_queries import stale_pipeline_clause
from app.services.ingestion_service import IngestionService

from .conftest import (
    BACKEND,
    BASE_REVISION,
    PIPELINE_VERSION_REVISION,
    SESSION_REVISION,
    USER_A,
    apply_revision,
)

OLD_TEXT = "Package Pilot 1 1,200 2 Package Regional 5 4,500 4"


def docx_with_table() -> bytes:
    document = WordDocument()
    document.add_heading("Packages", level=1)
    table = document.add_table(rows=2, cols=2)
    for (row, col), value in {
        (0, 0): "Package",
        (0, 1): "Fee",
        (1, 0): "Pilot",
        (1, 1): "1,200",
    }.items():
        table.cell(row, col).text = value
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


async def add_file(
    db: AsyncSession,
    *,
    name: str,
    status: DriveFileStatus = DriveFileStatus.INDEXED,
    mime_type: str = GOOGLE_DOC_MIME,
    body: str | None = OLD_TEXT,
    version: int | None = 1,
    owner: UUID = USER_A,
) -> DriveFile:
    drive_file = DriveFile(
        id=uuid4(),
        user_id=owner,
        drive_file_id=f"g-{uuid4()}",
        name=name,
        mime_type=mime_type,
        modified_at=datetime(2026, 1, 1, tzinfo=UTC),
        status=status,
    )
    db.add(drive_file)
    await db.flush()
    if body is not None:
        document = Document(
            id=uuid4(),
            drive_file_id=drive_file.id,
            extracted_text=body,
            extracted_text_hash=compute_extracted_text_hash(body),
            **({} if version is None else {"pipeline_version": version}),
        )
        db.add(document)
        await db.flush()
        db.add(
            Chunk(
                id=uuid4(),
                document_id=document.id,
                chunk_index=0,
                text=body,
                metadata_json={"extracted_text_hash": document.extracted_text_hash},
            )
        )
    await db.flush()
    return drive_file


@pytest.fixture
async def factory(pg_engine):
    register_builtin_extractors()
    return async_sessionmaker(pg_engine, expire_on_commit=False)


@pytest.fixture
async def full_schema(pg_engine):
    """Bring the shared test schema to the real head (an ingest run writes an ``indexing_jobs`` row)."""
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("path_separator", "os")
    order = [
        r.revision for r in reversed(list(ScriptDirectory.from_config(config).walk_revisions()))
    ]
    already = set(order[: order.index(BASE_REVISION) + 1]) | {
        SESSION_REVISION,
        PIPELINE_VERSION_REVISION,
    }
    async with pg_engine.begin() as connection:
        for revision in order:
            if revision not in already:
                await connection.run_sync(apply_revision, revision)


def service(db: AsyncSession, settings: Settings, content: AsyncMock) -> IngestionService:
    return IngestionService(db=db, settings=settings, content_service=content)


def content_returning(data: bytes, mime_type: str) -> AsyncMock:
    content = AsyncMock()
    content.fetch_file_content = AsyncMock(
        return_value=DriveFileContent(
            data=data, mime_type=mime_type, filename="x", drive_file_id="g"
        )
    )
    return content


# ---- migration -------------------------------------------------------------------------------------


async def test_migration_marks_existing_documents_as_version_one_and_is_reversible(pg_engine):
    async with pg_engine.begin() as connection:
        await connection.run_sync(apply_revision, PIPELINE_VERSION_REVISION, downgrade=True)
        columns = await connection.scalar(
            text(
                "SELECT count(*) FROM information_schema.columns WHERE table_name = 'documents' "
                "AND column_name = 'pipeline_version' AND table_schema = current_schema()"
            )
        )
        assert columns == 0
        file_id = uuid4()
        await connection.execute(
            text(
                "INSERT INTO drive_files (id, user_id, drive_file_id, name, mime_type, modified_at, "
                "status) VALUES (:i, :u, 'g-legacy', 'legacy.txt', 'text/plain', now(), 'INDEXED')"
            ),
            {"i": file_id, "u": USER_A},
        )
        await connection.execute(
            text(
                "INSERT INTO documents (id, drive_file_id, extracted_text, extracted_text_hash) "
                "VALUES (:d, :f, 'legacy text', 'h')"
            ),
            {"d": uuid4(), "f": file_id},
        )
        await connection.run_sync(apply_revision, PIPELINE_VERSION_REVISION)
        assert await connection.scalar(text("SELECT pipeline_version FROM documents")) == 1


async def test_a_new_document_is_stamped_with_the_current_pipeline_version(factory):
    async with factory.begin() as db:
        drive_file = await add_file(db, name="new.txt", version=None)
        stored = await db.scalar(
            select(Document.pipeline_version).where(Document.drive_file_id == drive_file.id)
        )
    assert stored == EXTRACTION_PIPELINE_VERSION


# ---- which files are found again ------------------------------------------------------------------


async def test_only_indexed_files_with_an_older_pipeline_are_selected(factory, settings):
    async with factory.begin() as db:
        stale = await add_file(db, name="stale.docx", version=1)
        await add_file(db, name="current.docx", version=EXTRACTION_PIPELINE_VERSION)
        await add_file(db, name="mid_pipeline.docx", version=1, status=DriveFileStatus.INDEXING)
        await add_file(db, name="no_document.docx", body=None)
        await add_file(db, name="skipped.docx", version=1, status=DriveFileStatus.SKIPPED)
        await add_file(db, name="other_owner.docx", version=1, owner=UUID(int=102))
        selected = set(await db.scalars(select(DriveFile.name).where(stale_pipeline_clause())))
        assert selected == {"stale.docx", "other_owner.docx"}

        listed = await service(db, settings, AsyncMock())._list_ingestible_files(USER_A)
        assert {f.name for f in listed} == {"stale.docx", "mid_pipeline.docx"}
        assert stale.id in {f.id for f in listed}


async def test_pending_counts_ask_for_ingest_exactly_when_the_ingest_list_is_not_empty(
    factory, settings
):
    async with factory.begin() as db:
        await add_file(db, name="current.docx", version=EXTRACTION_PIPELINE_VERSION)
        counts = await DriveSyncService(db, settings).get_pending_counts(USER_A)
        assert counts.to_ingest == 0 and not counts.any_pending

        await add_file(db, name="stale.docx", version=1)
        counts = await DriveSyncService(db, settings).get_pending_counts(USER_A)
        assert counts.to_ingest == 1 and counts.any_pending


# ---- what re-reading does ----------------------------------------------------------------------------


async def ingest(factory, settings, content: AsyncMock):
    """Run the service the way the app does: its own session, committing its own work."""
    async with factory() as db:
        return await service(db, settings, content).ingest_files(USER_A)


async def stored(factory, drive_file: DriveFile) -> tuple[DriveFile, Document, list[Chunk]]:
    async with factory() as db:
        file = await db.get(DriveFile, drive_file.id)
        document = await db.scalar(select(Document).where(Document.drive_file_id == drive_file.id))
        assert file is not None and document is not None
        chunks = list(await db.scalars(select(Chunk).where(Chunk.document_id == document.id)))
        return file, document, chunks


async def test_a_stale_file_is_replaced_by_the_richer_text_and_queued_for_rechunking(
    factory, full_schema, settings
):
    async with factory.begin() as db:
        stale = await add_file(db, name="plan.docx", version=1)
    result = await ingest(factory, settings, content_returning(docx_with_table(), DOCX_MIME))
    assert (result.ingested, result.unchanged, result.failed) == (1, 0, 0)

    file, document, _ = await stored(factory, stale)
    assert "| Package | Fee |" in document.extracted_text
    assert document.pipeline_version == EXTRACTION_PIPELINE_VERSION
    assert file.status == DriveFileStatus.INDEXING  # leaves search until re-chunked and rebuilt

    async with factory() as db:
        counts = await DriveSyncService(db, settings).get_pending_counts(USER_A)
    assert counts.to_ingest == 0  # this step is done; chunking and build take over


async def test_identical_text_only_stamps_the_version_and_keeps_the_file_indexed(
    factory, full_schema, settings
):
    async with factory.begin() as db:
        same = await add_file(
            db, name="notes.txt", mime_type=TXT_MIME, body="plain notes", version=1
        )
    result = await ingest(factory, settings, content_returning(b"plain notes", TXT_MIME))
    assert (result.ingested, result.unchanged, result.failed) == (0, 1, 0)

    file, document, chunks = await stored(factory, same)
    assert document.pipeline_version == EXTRACTION_PIPELINE_VERSION
    assert file.status == DriveFileStatus.INDEXED  # still searchable, chunks untouched
    assert [chunk.text for chunk in chunks] == ["plain notes"]


async def test_a_current_file_is_never_downloaded_again(factory, full_schema, settings):
    async with factory.begin() as db:
        await add_file(db, name="current.docx", version=EXTRACTION_PIPELINE_VERSION)
    content = content_returning(docx_with_table(), DOCX_MIME)
    result = await ingest(factory, settings, content)
    assert result.total == 0
    content.fetch_file_content.assert_not_called()


async def test_a_large_google_doc_that_came_back_as_plain_text_is_read_as_text(
    factory, full_schema, settings
):
    async with factory.begin() as db:
        big = await add_file(db, name="big_doc", version=1, body="old")
    result = await ingest(
        factory, settings, content_returning(b"Plain export of a big document", TXT_MIME)
    )
    assert result.ingested == 1
    _, document, _ = await stored(factory, big)
    assert document.extracted_text == "Plain export of a big document"
