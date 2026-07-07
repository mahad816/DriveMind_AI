"""Tests for vector indexing service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.enums import DriveFileStatus
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.db.models.google_oauth_token import GoogleOAuthToken
from app.db.models.indexing_job import IndexingJob
from app.db.models.user import User
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


def _drive_file() -> DriveFile:
    return DriveFile(
        id=FILE_ID,
        user_id=USER_ID,
        drive_file_id="gdrive-file-1",
        name="notes.txt",
        mime_type="text/plain",
        modified_at=datetime.now(UTC),
        status=DriveFileStatus.INDEXED,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _document(*, text: str = "hello world") -> Document:
    return Document(
        id=DOCUMENT_ID,
        drive_file_id=FILE_ID,
        extracted_text=text,
        extracted_text_hash=compute_extracted_text_hash(text),
        page_count=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _chunk(*, text: str, text_hash: str) -> Chunk:
    return Chunk(
        id=CHUNK_ID,
        document_id=DOCUMENT_ID,
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
    assert result.total == 1
    mock_embedding.embed_texts.assert_awaited_once_with(["hello world"])
    mock_vector_store.upsert_points.assert_awaited_once()
    mock_vector_store.ensure_collection.assert_awaited_once_with(vector_size=1536)
    added = [call.args[0] for call in mock_db.add.call_args_list]
    assert any(isinstance(item, IndexingJob) for item in added)


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
    mock_db.get = AsyncMock(side_effect=[USER, _drive_file(), _drive_file()])
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
    assert mock_embedding.embed_texts.await_count == 2
