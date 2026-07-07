"""Drive indexing sync routes."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.google_drive.client import DriveClientError
from app.db.session import get_db
from app.embeddings.base import EmbeddingConfigurationError, EmbeddingError
from app.embeddings.vector_store import VectorStoreError
from app.schemas.chunking import ChunkingResponse
from app.schemas.drive_sync import DriveSyncResponse, DriveSyncStatusResponse
from app.schemas.index_build import IndexBuildResponse
from app.schemas.indexing import IndexingJobRead
from app.schemas.ingest import IngestionResponse
from app.services.chunking_service import ChunkingService
from app.services.drive_sync_service import DriveSyncService
from app.services.indexing_service import IndexingService
from app.services.ingestion_service import IngestionService

router = APIRouter(prefix="/index")


def get_drive_sync_service(db: AsyncSession = Depends(get_db)) -> DriveSyncService:
    """Dependency provider for Drive sync service."""
    return DriveSyncService(db=db)


def get_ingestion_service(db: AsyncSession = Depends(get_db)) -> IngestionService:
    """Dependency provider for document ingestion service."""
    return IngestionService(db=db)


def get_chunking_service(db: AsyncSession = Depends(get_db)) -> ChunkingService:
    """Dependency provider for document chunking service."""
    return ChunkingService(db=db)


def get_indexing_service(db: AsyncSession = Depends(get_db)) -> IndexingService:
    """Dependency provider for vector indexing service."""
    return IndexingService(db=db)


@router.post("/sync", summary="Sync Drive file metadata")
async def sync_drive_metadata(
    full: bool = Query(
        default=False,
        description="Force a full Drive scan. Default uses incremental sync when available.",
    ),
    service: DriveSyncService = Depends(get_drive_sync_service),
) -> DriveSyncResponse:
    """Sync Drive metadata using incremental Changes API or a full scan."""
    try:
        result = await service.sync_metadata(full=full)
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

    mode_label = "full" if result.mode == "full" else "incremental"
    return DriveSyncResponse(
        job_id=result.job_id,
        user_id=result.user_id,
        mode=result.mode,
        created=result.created,
        updated=result.updated,
        unchanged=result.unchanged,
        removed=result.removed,
        total_seen=result.total_seen,
        message=f"Drive metadata {mode_label} sync completed",
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


@router.post("/ingest", summary="Ingest synced Drive files into extracted documents")
async def ingest_drive_files(
    file_id: uuid.UUID | None = Query(
        default=None,
        description="Optional synced drive_files.id to ingest a single file.",
    ),
    service: IngestionService = Depends(get_ingestion_service),
) -> IngestionResponse:
    """Fetch supported Drive files, extract text, and persist documents."""
    try:
        result = await service.ingest_files(file_id=file_id)
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

    scope = "file" if file_id is not None else "batch"
    return IngestionResponse(
        job_id=result.job_id,
        user_id=result.user_id,
        ingested=result.ingested,
        unchanged=result.unchanged,
        failed=result.failed,
        skipped=result.skipped,
        total=result.total,
        message=f"Drive text ingestion ({scope}) completed",
    )


@router.post("/chunk", summary="Chunk extracted documents into searchable segments")
async def chunk_extracted_documents(
    file_id: uuid.UUID | None = Query(
        default=None,
        description="Optional synced drive_files.id to chunk a single file's document.",
    ),
    service: ChunkingService = Depends(get_chunking_service),
) -> ChunkingResponse:
    """Split extracted document text into chunk rows stored in PostgreSQL."""
    try:
        result = await service.chunk_documents(file_id=file_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    scope = "file" if file_id is not None else "batch"
    return ChunkingResponse(
        job_id=result.job_id,
        user_id=result.user_id,
        chunked=result.chunked,
        unchanged=result.unchanged,
        skipped=result.skipped,
        total=result.total,
        message=f"Document chunking ({scope}) completed",
    )


@router.post("/build", summary="Build vector index from chunked documents")
async def build_vector_index(
    file_id: uuid.UUID | None = Query(
        default=None,
        description="Optional synced drive_files.id to index a single file's document.",
    ),
    service: IndexingService = Depends(get_indexing_service),
) -> IndexBuildResponse:
    """Chunk documents, embed pending chunks, and upsert vectors into Qdrant."""
    try:
        result = await service.build_index(file_id=file_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except (EmbeddingConfigurationError, EmbeddingError, VectorStoreError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    scope = "file" if file_id is not None else "batch"
    return IndexBuildResponse(
        job_id=result.job_id,
        user_id=result.user_id,
        embedded=result.embedded,
        unchanged=result.unchanged,
        skipped=result.skipped,
        failed=result.failed,
        removed=result.removed,
        total=result.total,
        message=f"Vector index build ({scope}) completed",
    )
