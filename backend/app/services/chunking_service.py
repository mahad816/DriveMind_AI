"""Document chunking service — split extracted text and persist chunk rows."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.enums import IndexingJobStatus
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.db.models.google_oauth_token import GoogleOAuthToken
from app.db.models.indexing_job import IndexingJob
from app.db.models.user import User
from app.ingestion.chunking import ChunkingConfig, chunk_text


@dataclass
class ChunkingResult:
    """Internal result from a document chunking run."""

    job_id: uuid.UUID
    user_id: uuid.UUID
    chunked: int
    unchanged: int
    skipped: int
    total: int


class ChunkingService:
    """Persists deterministic text chunks for extracted documents."""

    def __init__(
        self,
        db: AsyncSession,
        settings: Settings | None = None,
        *,
        chunking_config: ChunkingConfig | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.chunking_config = chunking_config or ChunkingConfig()

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

    async def _list_chunkable_documents(self, user_id: uuid.UUID) -> list[Document]:
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

    async def _get_existing_chunks(self, document_id: uuid.UUID) -> list[Chunk]:
        result = await self.db.scalars(
            select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.chunk_index.asc())
        )
        return list(result.all())

    @staticmethod
    def _chunks_are_current(chunks: list[Chunk], extracted_text_hash: str) -> bool:
        if not chunks:
            return False
        return all(
            chunk.metadata_json.get("extracted_text_hash") == extracted_text_hash
            for chunk in chunks
        )

    async def _replace_chunks(self, document: Document) -> str:
        """Chunk one document. Returns 'chunked' or 'unchanged'."""
        existing = await self._get_existing_chunks(document.id)
        text_hash = document.extracted_text_hash

        if existing and self._chunks_are_current(existing, text_hash):
            return "unchanged"

        text_chunks = chunk_text(document.extracted_text, config=self.chunking_config)
        if not existing and not text_chunks:
            return "unchanged"

        await self.db.execute(delete(Chunk).where(Chunk.document_id == document.id))

        for text_chunk in text_chunks:
            metadata = {
                **text_chunk.metadata,
                "extracted_text_hash": text_hash,
            }
            self.db.add(
                Chunk(
                    document_id=document.id,
                    chunk_index=text_chunk.chunk_index,
                    text=text_chunk.text,
                    metadata_json=metadata,
                )
            )

        return "chunked"

    async def sync_document_chunks(self, document: Document) -> str:
        """Ensure chunk rows exist for a document. Returns 'chunked' or 'unchanged'."""
        return await self._replace_chunks(document)

    async def _chunk_drive_file(self, drive_file: DriveFile) -> str:
        document = await self._get_latest_document(drive_file.id)
        if document is None:
            return "skipped"
        return await self._replace_chunks(document)

    async def chunk_documents(
        self,
        user_id: uuid.UUID | None = None,
        *,
        file_id: uuid.UUID | None = None,
    ) -> ChunkingResult:
        """Chunk one synced file's document or all extracted documents for the user."""
        user = await self._resolve_user(user_id)

        job = IndexingJob(user_id=user.id, status=IndexingJobStatus.QUEUED)
        self.db.add(job)
        await self.db.flush()

        job.status = IndexingJobStatus.RUNNING
        job.started_at = datetime.now(UTC)

        chunked = unchanged = skipped = 0
        total = 0

        try:
            if file_id is not None:
                drive_file = await self._get_drive_file(user.id, file_id)
                total = 1
                outcome = await self._chunk_drive_file(drive_file)
                if outcome == "chunked":
                    chunked += 1
                elif outcome == "unchanged":
                    unchanged += 1
                else:
                    skipped += 1
            else:
                documents = await self._list_chunkable_documents(user.id)
                total = len(documents)
                for document in documents:
                    outcome = await self._replace_chunks(document)
                    if outcome == "chunked":
                        chunked += 1
                    else:
                        unchanged += 1

            job.status = IndexingJobStatus.COMPLETED
            job.completed_at = datetime.now(UTC)
            await self.db.commit()
        except Exception as exc:
            job.status = IndexingJobStatus.FAILED
            job.error = str(exc)
            job.completed_at = datetime.now(UTC)
            await self.db.commit()
            raise

        return ChunkingResult(
            job_id=job.id,
            user_id=user.id,
            chunked=chunked,
            unchanged=unchanged,
            skipped=skipped,
            total=total,
        )
