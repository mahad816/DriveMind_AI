"""Drive file listing and content routes (synced metadata from PostgreSQL)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.google_drive.client import DriveClientError
from app.db.session import get_db
from app.schemas.drive_sync import DriveFileListResponse
from app.schemas.file import DriveFileRead
from app.services.drive_content_service import DriveContentService
from app.services.drive_sync_service import DriveSyncService

router = APIRouter(prefix="/files")


def get_drive_sync_service(db: AsyncSession = Depends(get_db)) -> DriveSyncService:
    """Dependency provider for Drive sync service."""
    return DriveSyncService(db=db)


def get_drive_content_service(db: AsyncSession = Depends(get_db)) -> DriveContentService:
    """Dependency provider for Drive content service."""
    return DriveContentService(db=db)


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


@router.get("/{file_id}/content", summary="Download or export synced file content")
async def get_file_content(
    file_id: uuid.UUID,
    service: DriveContentService = Depends(get_drive_content_service),
) -> Response:
    """Export or download bytes for a supported synced Drive file."""
    try:
        content = await service.fetch_file_content(file_id=file_id)
    except ValueError as exc:
        detail = str(exc)
        if detail == "Synced file not found":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=detail,
            ) from exc
        if detail.startswith("Unsupported file type"):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=detail,
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail,
        ) from exc
    except DriveClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return Response(
        content=content.data,
        media_type=content.mime_type,
        headers={
            "Content-Disposition": f'inline; filename="{content.filename}"',
            "X-Drive-File-Id": content.drive_file_id,
        },
    )
