"""Vector indexing service — chunk, embed, and upsert into Qdrant."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings, get_settings
from app.db.enums import IndexingJobStatus
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.db.models.google_oauth_token import GoogleOAuthToken
from app.db.models.indexing_job import IndexingJob
from app.db.models.user import User
from app.embeddings.base import EmbeddingError, EmbeddingService
from app.embeddings.factory import get_embedding_service
from app.embeddings.vector_store import QdrantVectorStore, VectorPoint, VectorStoreError
from app.services.chunking_service import ChunkingService

logger = logging.getLogger(__name__)


@dataclass
class IndexBuildResult:
    """Internal result from a vector index build run."""

    job_id: uuid.UUID
    user_id: uuid.UUID
    embedded: int
    unchanged: int
    skipped: int
    failed: int
    removed: int
    total: int


class IndexingService:
    """Build searchable vector indexes from chunked document text."""

    def __init__(
        self,
        db: AsyncSession,
        settings: Settings | None = None,
        *,
        chunking_service: ChunkingService | None = None,
        embedding_service: EmbeddingService | None = None,
        vector_store: QdrantVectorStore | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.chunking_service = chunking_service or ChunkingService(db, self.settings)
        self.embedding_service = embedding_service or get_embedding_service(self.settings)
        self.vector_store = vector_store or QdrantVectorStore(self.settings)

    async def _resolve_user(self, user_id: uuid.UUID | None) -> User:
        if user_id is not None:
            user = await self.db.get(User, user_id)
            if user is None:
                raise ValueError("User not found")
            return user

        token_row = await self.db.scalar(select(GoogleOAuthToken).limit(1))
        if token_row is None:
            raise ValueError("No Google Drive connection found. Complete OAuth first.")
        user = await self.db.get(User, token_row.user_id)
        if user is None:
            raise ValueError("Connected Google account has no user record")
        return user

    async def _get_drive_file(self, user_id: uuid.UUID, file_id: uuid.UUID) -> DriveFile:
        drive_file = await self.db.scalar(
            select(DriveFile).where(DriveFile.id == file_id, DriveFile.user_id == user_id)
        )
        if drive_file is None:
            raise ValueError("Synced file not found")
        return drive_file

    async def _list_indexable_documents(self, user_id: uuid.UUID) -> list[Document]:
        result = await self.db.scalars(
            select(Document)
            .join(DriveFile, Document.drive_file_id == DriveFile.id)
            .where(DriveFile.user_id == user_id)
            .order_by(Document.updated_at.desc())
        )
        return list(result.all())

    async def _get_latest_document(self, drive_file_id: uuid.UUID) -> Document | None:
        document = await self.db.scalar(
            select(Document)
            .where(Document.drive_file_id == drive_file_id)
            .order_by(Document.updated_at.desc())
            .limit(1)
        )
        return document

    async def _load_chunks_for_document(self, document_id: uuid.UUID) -> list[Chunk]:
        result = await self.db.scalars(
            select(Chunk)
            .where(Chunk.document_id == document_id)
            .options(selectinload(Chunk.document).selectinload(Document.drive_file))
            .order_by(Chunk.chunk_index.asc())
        )
        return list(result.all())

    def _chunk_payload(self, chunk: Chunk, drive_file: DriveFile) -> dict[str, object]:
        text_hash = chunk.metadata_json.get("extracted_text_hash", "")
        return {
            "chunk_id": str(chunk.id),
            "drive_file_id": str(drive_file.id),
            "filename": drive_file.name,
            "mime_type": drive_file.mime_type,
            "modified_at": drive_file.modified_at,
            "chunk_index": chunk.chunk_index,
            "extracted_text_hash": text_hash,
        }

    async def _index_document(self, document: Document) -> tuple[int, int, int, int]:
        """Chunk, embed, and upsert one document. Returns embedded/unchanged/skipped/removed."""
        await self.chunking_service.sync_document_chunks(document)
        await self.db.flush()

        chunks = await self._load_chunks_for_document(document.id)
        drive_file = await self.db.get(DriveFile, document.drive_file_id)
        if drive_file is None:
            return 0, 0, 1, 0

        keep_chunk_ids = {chunk.id for chunk in chunks}
        removed = await self.vector_store.delete_points_for_drive_file_except(
            drive_file_id=drive_file.id,
            keep_chunk_ids=keep_chunk_ids,
        )

        if not chunks:
            return 0, 0, 0, removed

        stored_hashes = await self.vector_store.get_stored_hashes([chunk.id for chunk in chunks])
        pending: list[Chunk] = []
        unchanged = 0

        for chunk in chunks:
            text_hash = chunk.metadata_json.get("extracted_text_hash")
            if isinstance(text_hash, str) and stored_hashes.get(chunk.id) == text_hash:
                unchanged += 1
            else:
                pending.append(chunk)

        embedded = 0
        if pending:
            vectors = await self.embedding_service.embed_texts([chunk.text for chunk in pending])
            points = [
                VectorPoint(
                    chunk_id=chunk.id,
                    vector=vector,
                    payload=self._chunk_payload(chunk, drive_file),
                )
                for chunk, vector in zip(pending, vectors, strict=True)
            ]
            await self.vector_store.upsert_points(
                points,
                expected_vector_size=self.embedding_service.embedding_dimension,
            )
            embedded = len(points)

        return embedded, unchanged, 0, removed

    async def _index_document_safe(
        self,
        document: Document,
        *,
        drive_file: DriveFile | None = None,
    ) -> tuple[int, int, int, int, int]:
        """Index one document, returning embedded/unchanged/skipped/removed/failed."""
        resolved_drive_file = drive_file
        if resolved_drive_file is None:
            resolved_drive_file = await self.db.get(DriveFile, document.drive_file_id)

        file_label = (
            resolved_drive_file.name
            if resolved_drive_file is not None
            else str(document.drive_file_id)
        )
        try:
            embedded, unchanged, skipped, removed = await self._index_document(document)
            return embedded, unchanged, skipped, removed, 0
        except (EmbeddingError, VectorStoreError) as exc:
            logger.warning(
                "Skipping vector index for document %s (%s): %s",
                document.id,
                file_label,
                exc,
            )
            return 0, 0, 0, 0, 1

    async def build_index(
        self,
        user_id: uuid.UUID | None = None,
        *,
        file_id: uuid.UUID | None = None,
    ) -> IndexBuildResult:
        """Chunk documents, embed pending chunks, and upsert vectors into Qdrant."""
        user = await self._resolve_user(user_id)
        await self.vector_store.ensure_collection(
            vector_size=self.embedding_service.embedding_dimension,
        )

        job = IndexingJob(user_id=user.id, status=IndexingJobStatus.QUEUED)
        self.db.add(job)
        await self.db.flush()

        job.status = IndexingJobStatus.RUNNING
        job.started_at = datetime.now(UTC)

        embedded = unchanged = skipped = failed = removed = 0
        total = 0

        try:
            if file_id is not None:
                drive_file = await self._get_drive_file(user.id, file_id)
                total = 1
                document = await self._get_latest_document(drive_file.id)
                if document is None:
                    skipped = 1
                else:
                    (
                        doc_embedded,
                        doc_unchanged,
                        doc_skipped,
                        doc_removed,
                        doc_failed,
                    ) = await self._index_document_safe(document, drive_file=drive_file)
                    embedded += doc_embedded
                    unchanged += doc_unchanged
                    skipped += doc_skipped
                    removed += doc_removed
                    failed += doc_failed
            else:
                documents = await self._list_indexable_documents(user.id)
                total = len(documents)
                for document in documents:
                    (
                        doc_embedded,
                        doc_unchanged,
                        doc_skipped,
                        doc_removed,
                        doc_failed,
                    ) = await self._index_document_safe(document)
                    embedded += doc_embedded
                    unchanged += doc_unchanged
                    skipped += doc_skipped
                    removed += doc_removed
                    failed += doc_failed

            job.status = IndexingJobStatus.COMPLETED
            job.completed_at = datetime.now(UTC)
            await self.db.commit()
        except Exception as exc:
            job.status = IndexingJobStatus.FAILED
            job.error = str(exc)
            job.completed_at = datetime.now(UTC)
            await self.db.commit()
            raise

        return IndexBuildResult(
            job_id=job.id,
            user_id=user.id,
            embedded=embedded,
            unchanged=unchanged,
            skipped=skipped,
            failed=failed,
            removed=removed,
            total=total,
        )
