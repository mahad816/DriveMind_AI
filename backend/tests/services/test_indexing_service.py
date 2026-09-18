"""Tests for vector indexing service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.db.enums import DriveFileStatus, IndexingJobStatus
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.db.models.google_oauth_token import GoogleOAuthToken
from app.db.models.indexing_job import IndexingJob
from app.db.models.user import User
from app.embeddings.base import EmbeddingError
from app.embeddings.vector_store import VectorStoreError
from app.ingestion.hash_util import compute_extracted_text_hash
from app.services.indexing_service import IndexingService

USER_ID = uuid.uuid4()
FILE_ID = uuid.uuid4()
DOCUMENT_ID = uuid.uuid4()
CHUNK_ID = uuid.uuid4()
USER = User(id=USER_ID, email="user@example.com", google_id="gid-1")
TOKEN_ROW = GoogleOAuthToken(
    id=uuid.uuid4(),
    user_id=USER_ID,
    access_token="access",
    refresh_token="refresh",
    token_expiry=datetime.now(UTC),
    scopes="https://www.googleapis.com/auth/drive.readonly",
)


def _drive_file(
    *,
    file_id: uuid.UUID = FILE_ID,
    name: str = "notes.txt",
    status: DriveFileStatus = DriveFileStatus.INDEXING,
) -> DriveFile:
    return DriveFile(
        id=file_id,
        user_id=USER_ID,
        drive_file_id=f"gdrive-{file_id}",
        name=name,
        mime_type="text/plain",
        modified_at=datetime.now(UTC),
        status=status,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _document(
    *,
    text: str = "hello world",
    document_id: uuid.UUID = DOCUMENT_ID,
    file_id: uuid.UUID = FILE_ID,
) -> Document:
    return Document(
        id=document_id,
        drive_file_id=file_id,
        extracted_text=text,
        extracted_text_hash=compute_extracted_text_hash(text),
        page_count=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _chunk(
    *,
    text: str,
    text_hash: str,
    chunk_id: uuid.UUID = CHUNK_ID,
    document_id: uuid.UUID = DOCUMENT_ID,
) -> Chunk:
    return Chunk(
        id=chunk_id,
        document_id=document_id,
        chunk_index=0,
        text=text,
        metadata_json={
            "char_start": 0,
            "char_end": len(text),
            "char_length": len(text),
            "extracted_text_hash": text_hash,
        },
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.fixture
def mock_db() -> AsyncMock:
    db = AsyncMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.fixture
def mock_chunking() -> AsyncMock:
    chunking = AsyncMock()
    chunking.sync_document_chunks = AsyncMock(return_value="chunked")
    return chunking


@pytest.fixture
def mock_embedding() -> AsyncMock:
    embedding = AsyncMock()
    embedding.embedding_dimension = 1536
    embedding.embed_texts = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
    return embedding


@pytest.fixture
def mock_vector_store() -> AsyncMock:
    vector_store = AsyncMock()
    vector_store.ensure_collection = AsyncMock()
    vector_store.get_stored_hashes = AsyncMock(return_value={})
    vector_store.delete_points_for_drive_file_except = AsyncMock(return_value=0)
    vector_store.upsert_points = AsyncMock()
    return vector_store


@pytest.fixture
def service(
    mock_db: AsyncMock,
    mock_chunking: AsyncMock,
    mock_embedding: AsyncMock,
    mock_vector_store: AsyncMock,
) -> IndexingService:
    return IndexingService(
        db=mock_db,
        settings=MagicMock(),
        chunking_service=mock_chunking,
        embedding_service=mock_embedding,
        vector_store=mock_vector_store,
    )


def _added_jobs(mock_db: AsyncMock) -> list[IndexingJob]:
    return [
        call.args[0] for call in mock_db.add.call_args_list if isinstance(call.args[0], IndexingJob)
    ]


@pytest.mark.asyncio
async def test_build_index_embeds_new_chunks(
    service: IndexingService,
    mock_db: AsyncMock,
    mock_embedding: AsyncMock,
    mock_vector_store: AsyncMock,
) -> None:
    drive_file = _drive_file()
    document = _document()
    chunk = _chunk(text="hello world", text_hash=document.extracted_text_hash)
    mock_db.get = AsyncMock(side_effect=[USER, drive_file, drive_file])
    mock_db.scalar = AsyncMock(side_effect=[TOKEN_ROW, drive_file, document])
    mock_db.scalars = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=[chunk])),
    )

    result = await service.build_index(file_id=FILE_ID)

    assert result.embedded == 1
    assert result.unchanged == 0
    assert result.skipped == 0
    assert result.failed == 0
    assert result.total == 1
    assert drive_file.status == DriveFileStatus.INDEXED
    mock_embedding.embed_texts.assert_awaited_once_with(["hello world"])
    mock_vector_store.upsert_points.assert_awaited_once()
    mock_vector_store.ensure_collection.assert_awaited_once_with(vector_size=1536)
    added = [call.args[0] for call in mock_db.add.call_args_list]
    assert any(isinstance(item, IndexingJob) for item in added)
    assert _added_jobs(mock_db)[0].status == IndexingJobStatus.COMPLETED


@pytest.mark.asyncio
async def test_build_index_skips_unchanged_vectors(
    service: IndexingService,
    mock_db: AsyncMock,
    mock_embedding: AsyncMock,
    mock_vector_store: AsyncMock,
) -> None:
    drive_file = _drive_file()
    document = _document()
    chunk = _chunk(text="hello world", text_hash=document.extracted_text_hash)
    mock_db.get = AsyncMock(side_effect=[USER, drive_file, drive_file])
    mock_db.scalar = AsyncMock(side_effect=[TOKEN_ROW, drive_file, document])
    mock_db.scalars = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=[chunk])),
    )
    mock_vector_store.get_stored_hashes = AsyncMock(
        return_value={CHUNK_ID: document.extracted_text_hash},
    )

    result = await service.build_index(file_id=FILE_ID)

    assert result.embedded == 0
    assert result.unchanged == 1
    mock_embedding.embed_texts.assert_not_awaited()
    mock_vector_store.upsert_points.assert_not_awaited()


@pytest.mark.asyncio
async def test_build_index_skips_file_without_document(
    service: IndexingService,
    mock_db: AsyncMock,
    mock_embedding: AsyncMock,
) -> None:
    drive_file = _drive_file()
    mock_db.get = AsyncMock(return_value=USER)
    mock_db.scalar = AsyncMock(side_effect=[TOKEN_ROW, drive_file, None])

    result = await service.build_index(file_id=FILE_ID)

    assert result.skipped == 1
    assert result.embedded == 0
    mock_embedding.embed_texts.assert_not_awaited()


@pytest.mark.asyncio
async def test_build_index_explicit_skipped_file_does_not_index_stale_chunks(
    service: IndexingService,
    mock_db: AsyncMock,
    mock_chunking: AsyncMock,
    mock_embedding: AsyncMock,
    mock_vector_store: AsyncMock,
) -> None:
    drive_file = _drive_file(status=DriveFileStatus.SKIPPED)
    stale_document = _document(text="old searchable content")
    stale_chunk = _chunk(
        text="old searchable content",
        text_hash=stale_document.extracted_text_hash,
    )
    mock_db.get = AsyncMock(return_value=USER)
    mock_db.scalar = AsyncMock(side_effect=[TOKEN_ROW, drive_file, stale_document])
    mock_db.scalars = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=[stale_chunk])),
    )

    result = await service.build_index(file_id=FILE_ID)

    assert result.embedded == 0
    assert result.unchanged == 0
    assert result.skipped == 1
    assert result.failed == 0
    assert drive_file.status == DriveFileStatus.SKIPPED
    assert _added_jobs(mock_db)[0].status == IndexingJobStatus.COMPLETED
    assert mock_db.scalar.await_count == 2
    mock_db.scalars.assert_not_awaited()
    mock_chunking.sync_document_chunks.assert_not_awaited()
    mock_embedding.embed_texts.assert_not_awaited()
    mock_vector_store.delete_points_for_drive_file_except.assert_not_awaited()
    mock_vector_store.get_stored_hashes.assert_not_awaited()
    mock_vector_store.upsert_points.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [DriveFileStatus.FAILED, DriveFileStatus.INDEXED])
async def test_build_index_explicit_non_indexing_file_does_not_index_stale_chunks(
    service: IndexingService,
    mock_db: AsyncMock,
    mock_chunking: AsyncMock,
    mock_embedding: AsyncMock,
    mock_vector_store: AsyncMock,
    status: DriveFileStatus,
) -> None:
    drive_file = _drive_file(status=status)
    stale_document = _document(text="old searchable content")
    stale_chunk = _chunk(
        text="old searchable content",
        text_hash=stale_document.extracted_text_hash,
    )
    mock_db.get = AsyncMock(return_value=USER)
    mock_db.scalar = AsyncMock(side_effect=[TOKEN_ROW, drive_file, stale_document])
    mock_db.scalars = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=[stale_chunk])),
    )

    result = await service.build_index(file_id=FILE_ID)

    assert result.embedded == 0
    assert result.unchanged == 0
    assert result.skipped == 1
    assert result.failed == 0
    assert drive_file.status == status
    assert mock_db.scalar.await_count == 2
    mock_db.scalars.assert_not_awaited()
    mock_chunking.sync_document_chunks.assert_not_awaited()
    mock_embedding.embed_texts.assert_not_awaited()
    mock_vector_store.delete_points_for_drive_file_except.assert_not_awaited()
    mock_vector_store.get_stored_hashes.assert_not_awaited()
    mock_vector_store.upsert_points.assert_not_awaited()


@pytest.mark.asyncio
async def test_batch_build_selector_requires_indexing_status(
    service: IndexingService,
    mock_db: AsyncMock,
) -> None:
    mock_db.scalars = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))

    await service._list_indexable_documents(USER_ID)

    statement = mock_db.scalars.await_args.args[0]
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "drive_files.status = 'INDEXING'" in sql


@pytest.mark.asyncio
async def test_build_index_reembeds_when_hash_changes(
    service: IndexingService,
    mock_db: AsyncMock,
    mock_embedding: AsyncMock,
    mock_vector_store: AsyncMock,
) -> None:
    drive_file = _drive_file()
    document = _document(text="updated content")
    chunk = _chunk(text="updated content", text_hash=document.extracted_text_hash)
    mock_db.get = AsyncMock(side_effect=[USER, drive_file, drive_file])
    mock_db.scalar = AsyncMock(side_effect=[TOKEN_ROW, drive_file, document])
    mock_db.scalars = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=[chunk])),
    )
    mock_vector_store.get_stored_hashes = AsyncMock(return_value={CHUNK_ID: "stale-hash"})

    result = await service.build_index(file_id=FILE_ID)

    assert result.embedded == 1
    assert result.unchanged == 0
    mock_embedding.embed_texts.assert_awaited_once_with(["updated content"])
    mock_vector_store.upsert_points.assert_awaited_once()


@pytest.mark.asyncio
async def test_build_index_batch_processes_documents(
    service: IndexingService,
    mock_db: AsyncMock,
    mock_embedding: AsyncMock,
) -> None:
    documents = [_document(text="doc one"), _document(text="doc two")]
    chunks = [
        _chunk(text="doc one", text_hash=documents[0].extracted_text_hash),
        _chunk(text="doc two", text_hash=documents[1].extracted_text_hash),
    ]
    drive_file = _drive_file()
    mock_db.get = AsyncMock(side_effect=[USER, drive_file, drive_file, drive_file, drive_file])
    mock_db.scalar = AsyncMock(return_value=TOKEN_ROW)
    mock_db.scalars = AsyncMock(
        side_effect=[
            MagicMock(all=MagicMock(return_value=documents)),
            MagicMock(all=MagicMock(return_value=[chunks[0]])),
            MagicMock(all=MagicMock(return_value=[chunks[1]])),
        ],
    )

    result = await service.build_index()

    assert result.total == 2
    assert result.embedded == 2
    assert result.failed == 0
    assert mock_embedding.embed_texts.await_count == 2


@pytest.mark.asyncio
async def test_build_index_continues_after_document_failure(
    service: IndexingService,
    mock_db: AsyncMock,
    mock_embedding: AsyncMock,
    mock_vector_store: AsyncMock,
) -> None:
    documents = [_document(text="doc one"), _document(text="doc two")]
    chunks = [
        _chunk(text="doc one", text_hash=documents[0].extracted_text_hash),
        _chunk(text="doc two", text_hash=documents[1].extracted_text_hash),
    ]
    drive_file = _drive_file()
    mock_db.get = AsyncMock(side_effect=[USER, drive_file, drive_file, drive_file, drive_file])
    mock_db.scalar = AsyncMock(return_value=TOKEN_ROW)
    mock_db.scalars = AsyncMock(
        side_effect=[
            MagicMock(all=MagicMock(return_value=documents)),
            MagicMock(all=MagicMock(return_value=[chunks[0]])),
            MagicMock(all=MagicMock(return_value=[chunks[1]])),
        ],
    )
    mock_vector_store.upsert_points = AsyncMock(
        side_effect=[VectorStoreError("Qdrant rejected vector upsert"), None],
    )

    result = await service.build_index()

    assert result.total == 2
    assert result.embedded == 1
    assert result.failed == 1
    assert mock_embedding.embed_texts.await_count == 2


@pytest.mark.asyncio
async def test_build_index_zero_chunks_marks_indexing_file_skipped(
    service: IndexingService,
    mock_db: AsyncMock,
    mock_embedding: AsyncMock,
) -> None:
    drive_file = _drive_file(status=DriveFileStatus.INDEXING)
    document = _document(text="")
    mock_db.get = AsyncMock(side_effect=[USER, drive_file, drive_file])
    mock_db.scalar = AsyncMock(side_effect=[TOKEN_ROW, drive_file, document])
    mock_db.scalars = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=[])),
    )

    result = await service.build_index(file_id=FILE_ID)

    assert result.skipped == 1
    assert result.failed == 0
    assert drive_file.status == DriveFileStatus.SKIPPED
    assert _added_jobs(mock_db)[0].status == IndexingJobStatus.COMPLETED
    mock_embedding.embed_texts.assert_not_awaited()


def _configure_two_document_build(
    mock_db: AsyncMock,
) -> tuple[list[DriveFile], list[Document], list[Chunk]]:
    file_ids = [uuid.uuid4(), uuid.uuid4()]
    document_ids = [uuid.uuid4(), uuid.uuid4()]
    chunk_ids = [uuid.uuid4(), uuid.uuid4()]
    drive_files = [
        _drive_file(
            file_id=file_ids[index],
            name=f"notes-{index}.txt",
            status=DriveFileStatus.INDEXING,
        )
        for index in range(2)
    ]
    documents = [
        _document(
            text=f"doc {index}",
            document_id=document_ids[index],
            file_id=file_ids[index],
        )
        for index in range(2)
    ]
    chunks = [
        _chunk(
            text=document.extracted_text,
            text_hash=document.extracted_text_hash,
            chunk_id=chunk_ids[index],
            document_id=document.id,
        )
        for index, document in enumerate(documents)
    ]
    mock_db.get = AsyncMock(
        side_effect=[
            USER,
            drive_files[0],
            drive_files[0],
            drive_files[1],
            drive_files[1],
        ]
    )
    mock_db.scalar = AsyncMock(return_value=TOKEN_ROW)
    mock_db.scalars = AsyncMock(
        side_effect=[
            MagicMock(all=MagicMock(return_value=documents)),
            MagicMock(all=MagicMock(return_value=[chunks[0]])),
            MagicMock(all=MagicMock(return_value=[chunks[1]])),
        ]
    )
    return drive_files, documents, chunks


@pytest.mark.asyncio
async def test_build_index_partial_embedding_error_fails_file_and_job(
    service: IndexingService,
    mock_db: AsyncMock,
    mock_embedding: AsyncMock,
) -> None:
    drive_files, _, _ = _configure_two_document_build(mock_db)
    mock_embedding.embed_texts = AsyncMock(
        side_effect=[EmbeddingError("embedding unavailable"), [[0.1, 0.2, 0.3]]]
    )

    result = await service.build_index()

    assert result.embedded == 1
    assert result.failed == 1
    assert drive_files[0].status == DriveFileStatus.FAILED
    assert drive_files[1].status == DriveFileStatus.INDEXED
    job = _added_jobs(mock_db)[0]
    assert job.status == IndexingJobStatus.FAILED
    assert job.error == "1 of 2 files failed during index build."


@pytest.mark.asyncio
async def test_build_index_partial_vector_store_error_fails_file_and_job(
    service: IndexingService,
    mock_db: AsyncMock,
    mock_vector_store: AsyncMock,
) -> None:
    drive_files, _, _ = _configure_two_document_build(mock_db)
    mock_vector_store.upsert_points = AsyncMock(
        side_effect=[VectorStoreError("Qdrant rejected vector upsert"), None]
    )

    result = await service.build_index()

    assert result.embedded == 1
    assert result.failed == 1
    assert drive_files[0].status == DriveFileStatus.FAILED
    assert drive_files[1].status == DriveFileStatus.INDEXED
    job = _added_jobs(mock_db)[0]
    assert job.status == IndexingJobStatus.FAILED
    assert job.error == "1 of 2 files failed during index build."


@pytest.mark.asyncio
async def test_build_index_all_document_failures_fail_job(
    service: IndexingService,
    mock_db: AsyncMock,
    mock_embedding: AsyncMock,
) -> None:
    drive_files, _, _ = _configure_two_document_build(mock_db)
    mock_embedding.embed_texts = AsyncMock(
        side_effect=[EmbeddingError("first failure"), EmbeddingError("second failure")]
    )

    result = await service.build_index()

    assert result.embedded == 0
    assert result.failed == 2
    assert all(drive_file.status == DriveFileStatus.FAILED for drive_file in drive_files)
    job = _added_jobs(mock_db)[0]
    assert job.status == IndexingJobStatus.FAILED
    assert job.error == "2 of 2 files failed during index build."


@pytest.mark.asyncio
async def test_build_index_ensure_collection_failure_persists_failed_job(
    service: IndexingService,
    mock_db: AsyncMock,
    mock_vector_store: AsyncMock,
) -> None:
    mock_db.get = AsyncMock(return_value=USER)
    mock_db.scalar = AsyncMock(return_value=TOKEN_ROW)
    mock_vector_store.ensure_collection = AsyncMock(
        side_effect=VectorStoreError("collection unavailable")
    )

    with pytest.raises(VectorStoreError, match="collection unavailable"):
        await service.build_index()

    job = _added_jobs(mock_db)[0]
    assert job.status == IndexingJobStatus.FAILED
    assert job.error == "collection unavailable"
    assert job.completed_at is not None
    assert mock_db.commit.await_count == 2


@pytest.mark.asyncio
async def test_build_index_unexpected_guarded_exception_fails_job(
    service: IndexingService,
    mock_db: AsyncMock,
) -> None:
    mock_db.get = AsyncMock(return_value=USER)
    mock_db.scalar = AsyncMock(side_effect=[TOKEN_ROW, RuntimeError("database unavailable")])

    with pytest.raises(RuntimeError, match="database unavailable"):
        await service.build_index(file_id=FILE_ID)

    job = _added_jobs(mock_db)[0]
    assert job.status == IndexingJobStatus.FAILED
    assert job.error == "database unavailable"
    assert job.completed_at is not None
