"""Session-bound durable indexing admission. No execution until 4E2/4E3."""

import logging
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.dependencies import require_index_user
from app.api.session_dependencies import require_application_principal
from app.core.config import Settings, get_settings
from app.core.credential_diagnostics import log_safe_failure
from app.db.enums import IndexingOperation
from app.db.models.drive_file import DriveFile
from app.db.session import get_db
from app.demo.manifest import load_manifest
from app.demo.service import DemoCorpusService
from app.schemas.drive_sync import DriveSyncStatusResponse
from app.schemas.indexing import IndexingJobAccepted, IndexingJobRead
from app.services.application_session_service import ApplicationSessionService
from app.services.drive_sync_service import DriveSyncService
from app.services.indexing_job_service import (
    IndexingJobService,
    IndexingAdmissionConflict,
    IndexingTargetNotFound,
    IndexingStoreUnavailable,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/index")


def get_drive_sync_service(
    db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)
) -> DriveSyncService:
    return DriveSyncService(db, settings)


def get_indexing_job_service(db: AsyncSession = Depends(get_db)) -> IndexingJobService:
    return IndexingJobService(db)


async def require_index_read_user(
    request: Request, settings: Settings = Depends(get_settings), db: AsyncSession = Depends(get_db)
) -> uuid.UUID | None:
    # Status readiness must remain anonymous even when demo admission is unavailable.
    if settings.demo_mode:
        return None
    principal = await require_application_principal(
        request, ApplicationSessionService(db, settings)
    )
    return principal.corpus_user_id


class PendingCountsResponse(BaseModel):
    to_ingest: int
    to_chunk: int
    to_build: int
    any_pending: bool


def _job_error(exc: Exception) -> HTTPException:
    if isinstance(exc, IndexingAdmissionConflict):
        return HTTPException(409, "An unresolved indexing job already exists for this account.")
    if isinstance(exc, IndexingTargetNotFound):
        return HTTPException(404, "Indexing resource not found")
    log_safe_failure(logger, "Indexing storage operation", exc)
    return HTTPException(503, "Indexing is temporarily unavailable.")


async def _accept(
    request: Request,
    owner: uuid.UUID,
    operation: IndexingOperation,
    jobs: IndexingJobService,
    settings: Settings,
    *,
    file_id: uuid.UUID | None = None,
    full: bool = False,
) -> IndexingJobAccepted:
    if getattr(request.app.state, "indexing_admission_ready", False) is not True:
        raise HTTPException(
            503,
            "Indexing execution is unavailable until its worker and recovery support are ready.",
        )
    try:
        if file_id is not None:
            target = await jobs.db.scalar(
                select(DriveFile.id).where(DriveFile.id == file_id, DriveFile.user_id == owner)
            )
            if target is None:
                raise IndexingTargetNotFound()
        if operation in (IndexingOperation.SYNC, IndexingOperation.INGEST):
            if not await DriveSyncService(jobs.db, settings).is_connected(user_id=owner):
                raise HTTPException(503, "No Google Drive connection found. Complete OAuth first.")
        job = await jobs.admit(owner, operation, file_id=file_id, full_sync=full)
        return IndexingJobAccepted(job_id=job.id)
    except (
        IndexingAdmissionConflict,
        IndexingTargetNotFound,
        IndexingStoreUnavailable,
        SQLAlchemyError,
    ) as exc:
        raise _job_error(exc) from None


@router.post("/sync", status_code=202)
async def sync_drive_metadata(
    request: Request,
    full: bool = Query(False),
    owner: uuid.UUID = Depends(require_index_user),
    jobs: IndexingJobService = Depends(get_indexing_job_service),
    settings: Settings = Depends(get_settings),
) -> IndexingJobAccepted:
    return await _accept(request, owner, IndexingOperation.SYNC, jobs, settings, full=full)


@router.post("/ingest", status_code=202)
async def ingest_drive_files(
    request: Request,
    file_id: uuid.UUID | None = Query(None),
    owner: uuid.UUID = Depends(require_index_user),
    jobs: IndexingJobService = Depends(get_indexing_job_service),
    settings: Settings = Depends(get_settings),
) -> IndexingJobAccepted:
    return await _accept(request, owner, IndexingOperation.INGEST, jobs, settings, file_id=file_id)


@router.post("/chunk", status_code=202)
async def chunk_extracted_documents(
    request: Request,
    file_id: uuid.UUID | None = Query(None),
    owner: uuid.UUID = Depends(require_index_user),
    jobs: IndexingJobService = Depends(get_indexing_job_service),
    settings: Settings = Depends(get_settings),
) -> IndexingJobAccepted:
    return await _accept(request, owner, IndexingOperation.CHUNK, jobs, settings, file_id=file_id)


@router.post("/build", status_code=202)
async def build_vector_index(
    request: Request,
    file_id: uuid.UUID | None = Query(None),
    owner: uuid.UUID = Depends(require_index_user),
    jobs: IndexingJobService = Depends(get_indexing_job_service),
    settings: Settings = Depends(get_settings),
) -> IndexingJobAccepted:
    return await _accept(request, owner, IndexingOperation.BUILD, jobs, settings, file_id=file_id)


@router.get("/status", response_model_exclude_unset=True)
async def get_sync_status(
    request: Request,
    job_id: uuid.UUID | None = Query(None),
    owner: uuid.UUID | None = Depends(require_index_read_user),
    service: DriveSyncService = Depends(get_drive_sync_service),
    jobs: IndexingJobService = Depends(get_indexing_job_service),
    settings: Settings = Depends(get_settings),
) -> DriveSyncStatusResponse:
    if settings.demo_mode:
        try:
            manifest = load_manifest()
            ready = await DemoCorpusService(
                service.db, settings, readiness_client=request.app.state.demo_readiness_client
            ).is_ready()
        except Exception:
            logger.warning("Controlled demo index unavailable")
            return DriveSyncStatusResponse(
                connected=False, job=None, demo_mode=True, demo_ready=False
            )
        return DriveSyncStatusResponse(
            connected=False,
            job=None,
            demo_mode=True,
            demo_ready=ready,
            corpus_version=manifest.version,
            demo_questions=[q.question for q in manifest.questions],
        )

    assert owner is not None
    try:
        job = await jobs.get_job(owner, job_id)
        connected = await service.is_connected(user_id=owner)
        return DriveSyncStatusResponse(
            connected=connected,
            job=IndexingJobRead.model_validate(job) if job is not None else None,
        )
    except (IndexingTargetNotFound, IndexingStoreUnavailable, SQLAlchemyError) as exc:
        raise _job_error(exc) from None


@router.get("/pending")
async def get_pending_counts(
    owner: uuid.UUID | None = Depends(require_index_read_user),
    service: DriveSyncService = Depends(get_drive_sync_service),
    settings: Settings = Depends(get_settings),
) -> PendingCountsResponse:
    if settings.demo_mode:
        try:
            counts = await service.get_pending_counts(user_id=uuid.UUID(settings.demo_user_id))
        except ValueError:
            return PendingCountsResponse(to_ingest=0, to_chunk=0, to_build=0, any_pending=False)
    else:
        assert owner is not None
        try:
            counts = await service.get_pending_counts(user_id=owner)
        except (ValueError, SQLAlchemyError) as exc:
            raise _job_error(exc) from None
    return PendingCountsResponse(
        to_ingest=counts.to_ingest,
        to_chunk=counts.to_chunk,
        to_build=counts.to_build,
        any_pending=counts.any_pending,
    )
