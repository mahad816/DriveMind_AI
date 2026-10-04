"""Bounded authoritative excerpts for per-file summaries; no similarity search."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import DriveFileStatus
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.retrieval.types import RetrievedChunk

MAX_SUMMARY_FILES = 10
MAX_CHUNKS_PER_FILE = 4


@dataclass
class CollectionSummaryResult:
    total: int
    files: list[tuple[str, list[RetrievedChunk]]]


class CollectionSummaryRetriever:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def search(self, user_id: UUID, *, max_chars: int) -> CollectionSummaryResult:
        eligible = (DriveFile.user_id == user_id, DriveFile.status == DriveFileStatus.INDEXED)
        total = int(
            await self.db.scalar(select(func.count()).select_from(DriveFile).where(*eligible)) or 0
        )
        files = list(
            (
                await self.db.scalars(
                    select(DriveFile)
                    .where(*eligible)
                    .order_by(DriveFile.name, DriveFile.id)
                    .limit(MAX_SUMMARY_FILES)
                )
            ).all()
        )
        results: list[tuple[str, list[RetrievedChunk]]] = []
        for file in files:
            rows = (
                await self.db.execute(
                    select(
                        Chunk.id,
                        Chunk.document_id,
                        Chunk.chunk_index,
                        func.substr(Chunk.text, 1, max_chars),
                    )
                    .join(Document, Chunk.document_id == Document.id)
                    .where(Document.drive_file_id == file.id)
                    .order_by(Chunk.chunk_index, Chunk.id)
                    .limit(MAX_CHUNKS_PER_FILE)
                )
            ).all()
            chunks = [
                RetrievedChunk(
                    chunk_id=row[0],
                    document_id=row[1],
                    chunk_index=row[2],
                    text=row[3],
                    drive_file_id=file.id,
                    filename=file.name,
                    mime_type=file.mime_type,
                    modified_at=file.modified_at,
                    score=1.0,
                )
                for row in rows
            ]
            results.append((file.name, chunks))
        return CollectionSummaryResult(total=total, files=results)
