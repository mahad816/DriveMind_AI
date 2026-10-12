"""Managed indexing execution; deliberately not started by the application yet.

One awaited polling loop processes one job at a time. PostgreSQL owns claims;
process-local state never grants permission to persist. There is no takeover or
automatic retry here. An interrupted BUILD retains recovery_required, and a
process crash leaves RUNNING work for the separately gated 4E3 recovery policy.
"""

from __future__ import annotations

import asyncio
import logging
import math
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.credential_diagnostics import safe_failure
from app.connectors.google_drive.constants import SUPPORTED_MIME_TYPES
from app.db.enums import DriveFileStatus, IndexingJobStatus, IndexingOperation
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.db.models.google_oauth_token import GoogleOAuthToken
from app.db.models.indexing_job import IndexingJob
from app.db.models.user import User
from app.embeddings.base import EmbeddingError, EmbeddingService
from app.embeddings.factory import get_embedding_service
from app.embeddings.qdrant_connection import create_qdrant_client
from app.embeddings.vector_store import (
    CollectionCompatibilityError,
    QdrantVectorStore,
    VectorStoreError,
)
from app.ingestion.chunking import chunk_text
from app.services.chunking_service import ChunkingService
from app.services.drive_content_service import DriveContentService, DriveFileContent
from app.services.drive_sync_service import DriveSyncService
from app.services.ingestion_service import IngestionService
from app.services.indexing_service import IndexingService

logger = logging.getLogger(__name__)

_STAGE_NAMES = {
    IndexingOperation.SYNC: "drive sync",
    IndexingOperation.INGEST: "ingestion",
    IndexingOperation.CHUNK: "chunking",
    IndexingOperation.BUILD: "index build",
}


class IndexingClaimLost(Exception):
    """No mutation or terminal transition is authorized by this claim."""


class IndexingSnapshotChanged(Exception):
    """Captured evidence no longer describes the authoritative SQL state."""


@dataclass(frozen=True)
class IndexingClaim:
    job_id: uuid.UUID
    user_id: uuid.UUID
    operation: IndexingOperation
    file_id: uuid.UUID | None
    full_sync: bool
    claim_id: uuid.UUID
    worker_id: uuid.UUID


@dataclass
class StageProgress:
    total: int = 0
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0


class _IndependentContent:
    """Ingestion downloads cannot commit the stage's accumulated ORM writes."""

    def __init__(self, worker: IndexingWorker) -> None:
        self.worker = worker

    async def fetch_file_content(
        self, file_id: uuid.UUID, user_id: uuid.UUID | None = None
    ) -> DriveFileContent:
        if not isinstance(user_id, uuid.UUID):
            raise ValueError("Explicit content owner is required")
        async with self.worker.sessions() as db:
            return await DriveContentService(db, self.worker.settings).fetch_file_content(
                file_id, user_id=user_id
            )


class IndexingWorker:
    """Explicitly constructed executor for controlled, independently owned work.

    Production lifespan neither constructs nor starts this executor in 4E2.
    Callers must await run/run_once; no detached tasks or environment activation.
    """

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: Settings,
        *,
        embedding_service: EmbeddingService | None = None,
        poll_seconds: float = 1.0,
    ) -> None:
        if settings.demo_mode:
            raise ValueError("Normal indexing workers are unavailable in demo mode")
        if not math.isfinite(poll_seconds) or not 0.1 <= poll_seconds <= 30:
            raise ValueError("Indexing polling must be bounded")
        if sessions.kw.get("expire_on_commit", True):
            raise ValueError("Indexing sessions must preserve captured snapshots after commit")
        self.sessions = sessions
        self.settings = settings
        self.embedding_service = embedding_service
        self.poll_seconds = poll_seconds
        self.worker_id = uuid.uuid4()
        self.demo_user_id = uuid.UUID(settings.demo_user_id) if settings.demo_user_id else None

    async def claim_next(self) -> IndexingClaim | None:
        async with self.sessions() as db, db.begin():
            job = await db.scalar(
                select(IndexingJob)
                .join(User, User.id == IndexingJob.user_id)
                .where(
                    IndexingJob.status == IndexingJobStatus.QUEUED,
                    IndexingJob.operation.is_not(None),
                    IndexingJob.claim_id.is_(None),
                    IndexingJob.recovery_required.is_(False),
                    User.id != self.demo_user_id,
                    ~User.google_id.startswith("demo:"),
                )
                .order_by(IndexingJob.created_at, IndexingJob.id)
                .with_for_update(skip_locked=True, of=IndexingJob)
                .limit(1)
            )
            if job is None:
                return None
            assert job.operation is not None
            job.status = IndexingJobStatus.RUNNING
            claim_id = uuid.uuid4()
            job.claim_id = claim_id
            job.worker_id = self.worker_id
            job.started_at = job.heartbeat_at = datetime.now(UTC)
            job.completed_at = None
            job.error = None
            return IndexingClaim(
                job.id,
                job.user_id,
                job.operation,
                job.file_id,
                job.full_sync,
                claim_id,
                self.worker_id,
            )

    async def _guard(self, db: AsyncSession, claim: IndexingClaim) -> IndexingJob:
        job = await db.scalar(
            select(IndexingJob)
            .join(User, User.id == IndexingJob.user_id)
            .where(
                IndexingJob.id == claim.job_id,
                IndexingJob.user_id == claim.user_id,
                IndexingJob.claim_id == claim.claim_id,
                IndexingJob.worker_id == claim.worker_id,
                IndexingJob.status == IndexingJobStatus.RUNNING,
                IndexingJob.operation == claim.operation,
                User.id != self.demo_user_id,
                ~User.google_id.startswith("demo:"),
                IndexingJob.full_sync == claim.full_sync,
                IndexingJob.file_id.is_(None)
                if claim.file_id is None
                else IndexingJob.file_id == claim.file_id,
            )
            .with_for_update(of=IndexingJob)
            .execution_options(populate_existing=True)
        )
        if job is None:
            raise IndexingClaimLost()
        return job

    async def finalize(
        self, claim: IndexingClaim, progress: StageProgress, *, error: str | None = None
    ) -> bool:
        # Always a fresh session: stage SQL failure may have poisoned its session.
        async with self.sessions() as db, db.begin():
            result = await db.execute(
                update(IndexingJob)
                .where(
                    IndexingJob.id == claim.job_id,
                    IndexingJob.user_id == claim.user_id,
                    IndexingJob.claim_id == claim.claim_id,
                    IndexingJob.worker_id == claim.worker_id,
                    IndexingJob.status == IndexingJobStatus.RUNNING,
                    IndexingJob.operation == claim.operation,
                    IndexingJob.full_sync == claim.full_sync,
                    IndexingJob.file_id.is_(None)
                    if claim.file_id is None
                    else IndexingJob.file_id == claim.file_id,
                    IndexingJob.user_id.in_(
                        select(User.id).where(
                            User.id != self.demo_user_id,
                            ~User.google_id.startswith("demo:"),
                        )
                    ),
                )
                .values(
                    status=IndexingJobStatus.FAILED if error else IndexingJobStatus.COMPLETED,
                    error=error,
                    completed_at=datetime.now(UTC),
                    total=progress.total,
                    processed=progress.processed,
                    succeeded=progress.succeeded,
                    failed=progress.failed,
                    skipped=progress.skipped,
                    **({"recovery_required": False} if error is None else {}),
                )
                .returning(IndexingJob.id)
            )
            return result.scalar_one_or_none() is not None

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            if await self.run_once():
                continue
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.poll_seconds)
            except TimeoutError:
                pass

    async def run_once(self) -> bool:
        """True means a job was claimed, not that its stage succeeded."""
        claim = await self.claim_next()
        if claim is None:
            return False
        await self.execute(claim)
        return True

    async def execute(self, claim: IndexingClaim) -> None:
        progress = StageProgress()
        try:
            async with self.sessions() as db:
                await self._guard(db, claim)
                await db.commit()
                if claim.operation == IndexingOperation.SYNC:
                    await self._sync(db, claim, progress)
                else:
                    await self._files(db, claim, progress)
            error = (
                f"{progress.failed} of {progress.total} files failed during {_STAGE_NAMES[claim.operation]}."
                if progress.failed
                else None
            )
        except asyncio.CancelledError:
            await self.finalize(claim, progress, error="Indexing execution interrupted.")
            raise
        except Exception as exc:
            error = safe_failure(exc, _STAGE_NAMES[claim.operation])
        await self.finalize(claim, progress, error=error)

    async def _sync(self, db: AsyncSession, claim: IndexingClaim, progress: StageProgress) -> None:
        service = DriveSyncService(db, self.settings)
        user = await service._resolve_user(claim.user_id)
        snapshot = await service._load_oauth_token(claim.user_id)
        state = await service._get_sync_state(claim.user_id)
        client = service._build_drive_client(snapshot)
        await db.commit()

        async def validate() -> None:
            await self._guard(db, claim)
            grant = await db.scalar(
                select(GoogleOAuthToken)
                .where(
                    GoogleOAuthToken.user_id == claim.user_id,
                    GoogleOAuthToken.id == snapshot.record.id,
                    GoogleOAuthToken.grant_epoch == snapshot.record.grant_epoch,
                    GoogleOAuthToken.grant_status == "ACTIVE",
                )
                .with_for_update()
            )
            if grant is None:
                raise IndexingSnapshotChanged()

        result: tuple[int, ...]
        if claim.full_sync or state is None:
            result = await service._run_full_sync(user, client, before_apply=validate)
        else:
            result = await service._run_incremental_sync(user, client, state, before_apply=validate)
        await self._guard(db, claim)
        await db.commit()
        progress.total = progress.processed = progress.succeeded = sum(result[:4])

    async def _files(self, db: AsyncSession, claim: IndexingClaim, progress: StageProgress) -> None:
        if claim.file_id is not None:
            ids = [claim.file_id]
        else:
            query = select(DriveFile.id).where(DriveFile.user_id == claim.user_id)
            if claim.operation == IndexingOperation.INGEST:
                query = query.where(
                    DriveFile.status.in_(
                        [
                            DriveFileStatus.DISCOVERED,
                            DriveFileStatus.INDEXING,
                            DriveFileStatus.FAILED,
                        ]
                    ),
                    DriveFile.mime_type.in_(list(SUPPORTED_MIME_TYPES)),
                )
            else:
                query = query.where(DriveFile.status == DriveFileStatus.INDEXING)
            ids = list((await db.scalars(query.order_by(DriveFile.id))).all())
        progress.total = len(ids)
        await db.commit()
        for file_id in ids:
            await self._file(db, claim, file_id, progress)

    async def _file(
        self,
        db: AsyncSession,
        claim: IndexingClaim,
        file_id: uuid.UUID,
        progress: StageProgress,
    ) -> None:
        active_job = await self._guard(db, claim)
        recovery_before = active_job.recovery_required
        file = await db.scalar(
            select(DriveFile).where(
                DriveFile.id == file_id,
                DriveFile.user_id == claim.user_id,
            )
        )
        if file is None:
            raise IndexingSnapshotChanged()
        document = None
        if file.status != DriveFileStatus.SKIPPED and (
            claim.operation == IndexingOperation.INGEST or file.status == DriveFileStatus.INDEXING
        ):
            document = await db.scalar(
                select(Document)
                .where(Document.drive_file_id == file_id)
                .order_by(Document.updated_at.desc(), Document.id)
                .limit(1)
            )
        frame = (
            file.modified_at,
            file.status,
            file.drive_file_id,
            file.name,
            file.mime_type,
            document.id if document else None,
            document.extracted_text_hash if document else None,
            document.extracted_text if document else None,
        )
        chunk_frame: dict[uuid.UUID, tuple[str, object, int]] | None = None

        async def validate() -> None:
            await self._guard(db, claim)
            current_file = await db.scalar(
                select(DriveFile)
                .where(
                    DriveFile.id == file_id,
                    DriveFile.user_id == claim.user_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            current_doc = await db.scalar(
                select(Document)
                .where(
                    Document.drive_file_id == file_id,
                )
                .order_by(Document.updated_at.desc(), Document.id)
                .limit(1)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if current_file is None or frame != (
                current_file.modified_at,
                current_file.status,
                current_file.drive_file_id,
                current_file.name,
                current_file.mime_type,
                current_doc.id if current_doc else None,
                current_doc.extracted_text_hash if current_doc else None,
                current_doc.extracted_text if current_doc else None,
            ):
                raise IndexingSnapshotChanged()
            if chunk_frame is not None:
                assert current_doc is not None
                chunks = list(
                    (
                        await db.scalars(
                            select(Chunk)
                            .where(
                                Chunk.document_id == current_doc.id,
                            )
                            .with_for_update()
                            .execution_options(populate_existing=True)
                        )
                    ).all()
                )
                if chunk_frame != {
                    c.id: (c.text, c.metadata_json.get("extracted_text_hash"), c.chunk_index)
                    for c in chunks
                }:
                    raise IndexingSnapshotChanged()

        async def release() -> None:
            await self._guard(db, claim)
            if claim.operation == IndexingOperation.BUILD:
                job = await self._guard(db, claim)
                job.recovery_required = True
            await db.commit()

        if claim.operation == IndexingOperation.INGEST:
            service = IngestionService(db, self.settings)
            service.content_service = _IndependentContent(self)
            outcome = await service._ingest_single_file(
                file,
                before_external=release,
                before_persist=validate,
            )
        elif file.status != DriveFileStatus.INDEXING or document is None:
            outcome = "skipped"
        else:
            chunker = ChunkingService(db, self.settings)
            text_snapshot = document.extracted_text
            await db.commit()
            prepared = await asyncio.to_thread(
                chunk_text,
                text_snapshot,
                config=chunker.chunking_config,
            )
            await validate()
            outcome = await chunker._replace_chunks(document, prepared_chunks=prepared)
            await db.flush()
            await self._guard(db, claim)
            await db.commit()
            if claim.operation == IndexingOperation.BUILD:
                if outcome == "skipped":
                    # Zero chunks retain the established SKIPPED outcome.
                    frame = (
                        file.modified_at,
                        file.status,
                        file.drive_file_id,
                        file.name,
                        file.mime_type,
                        document.id,
                        document.extracted_text_hash,
                        document.extracted_text,
                    )
                chunks = list(
                    (
                        await db.scalars(
                            select(Chunk).where(
                                Chunk.document_id == document.id,
                            )
                        )
                    ).all()
                )
                chunk_frame = {
                    c.id: (c.text, c.metadata_json.get("extracted_text_hash"), c.chunk_index)
                    for c in chunks
                }
                await release()
                client = create_qdrant_client(self.settings)
                try:
                    embeddings = self.embedding_service or get_embedding_service(self.settings)
                    store = QdrantVectorStore(self.settings, client=client, verify_writes=True)
                    await store.ensure_collection(vector_size=embeddings.embedding_dimension)
                    indexer = IndexingService(
                        db,
                        self.settings,
                        embedding_service=embeddings,
                        vector_store=store,
                    )
                    # Load SQL evidence, then commit it before the first vector mutation.
                    await validate()
                    await indexer._index_document(
                        document,
                        prepared=True,
                        before_external=release,
                        before_persist=validate,
                    )
                    outcome = "skipped" if not chunks else "indexed"
                except (EmbeddingError, VectorStoreError) as exc:
                    await validate()
                    if isinstance(exc, CollectionCompatibilityError):
                        logger.warning(
                            "Index build requires a Qdrant collection with unnamed COSINE "
                            "vectors matching the configured embedding dimension; "
                            "inspect the collection configuration."
                        )
                        if not recovery_before:
                            # Do not clear uncertainty from an earlier file.
                            active_job.recovery_required = False
                    file.status = DriveFileStatus.FAILED
                    outcome = "failed"
                finally:
                    await client.close()
        committed = replace(progress, processed=progress.processed + 1)
        if outcome == "failed":
            committed.failed += 1
        elif outcome == "skipped":
            committed.skipped += 1
        else:
            committed.succeeded += 1
        job = await self._guard(db, claim)
        job.total, job.processed = committed.total, committed.processed
        job.succeeded, job.failed, job.skipped = (
            committed.succeeded,
            committed.failed,
            committed.skipped,
        )
        job.heartbeat_at = datetime.now(UTC)
        await db.commit()
        progress.processed = committed.processed
        progress.succeeded, progress.failed, progress.skipped = (
            committed.succeeded,
            committed.failed,
            committed.skipped,
        )
