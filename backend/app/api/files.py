"""Drive file listing routes (synced metadata from PostgreSQL)."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.drive_sync import DriveFileListResponse
from app.schemas.file import DriveFileRead
from app.services.drive_sync_service import DriveSyncService

router = APIRouter(prefix="/files")


def get_drive_sync_service(db: AsyncSession = Depends(get_db)) -> DriveSyncService:
    """Dependency provider for Drive sync service."""
    return DriveSyncService(db=db)


@router.get("", summary="List synced Drive files")
async def list_synced_files(
    service: DriveSyncService = Depends(get_drive_sync_service),
) -> DriveFileListResponse:
    """Return Drive file metadata stored in PostgreSQL after sync."""
    try:
        files = await service.list_synced_files()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    file_reads = [DriveFileRead.model_validate(f) for f in files]
    return DriveFileListResponse(files=file_reads, total=len(file_reads))
