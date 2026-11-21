"""KI-032 (FIXED, M0-SEC ticket 07): abandoned Google login attempts used to stay in ``oauth_pending_states``.

Fixed by pruning expired rows when a login starts, plus a global limit on the endpoint (tests in
``tests/security/test_login_start_limit.py``). The marker is removed; both tests below are ordinary
regression tests now. The text below is the historical description of the defect (it said "open" and "passes today"
before the fix).

M0 ticket 04 (audit area A2). ``POST /api/v1/auth/session/google`` with intent ``LOGIN`` needs no
session, only a matching ``Origin`` header and ``X-DriveMind-Auth: 1`` (both are plain request headers,
so any HTTP client can send them). Each call commits one ``OAuthPendingState`` row that lives for ten
minutes. A row is deleted only when its callback consumes it. The one cleanup of expired rows
(``GoogleOAuthService._cleanup_expired_pending_states``) runs inside the legacy ``handle_callback``,
which belongs to the unmounted legacy router, so nothing in the running application ever removes a
login that was started and never finished. The table therefore grows by one row per request, without
limit, whenever ``GOOGLE_APPLICATION_SESSIONS_ENABLED`` is on.

This is an availability and storage-growth defect, not an authentication or data-isolation one:
a row holds only a PKCE verifier, a nonce and hashes, and cannot be redeemed after it expires.

The test states the correct behaviour in the one way a unit test can: after a login attempt has
expired and another login starts, the expired attempt is gone. A fix that prunes at start satisfies it.
A fix that prunes on a schedule outside the request would need this test rewritten to call that
sweeper; the registry entry says so. The guard passes today: starting a login never removes another
browser's still-valid attempt, so a fix cannot be allowed to do that.

Needs the disposable PostgreSQL (``SESSION_TEST_DATABASE_URL``); skipped without it. No Google call is
made: building the authorization URL is local.
"""

# ruff: noqa: F811  (fixtures are imported by name and then requested as arguments)
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.config import Settings
from app.db.models.oauth_pending_state import OAuthPendingState
from app.services.google_session_auth_service import GoogleAuthIntent, GoogleSessionAuthService
from tests.security.conftest import (
    pg_engine,  # noqa: F401  # pyright: ignore[reportUnusedImport]  (pytest fixture, by name)
    settings,  # noqa: F401  # pyright: ignore[reportUnusedImport]  (pytest fixture, by name)
)
from tests.security.test_google_session_postgres import (
    login_settings,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    oauth_engine,  # noqa: F401  # pyright: ignore[reportUnusedImport]
)


async def _start_login(factory: async_sessionmaker, login_settings: Settings) -> None:
    async with factory() as db:
        await GoogleSessionAuthService(db, login_settings).start(GoogleAuthIntent.LOGIN, None)


async def _count(factory: async_sessionmaker, *, expired: bool) -> int:
    now = datetime.now(UTC)
    condition = (
        OAuthPendingState.expires_at < now if expired else OAuthPendingState.expires_at >= now
    )
    async with factory() as db:
        return int(
            await db.scalar(select(func.count()).select_from(OAuthPendingState).where(condition))
            or 0
        )


async def test_expired_unfinished_login_attempts_are_removed_when_a_new_login_starts(
    oauth_engine: AsyncEngine,
    login_settings: Settings,
) -> None:
    factory = async_sessionmaker(oauth_engine, expire_on_commit=False)
    for _ in range(3):
        await _start_login(factory, login_settings)
    async with factory.begin() as db:  # the ten minutes pass, nobody finishes the login
        await db.execute(
            update(OAuthPendingState).values(expires_at=datetime.now(UTC) - timedelta(hours=1))
        )
    await _start_login(factory, login_settings)

    assert await _count(factory, expired=False) == 1
    assert await _count(factory, expired=True) == 0, (
        "3 login attempts expired unfinished and are still stored after a new login started"
    )


async def test_starting_a_login_keeps_another_browsers_valid_attempt(
    oauth_engine: AsyncEngine,
    login_settings: Settings,
) -> None:
    factory = async_sessionmaker(oauth_engine, expire_on_commit=False)
    await _start_login(factory, login_settings)
    await _start_login(factory, login_settings)
    assert await _count(factory, expired=False) == 2
