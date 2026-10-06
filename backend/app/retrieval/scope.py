"""One concrete eligibility predicate for all scoped SQL retrieval paths."""

from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.ext.asyncio import AsyncSession, AsyncEngine, async_sessionmaker
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from app.db.models.drive_file import DriveFile
from app.db.enums import DriveFileStatus
from app.routing.intent_frame.execution import RetrievalRequest
from app.routing.intent_frame.scope import ResolvedFileScope


def eligibility(request: RetrievalRequest | None) -> tuple[ColumnElement[bool], ...]:
    predicates = [DriveFile.status == DriveFileStatus.INDEXED]
    if request is not None:
        predicates.append(DriveFile.user_id == request.user_id)
        if isinstance(request.scope, ResolvedFileScope):
            if not request.scope.file_ids:
                raise ValueError("EMPTY_EXACT_SCOPE")
            predicates.append(DriveFile.id.in_(request.scope.file_ids))
    return tuple(predicates)


def is_eligible(file: DriveFile, request: RetrievalRequest | None) -> bool:
    return file.status == DriveFileStatus.INDEXED and (
        request is None
        or (
            file.user_id == request.user_id
            and (
                not isinstance(request.scope, ResolvedFileScope)
                or file.id in request.scope.file_ids
            )
        )
    )


@asynccontextmanager
async def scoped_session(db: AsyncSession) -> AsyncIterator[AsyncSession]:
    """Each parallel strategy gets its own session; mocks stay dependency-injected."""
    if isinstance(db, AsyncSession):
        bind = getattr(db, "bind", None)
        if not isinstance(bind, AsyncEngine):
            raise ValueError("Scoped parallel retrieval requires an AsyncEngine-bound session")
        async with async_sessionmaker(bind, expire_on_commit=False)() as session:
            yield session
    else:
        # Test doubles implement the session surface without opening a connection.
        yield db
