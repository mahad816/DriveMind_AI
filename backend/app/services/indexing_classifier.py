"""Explicit classification only. Expiry is never evidence of remote quiescence."""

from __future__ import annotations

from uuid import UUID
from sqlalchemy import select
from app.db.enums import IndexingJobStatus, IndexingOperation
from app.db.models.indexing_job import IndexingJob
from app.db.models.user import User
from app.services.indexing_attempt import AttemptEvidenceError, read_attempt
from app.services.indexing_worker import IndexingWorker


class IndexingClassifier:
    def __init__(self, worker: IndexingWorker) -> None:
        self.worker = worker

    async def classify(self, job_id: UUID) -> str:
        async with self.worker.sessions() as db, db.begin():
            await self.worker._transaction_limits(db)
            job = await db.scalar(
                select(IndexingJob)
                .join(User, User.id == IndexingJob.user_id)
                .where(
                    IndexingJob.id == job_id,
                    IndexingJob.operation.is_not(None),
                    User.id != self.worker.demo_user_id,
                    ~User.google_id.startswith("demo:"),
                )
                .with_for_update(of=IndexingJob)
                .execution_options(populate_existing=True)
            )
            if job is None or job.status != IndexingJobStatus.RUNNING:
                return "UNCHANGED"
            if job.lease_expires_at is None or job.claim_id is None or job.worker_id is None:
                return "REVIEW_REQUIRED"
            now = await self.worker._database_time(db)
            if job.lease_expires_at > now:
                return "LIVE"
            recovery = job.recovery_required
            if job.operation == IndexingOperation.BUILD:
                try:
                    attempt = read_attempt(job, self.worker.settings.qdrant_collection)
                    # Even acknowledged requests may outlive SQL publication.
                    # No automatic reconciliation or release after remote effects.
                    recovery = attempt.prior_recovery_required or any(
                        f.mutations for f in attempt.files
                    )
                except AttemptEvidenceError:
                    recovery = True
            job.status = IndexingJobStatus.FAILED
            job.error = (
                "Indexing lease expired; operator recovery required."
                if recovery
                else "Indexing lease expired; execution interrupted."
            )
            job.recovery_required = recovery
            job.completed_at = now
            # Row lock fences the exact loaded attempt until commit. Retain its
            # claim identity and evidence for audit; RUNNING guards now reject it.
            await db.flush()
            return "RECOVERY_REQUIRED" if recovery else "FAILED"
