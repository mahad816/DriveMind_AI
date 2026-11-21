"""KI-031 (fixed): services picked an arbitrary owner's Google credential when no owner was given.

M0 ticket 03 (audit area A2) found six sites that ran ``select(GoogleOAuthToken).limit(1)`` (no
owner filter, no ordering) when called with ``user_id=None`` and then acted as the owner of
whichever credential row PostgreSQL returned first. M0-SEC tickets 01 and 02 removed all six
(``user_resolution``, ``drive_sync``, ``drive_content``, ``chunking``, ``ingestion``,
``indexing``). These are now ordinary regression tests.

The tests state the correct behaviour: with no owner given, the call must be refused
(``ValueError``), never resolved to somebody's account. They do not depend on WHICH owner
PostgreSQL returns, so they are deterministic. The guards check that an explicit owner resolves to
exactly that owner even when a second owner with a credential exists.

Needs the disposable PostgreSQL (``SESSION_TEST_DATABASE_URL``); skipped without it. No Google, Qdrant
or OpenAI call is made: the embedding service and vector store are stubs and are never used.
"""

import re
from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.models.user import User
from app.services.chunking_service import ChunkingService
from app.services.drive_content_service import DriveContentService
from app.services.drive_sync_service import DriveSyncService
from app.services.indexing_service import IndexingService
from app.services.ingestion_service import IngestionService
from app.services.user_resolution import resolve_active_user
from tests.credential_fixtures import synthetic_oauth_row
from tests.security.conftest import (
    USER_A,
    USER_B,
    apply_revision,
    pg_engine,  # noqa: F401  # pyright: ignore[reportUnusedImport]  (pytest fixture, by name)
)

SCOPES = "https://www.googleapis.com/auth/drive.readonly"
CREDENTIAL_REVISIONS = ("20261009_1300", "20261010_1200", "20261011_1200")
Resolver = Callable[[AsyncSession, Settings, Any], Awaitable[User]]


async def _user_resolution(db: AsyncSession, settings: Settings, owner: Any) -> User:
    return await resolve_active_user(db, settings, owner)


async def _drive_sync(db: AsyncSession, settings: Settings, owner: Any) -> User:
    return await DriveSyncService(db, settings)._resolve_user(owner)


async def _drive_content(db: AsyncSession, settings: Settings, owner: Any) -> User:
    return await DriveContentService(db, settings)._resolve_user(owner)


async def _chunking(db: AsyncSession, settings: Settings, owner: Any) -> User:
    return await ChunkingService(db, settings)._resolve_user(owner)


async def _ingestion(db: AsyncSession, settings: Settings, owner: Any) -> User:
    return await IngestionService(db, settings)._resolve_user(owner)


async def _indexing(db: AsyncSession, settings: Settings, owner: Any) -> User:
    service = IndexingService(db, settings, embedding_service=MagicMock(), vector_store=MagicMock())
    return await service._resolve_user(owner)


SITES: dict[str, Resolver] = {
    "user_resolution": _user_resolution,
    "drive_sync": _drive_sync,
    "drive_content": _drive_content,
    "chunking": _chunking,
    "ingestion": _ingestion,
    "indexing": _indexing,
}


@pytest.fixture
async def two_owners(pg_engine, monkeypatch: pytest.MonkeyPatch):  # noqa: F811
    """Two normal owners, each with an ACTIVE credential: the state in which "first" is ambiguous."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    async with pg_engine.begin() as connection:
        # The shared fixture stops before the encrypted-credential columns exist.
        for revision in CREDENTIAL_REVISIONS:
            await connection.run_sync(apply_revision, revision)
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with factory.begin() as db:
        db.add(synthetic_oauth_row(user_id=USER_A, scopes=SCOPES))
        db.add(synthetic_oauth_row(user_id=USER_B, scopes=SCOPES))
    return factory


def _settings() -> Settings:
    return Settings(demo_mode=False)  # type: ignore[call-arg]


@pytest.mark.parametrize("site", list(SITES))
async def test_no_owner_must_not_resolve_to_an_arbitrary_credential_owner(
    two_owners, site: str
) -> None:
    async with two_owners() as db:
        try:
            resolved = await SITES[site](db, _settings(), None)
        except ValueError as exc:
            # Only a refusal that names the missing owner counts: "User not found" and "No Google
            # Drive connection found" are other failures of the same code path.
            assert re.search(r"explicit.*owner", str(exc), re.IGNORECASE), str(exc)
            return
    raise AssertionError(
        f"{site}: called with no owner, resolved to owner {resolved.id} "
        f"although two owners hold credentials (expected ValueError)"
    )


@pytest.mark.parametrize("site", list(SITES))
@pytest.mark.parametrize("owner", [USER_A, USER_B], ids=["owner_a", "owner_b"])
async def test_explicit_owner_resolves_to_exactly_that_owner(two_owners, site: str, owner) -> None:
    async with two_owners() as db:
        resolved = await SITES[site](db, _settings(), owner)
    assert resolved.id == owner
