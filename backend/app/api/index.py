"""Drive indexing sync routes."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.google_drive.client import DriveClientError
from app.db.session import get_db
from app.schemas.drive_sync import DriveSyncResponse, DriveSyncStatusResponse
from app.schemas.indexing import IndexingJobRead
from app.services.drive_sync_service import DriveSyncService

router = APIRouter(prefix="/index")


def get_drive_sync_service(db: AsyncSession = Depends(get_db)) -> DriveSyncService:
    """Dependency provider for Drive sync service."""
    return DriveSyncService(db=db)


@router.post("/sync", summary="Sync Drive file metadata")
async def sync_drive_metadata(
    service: DriveSyncService = Depends(get_drive_sync_service),
) -> DriveSyncResponse:
    """List supported Drive files and upsert metadata into PostgreSQL."""
    try:
        result = await service.sync_metadata()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except DriveClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return DriveSyncResponse(
        job_id=result.job_id,
        user_id=result.user_id,
        created=result.created,
        updated=result.updated,
        unchanged=result.unchanged,
        total_seen=result.total_seen,
        message="Drive metadata sync completed",
    )


@router.get("/status", summary="Latest Drive sync status")
async def get_sync_status(
    service: DriveSyncService = Depends(get_drive_sync_service),
) -> DriveSyncStatusResponse:
    """Return the latest indexing job status for the connected user."""
    connected = await service.is_connected()
    if not connected:
        return DriveSyncStatusResponse(connected=False, job=None)

    job = await service.get_latest_sync_job()
    job_read = IndexingJobRead.model_validate(job) if job is not None else None
    return DriveSyncStatusResponse(connected=True, job=job_read)
