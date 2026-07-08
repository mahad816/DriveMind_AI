"""Drive indexing routes — all write operations run in background tasks."""

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal, get_db
from app.schemas.drive_sync import DriveSyncStatusResponse
from app.schemas.indexing import IndexingJobRead
from app.services.chunking_service import ChunkingService
from app.services.drive_sync_service import DriveSyncService
from app.services.indexing_service import IndexingService
from app.services.ingestion_service import IngestionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/index")


# ---------------------------------------------------------------------------
# Dependency factories
# ---------------------------------------------------------------------------


def get_drive_sync_service(db: AsyncSession = Depends(get_db)) -> DriveSyncService:
    return DriveSyncService(db=db)


# ---------------------------------------------------------------------------
# Background task helpers — each opens its own DB session so the HTTP session
# can close as soon as we return 202.
# ---------------------------------------------------------------------------


async def _bg_sync(full: bool) -> None:
    async with SessionLocal() as db:
        try:
            await DriveSyncService(db=db).sync_metadata(full=full)
        except Exception:
            logger.exception("Background Drive sync failed")


async def _bg_ingest(file_id: uuid.UUID | None) -> None:
    async with SessionLocal() as db:
        try:
            await IngestionService(db=db).ingest_files(file_id=file_id)
        except Exception:
            logger.exception("Background ingestion failed")


async def _bg_chunk(file_id: uuid.UUID | None) -> None:
    async with SessionLocal() as db:
        try:
            await ChunkingService(db=db).chunk_documents(file_id=file_id)
        except Exception:
            logger.exception("Background chunking failed")


async def _bg_build(file_id: uuid.UUID | None) -> None:
    async with SessionLocal() as db:
        try:
            await IndexingService(db=db).build_index(file_id=file_id)
        except Exception:
            logger.exception("Background index build failed")


# ---------------------------------------------------------------------------
# Shared response model for kicked-off background jobs
# ---------------------------------------------------------------------------

_STARTED_RESPONSE = {"status": "started", "message": "Job started — poll /index/status for progress"}


class PendingCountsResponse(BaseModel):
    """How many files still need each indexing step."""

    to_ingest: int
    to_chunk: int
    to_build: int
    any_pending: bool


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/sync",
    summary="Start Drive metadata sync (background)",
    status_code=status.HTTP_202_ACCEPTED,
)
async def sync_drive_metadata(
    background_tasks: BackgroundTasks,
    full: bool = Query(
        default=False,
        description="Force a full Drive scan. Default uses incremental sync.",
    ),
    service: DriveSyncService = Depends(get_drive_sync_service),
) -> dict:
    """Kick off Drive metadata sync as a background task; returns 202 immediately.

    Poll ``GET /index/status`` to track progress.
    """
    # Guard: ensure there is a connected Drive account before queueing work.
    try:
        connected = await service.is_connected()
    except Exception as exc:
        logger.exception("Could not check Drive connection")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Could not verify Drive connection: {exc}",
        ) from exc

    if not connected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No Google Drive connection found. Complete OAuth first.",
        )

    background_tasks.add_task(_bg_sync, full)
    return _STARTED_RESPONSE


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


@router.get("/pending", summary="Count files pending each indexing step")
async def get_pending_counts(
    service: DriveSyncService = Depends(get_drive_sync_service),
) -> PendingCountsResponse:
    """Return how many files still need each pipeline step.

    The frontend uses this to skip steps that have no pending work — making
    a routine 'add one file + Set up' flow much faster than always running
    all four steps.
    """
    try:
        counts = await service.get_pending_counts()
    except ValueError:
        return PendingCountsResponse(to_ingest=0, to_chunk=0, to_build=0, any_pending=False)
    return PendingCountsResponse(
        to_ingest=counts.to_ingest,
        to_chunk=counts.to_chunk,
        to_build=counts.to_build,
        any_pending=counts.any_pending,
    )


@router.post(
    "/ingest",
    summary="Start Drive file ingestion (background)",
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_drive_files(
    background_tasks: BackgroundTasks,
    file_id: uuid.UUID | None = Query(default=None),
) -> dict:
    """Kick off file ingestion as a background task; returns 202 immediately."""
    background_tasks.add_task(_bg_ingest, file_id)
    return _STARTED_RESPONSE


@router.post(
    "/chunk",
    summary="Start document chunking (background)",
    status_code=status.HTTP_202_ACCEPTED,
)
async def chunk_extracted_documents(
    background_tasks: BackgroundTasks,
    file_id: uuid.UUID | None = Query(default=None),
) -> dict:
    """Kick off chunking as a background task; returns 202 immediately."""
    background_tasks.add_task(_bg_chunk, file_id)
    return _STARTED_RESPONSE


@router.post(
    "/build",
    summary="Start vector index build (background)",
    status_code=status.HTTP_202_ACCEPTED,
)
async def build_vector_index(
    background_tasks: BackgroundTasks,
    file_id: uuid.UUID | None = Query(default=None),
) -> dict:
    """Kick off vector index build as a background task; returns 202 immediately."""
    background_tasks.add_task(_bg_build, file_id)
    return _STARTED_RESPONSE
