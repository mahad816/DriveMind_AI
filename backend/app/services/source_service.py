"""Source chunk lookup for citation viewer."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.schemas.source import SourceChunkRead


class SourceService:
    """Load authoritative chunk text and file metadata from PostgreSQL."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_source_chunk(self, chunk_id: uuid.UUID) -> SourceChunkRead | None:
        """Return chunk source details when the chunk exists."""
        chunk = await self.db.scalar(
            select(Chunk)
            .where(Chunk.id == chunk_id)
            .options(
                selectinload(Chunk.document).selectinload(Document.drive_file),
            )
        )
        if chunk is None:
            return None

        document = chunk.document
        drive_file = document.drive_file if document is not None else None
        if document is None or drive_file is None:
            return None

        return SourceChunkRead(
            chunk_id=chunk.id,
            drive_file_id=drive_file.id,
            filename=drive_file.name,
            mime_type=drive_file.mime_type,
            chunk_index=chunk.chunk_index,
            text=chunk.text,
            modified_at=drive_file.modified_at,
        )
