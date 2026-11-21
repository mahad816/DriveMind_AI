"""M0-SEC ticket 07 (KI-032): expired login states are pruned and the login start is rate limited.

Limiter tests need no database. Prune, HTTP and failure tests need the disposable PostgreSQL
(``SESSION_TEST_DATABASE_URL``) and skip without it. No Google call is made: building the
authorization URL is local, and the one end-to-end login stubs the token verification.
"""

# ruff: noqa: F811  (fixtures are imported by name and then requested as arguments)
import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.api.google_session_auth import get_login_start_limiter, router
from app.core.config import Settings, get_settings
from app.db.models.oauth_pending_state import OAuthPendingState
from app.db.session import get_db
from app.security.login_start_limit import LoginStartLimiter, login_start_limiter
from app.security.session_helpers import SessionStoreUnavailable
from app.services.google_session_auth_service import (
    _PRUNE_BATCH,
    GoogleAuthIntent,
    GoogleLoginRejected,
    GoogleSessionAuthService,
)
from tests.security.conftest import (
    pg_engine,  # noqa: F401  # pyright: ignore[reportUnusedImport]  (pytest fixture, by name)
    settings,  # noqa: F401  # pyright: ignore[reportUnusedImport]  (pytest fixture, by name)
)
from tests.security.test_google_session_postgres import (
    begin,
    login_settings,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    oauth_engine,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    verified,
)

# ---------------------------------------------------------------- limiter (no database)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _limited(limit: int = 3, window: int = 60) -> Settings:
    return Settings(
        google_login_start_rate_limit=limit, google_login_start_rate_window_seconds=window
    )


def _retry_after(limiter: LoginStartLimiter, config: Settings) -> int:
    with pytest.raises(HTTPException) as caught:
        limiter.admit(config)
    assert caught.value.status_code == 429
    assert caught.value.headers is not None
    return int(caught.value.headers["Retry-After"])


def test_limiter_admits_up_to_the_limit_then_rejects_with_a_retry_hint() -> None:
    clock, config = Clock(), _limited(limit=3, window=60)
    limiter = LoginStartLimiter(clock)
    for _ in range(3):
        limiter.admit(config)
    clock.now += 20
    assert _retry_after(limiter, config) == 40  # the oldest admission leaves the window in 40 s


def test_limiter_recovers_after_the_window_and_rejections_do_not_extend_it() -> None:
    clock, config = Clock(), _limited(limit=2, window=60)
    limiter = LoginStartLimiter(clock)
    limiter.admit(config)
    limiter.admit(config)
    for _ in range(50):  # a flood while limited records nothing
        clock.now += 1
        with pytest.raises(HTTPException):
            limiter.admit(config)
    clock.now = 1000.0 + 60  # exactly one window after the first two
    limiter.admit(config)
    limiter.admit(config)


def test_limiter_retry_hint_is_at_least_one_second() -> None:
    clock, config = Clock(), _limited(limit=1, window=60)
    limiter = LoginStartLimiter(clock)
    limiter.admit(config)
    clock.now += 59.9
    assert _retry_after(limiter, config) == 1


def test_a_flood_admits_exactly_the_limit_and_recovers_afterwards() -> None:
    clock, config = Clock(), _limited(limit=5, window=60)
    limiter = LoginStartLimiter(clock)
    admitted = 0
    for _ in range(1000):
        try:
            limiter.admit(config)
            admitted += 1
        except HTTPException:
            pass
    assert admitted == 5
    clock.now += 60
    limiter.admit(config)


def test_settings_defaults_are_generous_and_bounded() -> None:
    config = Settings()
    assert config.google_login_start_rate_limit == 30
    assert config.google_login_start_rate_window_seconds == 60
    for bad in (0, -1, 10001):
        with pytest.raises(ValueError):
            Settings(google_login_start_rate_limit=bad)
    with pytest.raises(ValueError):
        Settings(google_login_start_rate_window_seconds=0)


# ---------------------------------------------------------------- prune (PostgreSQL)


async def _rows(factory: async_sessionmaker) -> list[OAuthPendingState]:
    async with factory() as db:
        return list((await db.scalars(select(OAuthPendingState))).all())


async def _expire(factory: async_sessionmaker, *, only: set[str] | None = None) -> None:
    async with factory.begin() as db:
        stmt = update(OAuthPendingState).values(expires_at=datetime.now(UTC) - timedelta(hours=1))
        if only is not None:
            stmt = stmt.where(OAuthPendingState.state.in_(only))
        await db.execute(stmt)


async def _start(factory: async_sessionmaker, config: Settings, intent=GoogleAuthIntent.LOGIN):
    async with factory() as db:
        return await GoogleSessionAuthService(db, config).start(intent, None)


async def test_start_removes_only_expired_rows_and_keeps_the_new_and_valid_ones(
    oauth_engine: AsyncEngine, login_settings: Settings
) -> None:
    factory = async_sessionmaker(oauth_engine, expire_on_commit=False)
    for _ in range(4):
        await _start(factory, login_settings)
    states = [row.state for row in await _rows(factory)]
    stale, valid = set(states[:3]), states[3]
    await _expire(factory, only=stale)

    await _start(factory, login_settings)

    remaining = {row.state for row in await _rows(factory)}
    assert valid in remaining and not (remaining & stale) and len(remaining) == 2


async def test_pruned_state_can_never_complete_and_unexpired_state_still_can(
    oauth_engine: AsyncEngine, login_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    verified(monkeypatch)
    factory = async_sessionmaker(oauth_engine, expire_on_commit=False)
    async with factory() as db:
        expired_state, expired_binding = await begin(GoogleSessionAuthService(db, login_settings))
    async with factory() as db:
        valid_state, valid_binding = await begin(GoogleSessionAuthService(db, login_settings))
    await _expire(factory, only={expired_state})
    await _start(factory, login_settings)  # prunes the expired attempt
    assert expired_state not in {row.state for row in await _rows(factory)}

    async with factory() as db:  # replay of the pruned (and expired) attempt is rejected
        with pytest.raises(GoogleLoginRejected):
            await GoogleSessionAuthService(db, login_settings).callback(
                code="code", state=expired_state, binding=expired_binding, credential=None
            )
    async with factory() as db:  # the other browser's valid attempt still completes, once
        issued = await GoogleSessionAuthService(db, login_settings).callback(
            code="code", state=valid_state, binding=valid_binding, credential=None
        )
        assert issued.credential
    async with factory() as db:
        with pytest.raises(GoogleLoginRejected):  # consumed: replay fails
            await GoogleSessionAuthService(db, login_settings).callback(
                code="code", state=valid_state, binding=valid_binding, credential=None
            )


async def test_prune_also_removes_expired_legacy_rows_and_is_batch_bounded(
    oauth_engine: AsyncEngine, login_settings: Settings
) -> None:
    factory = async_sessionmaker(oauth_engine, expire_on_commit=False)
    past = datetime.now(UTC) - timedelta(hours=1)
    async with factory.begin() as db:
        db.add_all(
            OAuthPendingState(state=f"legacy-{index}", code_verifier="v", expires_at=past)
            for index in range(_PRUNE_BATCH + 20)
        )
    await _start(factory, login_settings)
    # One batch is removed per start; the backlog drains over several logins.
    assert len(await _rows(factory)) == 20 + 1
    await _start(factory, login_settings)
    assert len(await _rows(factory)) == 2


async def test_concurrent_starts_neither_deadlock_nor_lose_rows(
    oauth_engine: AsyncEngine, login_settings: Settings
) -> None:
    factory = async_sessionmaker(oauth_engine, expire_on_commit=False)
    past = datetime.now(UTC) - timedelta(hours=1)
    async with factory.begin() as db:
        db.add_all(
            OAuthPendingState(state=f"old-{index}", code_verifier="v", expires_at=past)
            for index in range(200)
        )
    await asyncio.wait_for(
        asyncio.gather(*(_start(factory, login_settings) for _ in range(12))), timeout=30
    )
    rows = await _rows(factory)
    assert len(rows) == 12 and all(row.expires_at > datetime.now(UTC) for row in rows)


async def test_prune_failure_stores_nothing_and_reports_unavailable(
    oauth_engine: AsyncEngine, login_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = async_sessionmaker(oauth_engine, expire_on_commit=False)
    await _start(factory, login_settings)
    before = {row.state for row in await _rows(factory)}

    async def broken(self: GoogleSessionAuthService, now: datetime) -> None:
        raise OperationalError("DELETE", {}, Exception("synthetic"))

    monkeypatch.setattr(GoogleSessionAuthService, "_prune_expired_states", broken)
    async with factory() as db:
        with pytest.raises(SessionStoreUnavailable):
            await GoogleSessionAuthService(db, login_settings).start(GoogleAuthIntent.LOGIN, None)
    assert {row.state for row in await _rows(factory)} == before


# ---------------------------------------------------------------- HTTP (PostgreSQL)


def _app(factory: async_sessionmaker, config: Settings, limiter: LoginStartLimiter) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    async def database():
        async with factory() as db:
            yield db

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_settings] = lambda: config
    app.dependency_overrides[get_login_start_limiter] = lambda: limiter
    return app


async def _count(factory: async_sessionmaker) -> int:
    async with factory() as db:
        return int(await db.scalar(select(func.count()).select_from(OAuthPendingState)) or 0)


async def test_over_the_limit_gets_429_writes_no_row_and_recovers_after_the_window(
    oauth_engine: AsyncEngine, login_settings: Settings
) -> None:
    login_settings.google_login_start_rate_limit = 3
    clock = Clock()
    limiter = LoginStartLimiter(clock)
    factory = async_sessionmaker(oauth_engine, expire_on_commit=False)
    headers = {"Origin": login_settings.frontend_url, "X-DriveMind-Auth": "1"}
    async with AsyncClient(
        transport=ASGITransport(app=_app(factory, login_settings, limiter)),
        base_url=login_settings.frontend_url,
    ) as client:

        async def start():
            return await client.post(
                "/api/v1/auth/session/google", json={"intent": "LOGIN"}, headers=headers
            )

        for _ in range(3):
            assert (await start()).status_code == 200
        assert await _count(factory) == 3
        for _ in range(5):
            limited = await start()
            assert limited.status_code == 429
            assert int(limited.headers["retry-after"]) >= 1
            assert "set-cookie" not in limited.headers
        assert await _count(factory) == 3  # no row written while limited
        clock.now += 61
        assert (await start()).status_code == 200
        assert await _count(factory) == 4


async def test_requests_that_fail_origin_or_header_checks_do_not_use_the_budget(
    oauth_engine: AsyncEngine, login_settings: Settings
) -> None:
    login_settings.google_login_start_rate_limit = 1
    limiter = LoginStartLimiter(Clock())
    factory = async_sessionmaker(oauth_engine, expire_on_commit=False)
    async with AsyncClient(
        transport=ASGITransport(app=_app(factory, login_settings, limiter)),
        base_url=login_settings.frontend_url,
    ) as client:
        for _ in range(5):
            bad = await client.post("/api/v1/auth/session/google", json={"intent": "LOGIN"})
            assert bad.status_code == 403
        ok = await client.post(
            "/api/v1/auth/session/google",
            json={"intent": "LOGIN"},
            headers={"Origin": login_settings.frontend_url, "X-DriveMind-Auth": "1"},
        )
        assert ok.status_code == 200


async def test_unchanged_statuses_flag_off_demo_and_unconfigured_even_when_limited(
    oauth_engine: AsyncEngine, login_settings: Settings
) -> None:
    login_settings.google_login_start_rate_limit = 1
    limiter = LoginStartLimiter(Clock())
    limiter.admit(login_settings)  # the window is already full
    factory = async_sessionmaker(oauth_engine, expire_on_commit=False)
    headers = {"Origin": login_settings.frontend_url, "X-DriveMind-Auth": "1"}
    async with AsyncClient(
        transport=ASGITransport(app=_app(factory, login_settings, limiter)),
        base_url=login_settings.frontend_url,
    ) as client:

        async def status() -> int:
            return (
                await client.post(
                    "/api/v1/auth/session/google", json={"intent": "LOGIN"}, headers=headers
                )
            ).status_code

        login_settings.google_application_sessions_enabled = False
        assert await status() == 404
        login_settings.google_application_sessions_enabled = True
        login_settings.demo_mode = True
        assert await status() == 403
        login_settings.demo_mode = False
        login_settings.google_client_secret = ""
        assert await status() == 503
        login_settings.google_client_secret = "synthetic-client-secret"
        assert await status() == 429  # configured and enabled: only now does the limit speak


async def test_refused_connect_drive_does_not_use_the_login_budget(
    oauth_engine: AsyncEngine, login_settings: Settings
) -> None:
    login_settings.google_login_start_rate_limit = 1
    limiter = LoginStartLimiter(Clock())
    factory = async_sessionmaker(oauth_engine, expire_on_commit=False)
    headers = {"Origin": login_settings.frontend_url, "X-DriveMind-Auth": "1"}
    async with AsyncClient(
        transport=ASGITransport(app=_app(factory, login_settings, limiter)),
        base_url=login_settings.frontend_url,
    ) as client:
        # Unauthenticated CONNECT_DRIVE is refused (401/403) by its own checks and records nothing.
        for _ in range(3):
            refused = await client.post(
                "/api/v1/auth/session/google", json={"intent": "CONNECT_DRIVE"}, headers=headers
            )
            assert refused.status_code in {401, 403}
        ok = await client.post(
            "/api/v1/auth/session/google", json={"intent": "LOGIN"}, headers=headers
        )
        assert ok.status_code == 200


def test_the_real_dependency_is_the_process_wide_limiter() -> None:
    assert get_login_start_limiter() is login_start_limiter
