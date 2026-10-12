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
from datetime import datetime, timedelta

from sqlalchemy import func, select, text, update
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
        lease_seconds: float = 60.0,
        heartbeat_seconds: float = 10.0,
        lock_timeout_seconds: float = 2.0,
    ) -> None:
        if settings.demo_mode:
            raise ValueError("Normal indexing workers are unavailable in demo mode")
        if not math.isfinite(poll_seconds) or not 0.1 <= poll_seconds <= 30:
            raise ValueError("Indexing polling must be bounded")
        if sessions.kw.get("expire_on_commit", True):
            raise ValueError("Indexing sessions must preserve captured snapshots after commit")
        if (
            not all(
                math.isfinite(v) for v in (lease_seconds, heartbeat_seconds, lock_timeout_seconds)
            )
            or not 0.1 <= lease_seconds <= 300
            or not 0.01 <= heartbeat_seconds < lease_seconds / 3
            or not 0.01 <= lock_timeout_seconds <= 10
        ):
            raise ValueError("Indexing lease and heartbeat settings must be bounded")
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.lock_timeout_seconds = lock_timeout_seconds
        self.sessions = sessions
        self.settings = settings
        self.embedding_service = embedding_service
        self.poll_seconds = poll_seconds
        self.worker_id = uuid.uuid4()
        self.demo_user_id = uuid.UUID(settings.demo_user_id) if settings.demo_user_id else None

    async def claim_next(self) -> IndexingClaim | None:
        async with self.sessions() as db, db.begin():
            await self._transaction_limits(db)
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
            now = await self._database_time(db)
            job.started_at = job.heartbeat_at = now
            job.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
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

    async def _transaction_limits(self, db: AsyncSession) -> None:
        # Explicit READ COMMITTED is necessary for a fresh post-lock statement.
        # These settings affect this transaction only, not shared application sessions.
        connection = await db.connection()
        if await connection.get_isolation_level() != "READ COMMITTED":
            raise ValueError("Indexing requires READ COMMITTED transactions")
        await db.execute(
            select(
                func.set_config("lock_timeout", f"{int(self.lock_timeout_seconds * 1000)}ms", True)
            ),
            execution_options={"autoflush": False},
        )
        await db.execute(
            text("SET LOCAL statement_timeout = '15s'"),
            execution_options={"autoflush": False},
        )

    async def _database_time(self, db: AsyncSession) -> datetime:
        now = await db.scalar(
            select(func.clock_timestamp()), execution_options={"autoflush": False}
        )
        assert isinstance(now, datetime)
        return now

    async def _guard(self, db: AsyncSession, claim: IndexingClaim) -> IndexingJob:
        # Never flush dirty stage objects or refresh a dirty job to authorize it.
        # PostgreSQL can evaluate a WHERE expiry check BEFORE waiting for a lock.
        # Lock identity first, then obtain a fresh clock in a separate statement.
        poisoned = db.info.get("indexing_attempt_poisoned")
        if isinstance(poisoned, asyncio.Event) and poisoned.is_set():
            raise IndexingClaimLost()
        await self._transaction_limits(db)
        with db.no_autoflush:
            row = (
                await db.execute(
                    select(IndexingJob.id, IndexingJob.lease_expires_at)
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
                )
            ).one_or_none()
            if row is None or row.lease_expires_at is None:
                raise IndexingClaimLost()
            if row.lease_expires_at <= await self._database_time(db):
                raise IndexingClaimLost()
            if isinstance(poisoned, asyncio.Event) and poisoned.is_set():
                raise IndexingClaimLost()
            job = await db.get(IndexingJob, claim.job_id)
            assert job is not None
            return job

    async def _commit(self, db: AsyncSession, claim: IndexingClaim) -> None:
        try:
            await self._guard(db, claim)
            await db.commit()
        except BaseException:
            await db.rollback()
            raise

    async def renew_lease(self, claim: IndexingClaim) -> None:
        async with self.sessions() as db, db.begin():
            job = await self._guard(db, claim)
            now = await self._database_time(db)
            if job.lease_expires_at is None or job.lease_expires_at <= now:
                raise IndexingClaimLost()
            await db.execute(
                update(IndexingJob)
                .where(IndexingJob.id == claim.job_id)
                .values(
                    heartbeat_at=now, lease_expires_at=now + timedelta(seconds=self.lease_seconds)
                )
            )

    async def _heartbeat(self, claim: IndexingClaim, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.heartbeat_seconds)
            except TimeoutError:
                # Bound connection acquisition/transport stalls too, not just
                # PostgreSQL lock waits. Timeout poisons the owned attempt.
                async with asyncio.timeout(min(15.0, self.lease_seconds / 3)):
                    await self.renew_lease(claim)

    async def finalize(
        self, claim: IndexingClaim, progress: StageProgress, *, error: str | None = None
    ) -> bool:
        # Always a fresh session: stage SQL failure may have poisoned its session.
        async with self.sessions() as db, db.begin():
            try:
                await self._guard(db, claim)
            except IndexingClaimLost:
                return False
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
                    completed_at=func.clock_timestamp(),
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
        stop = asyncio.Event()
        # Initial renewal must succeed before the stage can start. No orphaned
        # heartbeat exists if authorization or initialization fails.
        try:
            await self.renew_lease(claim)
        except IndexingClaimLost:
            return
        poisoned = asyncio.Event()

        async def supervise_heartbeat() -> None:
            try:
                await self._heartbeat(claim, stop)
            finally:
                if not stop.is_set():
                    # Poison before the supervisor is rescheduled; stage guards
                    # cannot authorize another batch while cancellation is pending.
                    poisoned.set()

        heartbeat = asyncio.create_task(supervise_heartbeat(), name="indexing-heartbeat")
        stage = asyncio.create_task(
            self._execute_stage(claim, progress, poisoned), name="indexing-stage"
        )
        error: str | None = None
        interrupted = False

        async def join_owned(task: asyncio.Task[None]) -> tuple[None | BaseException, ...]:
            nonlocal interrupted
            joined = asyncio.gather(task, return_exceptions=True)
            while True:
                try:
                    return tuple(await asyncio.shield(joined))
                except asyncio.CancelledError:
                    # Repeated caller cancellation must not detach cleanup or
                    # send a second cancellation into an issued remote request.
                    interrupted = True
                    poisoned.set()

        try:
            done, _ = await asyncio.wait({stage, heartbeat}, return_when=asyncio.FIRST_COMPLETED)
            if heartbeat in done:
                # An unsolicited heartbeat termination is always fatal to this
                # attempt, even if the stage happens to finish at the same time.
                stage.cancel()
                await join_owned(stage)
                error = "Indexing heartbeat failed."
                # Retrieve the exception without exposing database/provider detail.
                await join_owned(heartbeat)
            else:
                await asyncio.shield(stage)
                if progress.failed:
                    error = (
                        f"{progress.failed} of {progress.total} files failed "
                        f"during {_STAGE_NAMES[claim.operation]}."
                    )
        except asyncio.CancelledError:
            interrupted = True
            poisoned.set()
            stage.cancel()
            await join_owned(stage)
            error = "Indexing execution interrupted."
        except Exception as exc:
            error = safe_failure(exc, _STAGE_NAMES[claim.operation])
        finally:
            # Stage sessions are closed before joining heartbeat. Never wait for
            # renewal while holding the row lock it needs. Join before finalizing.
            stop.set()
            heartbeat_result = await join_owned(heartbeat)
            if isinstance(heartbeat_result[0], BaseException) and error is None:
                error = "Indexing heartbeat failed."
        if interrupted:
            error = "Indexing execution interrupted."
        if not await self.finalize(claim, progress, error=error):
            logger.warning("Indexing attempt no longer authorized for terminal publication")
        if interrupted:
            raise asyncio.CancelledError

    async def _execute_stage(
        self, claim: IndexingClaim, progress: StageProgress, poisoned: asyncio.Event
    ) -> None:
        async with self.sessions() as db:
            # Attempt-local cancellation signal, never an authorization identity.
            db.info["indexing_attempt_poisoned"] = poisoned
            await self._commit(db, claim)
            if claim.operation == IndexingOperation.SYNC:
                await self._sync(db, claim, progress)
            else:
                await self._files(db, claim, progress)

    async def _sync(self, db: AsyncSession, claim: IndexingClaim, progress: StageProgress) -> None:
        service = DriveSyncService(db, self.settings)
        user = await service._resolve_user(claim.user_id)
        snapshot = await service._load_oauth_token(claim.user_id)
        state = await service._get_sync_state(claim.user_id)
        client = service._build_drive_client(snapshot)
        await self._commit(db, claim)

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
        await self._commit(db, claim)
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
        await self._commit(db, claim)
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
            await self._commit(db, claim)

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
            await self._commit(db, claim)
            prepared = await asyncio.to_thread(
                chunk_text,
                text_snapshot,
                config=chunker.chunking_config,
            )
            await validate()
            outcome = await chunker._replace_chunks(document, prepared_chunks=prepared)
            await self._guard(db, claim)
            await db.flush()
            await self._guard(db, claim)
            await self._commit(db, claim)
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

                    async def authorize_mutation() -> None:
                        await validate()
                        await release()

                    store = QdrantVectorStore(
                        self.settings,
                        client=client,
                        verify_writes=True,
                        before_mutation=authorize_mutation,
                    )
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
        await self._commit(db, claim)
        progress.processed = committed.processed
        progress.succeeded, progress.failed, progress.skipped = (
            committed.succeeded,
            committed.failed,
            committed.skipped,
        )
