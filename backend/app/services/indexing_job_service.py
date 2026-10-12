"""Owner-scoped indexing admission and reads. No dispatch or worker execution."""

from uuid import UUID
from collections.abc import Callable
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.enums import IndexingJobStatus, IndexingOperation
from app.db.models.drive_file import DriveFile
from app.db.models.indexing_job import IndexingJob
from app.db.models.user import User
from app.services.indexing_maintenance import writer_available


class IndexingAdmissionUnavailable(Exception):
    """Lifecycle closure or a bounded admission deadline rejected publication."""


class IndexingAdmissionConflict(Exception):
    pass


class IndexingTargetNotFound(Exception):
    pass


class IndexingStoreUnavailable(Exception):
    pass


class IndexingJobService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def admit(
        self,
        user_id: UUID,
        operation: IndexingOperation,
        *,
        authorize: Callable[[], None],
        file_id: UUID | None = None,
        full_sync: bool = False,
    ) -> IndexingJob:
        if not isinstance(user_id, UUID) or not isinstance(operation, IndexingOperation):
            raise ValueError("Explicit owner and operation are required")
        if (operation == IndexingOperation.SYNC and file_id is not None) or (
            operation != IndexingOperation.SYNC and full_sync
        ):
            raise ValueError("Invalid indexing operation inputs")
        try:
            if not await writer_available(self.db):
                raise IndexingAdmissionUnavailable()
            # Serialize admission for this owner, including targets and legacy blockers.
            owner = await self.db.scalar(
                select(User.id).where(User.id == user_id).with_for_update()
            )
            if owner is None:
                raise IndexingTargetNotFound()
            if file_id is not None:
                target = await self.db.scalar(
                    select(DriveFile.id)
                    .where(DriveFile.id == file_id, DriveFile.user_id == user_id)
                    .with_for_update()
                )
                if target is None:
                    raise IndexingTargetNotFound()
            unresolved = await self.db.scalar(
                select(IndexingJob.id)
                .where(
                    IndexingJob.user_id == user_id,
                    or_(
                        IndexingJob.status.in_(
                            [IndexingJobStatus.QUEUED, IndexingJobStatus.RUNNING]
                        ),
                        IndexingJob.recovery_required,
                    ),
                )
                .limit(1)
            )
            if unresolved is not None:
                raise IndexingAdmissionConflict()
            job = IndexingJob(
                user_id=user_id,
                operation=operation,
                file_id=file_id,
                full_sync=full_sync,
                status=IndexingJobStatus.QUEUED,
            )
            # No await between the synchronous lifecycle permit transition and
            # starting publication. All owner/target/uniqueness waits precede it.
            # A subsequent closure cannot revoke an already-granted commit.
            authorize()
            self.db.add(job)
            await self.db.commit()
            return job
        except (IndexingAdmissionConflict, IndexingTargetNotFound, IndexingAdmissionUnavailable):
            await self.db.rollback()
            raise
        except IntegrityError as exc:
            await self.db.rollback()
            cause = getattr(exc.orig, "__cause__", None)
            if getattr(cause, "constraint_name", None) == "uq_indexing_jobs_unresolved_owner":
                raise IndexingAdmissionConflict() from None
            raise IndexingStoreUnavailable() from None
        except SQLAlchemyError:
            await self.db.rollback()
            raise IndexingStoreUnavailable() from None

    async def get_job(self, user_id: UUID, job_id: UUID | None = None) -> IndexingJob | None:
        if not isinstance(user_id, UUID):
            raise ValueError("Explicit owner is required")
        try:
            query = select(IndexingJob).where(IndexingJob.user_id == user_id)
            if job_id is not None:
                query = query.where(IndexingJob.id == job_id)
            else:
                query = query.order_by(IndexingJob.created_at.desc(), IndexingJob.id.desc()).limit(
                    1
                )
            job = await self.db.scalar(query)
            if job_id is not None and job is None:
                raise IndexingTargetNotFound()
            return job
        except SQLAlchemyError:
            raise IndexingStoreUnavailable() from None
