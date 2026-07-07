"""Citation source viewer routes."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.source import SourceChunkRead
from app.services.source_service import SourceService

router = APIRouter(prefix="/sources")


def get_source_service(db: AsyncSession = Depends(get_db)) -> SourceService:
    """Dependency provider for citation source lookup."""
    return SourceService(db=db)


@router.get("/{chunk_id}", summary="View source chunk for a citation")
async def get_source_chunk(
    chunk_id: uuid.UUID,
    service: SourceService = Depends(get_source_service),
) -> SourceChunkRead:
    """Return full chunk text and file metadata for a cited source."""
    source = await service.get_source_chunk(chunk_id)
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source chunk not found",
        )
    return source
