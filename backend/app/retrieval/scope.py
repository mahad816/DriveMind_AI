"""One concrete eligibility predicate for all scoped SQL retrieval paths."""

from uuid import UUID

from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.ext.asyncio import AsyncSession, AsyncEngine, async_sessionmaker
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from app.db.models.drive_file import DriveFile
from app.db.enums import DriveFileStatus
from app.routing.intent_frame.execution import RetrievalRequest
from app.routing.intent_frame.scope import EligibleCollectionScope, ResolvedFileScope


def require_request(request: RetrievalRequest) -> None:
    """Reject string/ownerless compatibility calls before any provider or SQL work."""
    if not isinstance(request, RetrievalRequest):
        raise ValueError("An owner-scoped RetrievalRequest is required")
    # Also defend internal callers using Pydantic's unchecked model_construct().
    if not isinstance(request.user_id, UUID):
        raise ValueError("A valid corpus owner UUID is required")
    if not isinstance(request.scope, (EligibleCollectionScope, ResolvedFileScope)):
        raise ValueError("A supported retrieval scope is required")
    if isinstance(request.scope, ResolvedFileScope) and not request.scope.file_ids:
        raise ValueError("EMPTY_EXACT_SCOPE")


def eligibility(request: RetrievalRequest) -> tuple[ColumnElement[bool], ...]:
    require_request(request)
    predicates = [
        DriveFile.status == DriveFileStatus.INDEXED,
        DriveFile.user_id == request.user_id,
    ]
    if isinstance(request.scope, ResolvedFileScope):
        predicates.append(DriveFile.id.in_(request.scope.file_ids))
    return tuple(predicates)


def is_eligible(file: DriveFile, request: RetrievalRequest) -> bool:
    require_request(request)
    return (
        file.status == DriveFileStatus.INDEXED
        and file.user_id == request.user_id
        and (not isinstance(request.scope, ResolvedFileScope) or file.id in request.scope.file_ids)
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
