"""Real PostgreSQL callback transactions, replay races, cookies and migration tests."""

import asyncio
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from google.oauth2.credentials import Credentials
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.api.google_session_auth import router
from app.core.config import Settings, get_settings
from app.db.models.application_session import ApplicationSession
from app.db.models.google_oauth_token import GoogleOAuthToken
from app.db.models.oauth_pending_state import OAuthPendingState
from app.db.models.user import User
from app.db.session import get_db
from app.security.principal import VerifiedGoogleIdentity
from app.security.session_helpers import (
    InvalidApplicationSession,
    SessionStoreUnavailable,
    encode_token,
)
from app.services.application_session_service import ApplicationSessionService
from app.services.google_oauth_service import GoogleOAuthService
from app.services.google_credential_repository import GoogleCredentialRepository
from tests.credential_fixtures import configure_test_keys, synthetic_oauth_row, secret_value
from app.services.google_session_auth_service import (
    GoogleAuthIntent,
    GoogleLoginRejected,
    GoogleSessionAuthService,
)
from .conftest import USER_A, USER_B, apply_revision
from .test_google_session_auth import install_token_response, oidc

__all__ = ["oidc"]

REVISION = "20261009_1300"


@pytest.fixture
async def oauth_engine(pg_engine: AsyncEngine):
    async with pg_engine.begin() as connection:
        await connection.run_sync(apply_revision, REVISION)
        await connection.run_sync(apply_revision, "20261010_1200")
        await connection.run_sync(apply_revision, "20261011_1200")
    return pg_engine


@pytest.fixture
def login_settings(settings: Settings) -> Settings:
    settings.google_application_sessions_enabled = True
    settings.google_session_redirect_uri = (
        settings.frontend_url + "/api/v1/auth/session/google/callback"
    )
    settings.google_client_id = "synthetic-client"
    settings.google_client_secret = "synthetic-client-secret"
    return configure_test_keys(settings)


async def begin(service: GoogleSessionAuthService, intent=GoogleAuthIntent.LOGIN, credential=None):
    started = await service.start(intent, credential)
    state = parse_qs(urlsplit(started.authorization_url).query)["state"][0]
    return state, started.browser_binding.get_secret_value()


def verified(
    monkeypatch: pytest.MonkeyPatch, subject="verified-subject-a", email="a@example.invalid"
):
    credentials = Credentials(token="synthetic-new-access", scopes=["openid"], refresh_token=None)
    monkeypatch.setattr(
        GoogleSessionAuthService,
        "_exchange_and_verify",
        lambda self, code, pending: (credentials, VerifiedGoogleIdentity(subject), email),
    )
    return credentials


async def test_existing_and_new_login_do_not_write_drive_tokens(
    oauth_engine: AsyncEngine,
    login_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
):
    sessions = async_sessionmaker(oauth_engine, expire_on_commit=False)
    async with sessions() as db:
        for subject, email in (
            ("verified-subject-a", "a@example.invalid"),
            ("new-verified-subject", "new@example.invalid"),
        ):
            verified(monkeypatch, subject, email)
            service = GoogleSessionAuthService(db, login_settings)
            state, binding = await begin(service)
            issued = await service.callback(
                code="code", state=state, binding=binding, credential=None
            )
            principal = await ApplicationSessionService(db, login_settings).resolve_principal(
                issued.credential.get_secret_value()
            )
            assert (
                await db.scalar(select(User.google_id).where(User.id == principal.corpus_user_id))
                == subject
            )
            assert issued.credential.get_secret_value() not in repr(issued)
            assert await db.scalar(select(func.count()).select_from(GoogleOAuthToken)) == 0
            assert await db.scalar(select(func.count()).select_from(OAuthPendingState)) == 0


async def test_binding_expiry_replay_and_legacy_boundary(
    oauth_engine: AsyncEngine,
    login_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
):
    verified(monkeypatch)
    async with async_sessionmaker(oauth_engine)() as db:
        service = GoogleSessionAuthService(db, login_settings)
        state, binding = await begin(service)
        for wrong in (None, encode_token(b"x" * 32)):
            with pytest.raises(GoogleLoginRejected):
                await service.callback(code="code", state=state, binding=wrong, credential=None)
        with pytest.raises(ValueError):
            await GoogleOAuthService(db, login_settings)._pop_code_verifier(state)
        await service.callback(code="code", state=state, binding=binding, credential=None)
        with pytest.raises(GoogleLoginRejected):
            await service.callback(code="code", state=state, binding=binding, credential=None)
        state, binding = await begin(service)
        await db.execute(
            update(OAuthPendingState)
            .where(OAuthPendingState.state == state)
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await db.commit()
        with pytest.raises(GoogleLoginRejected):
            await service.callback(code="code", state=state, binding=binding, credential=None)
        assert await db.scalar(select(func.count()).select_from(ApplicationSession)) == 1


async def test_concurrent_callbacks_only_one_succeeds(
    oauth_engine: AsyncEngine,
    login_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
):
    verified(monkeypatch)
    sessions = async_sessionmaker(oauth_engine)
    async with sessions() as db:
        state, binding = await begin(GoogleSessionAuthService(db, login_settings))

    async def callback():
        async with sessions() as db:
            try:
                await GoogleSessionAuthService(db, login_settings).callback(
                    code="code", state=state, binding=binding, credential=None
                )
                return "success"
            except GoogleLoginRejected:
                return "rejected"

    assert sorted(await asyncio.gather(callback(), callback())) == ["rejected", "success"]
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ApplicationSession)) == 1


async def test_connect_subject_mismatch_rotation_and_refresh_preservation(
    oauth_engine: AsyncEngine,
    login_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
):
    sessions = async_sessionmaker(oauth_engine, expire_on_commit=False)
    async with sessions() as db:
        sessions_service = ApplicationSessionService(db, login_settings)
        old = await sessions_service.issue_google(VerifiedGoogleIdentity("verified-subject-a"))
        db.add(
            synthetic_oauth_row(
                user_id=USER_A,
                access_token="synthetic-old-access",
                refresh_token="synthetic-refresh",
                scopes=login_settings.google_drive_scopes,
            )
        )
        await db.commit()
        token = old.credential.get_secret_value()
        service = GoogleSessionAuthService(db, login_settings)
        state, binding = await begin(service, GoogleAuthIntent.CONNECT_DRIVE, token)
        verified(monkeypatch, "verified-subject-b", "b@example.invalid")
        with pytest.raises(GoogleLoginRejected):
            await service.callback(code="code", state=state, binding=binding, credential=token)
        assert (await sessions_service.resolve_principal(token)).authenticated_user_id == USER_A
        assert (
            secret_value(
                (
                    await GoogleCredentialRepository(db, login_settings).load_encrypted(USER_A)
                ).payload.access_token
            )
            == "synthetic-old-access"
        )
        state, binding = await begin(service, GoogleAuthIntent.CONNECT_DRIVE, token)
        verified(monkeypatch)
        new = await service.callback(code="code", state=state, binding=binding, credential=token)
        with pytest.raises(InvalidApplicationSession):
            await sessions_service.resolve_principal(token)
        assert (
            await sessions_service.resolve_principal(new.credential.get_secret_value())
        ).authenticated_user_id == USER_A
        assert (
            secret_value(
                (
                    await GoogleCredentialRepository(db, login_settings).load_encrypted(USER_A)
                ).payload.refresh_token
            )
            == "synthetic-refresh"
        )
        assert (
            await db.scalar(
                select(func.count())
                .select_from(GoogleOAuthToken)
                .where(GoogleOAuthToken.user_id == USER_B)
            )
            == 0
        )


async def test_failed_verification_and_final_commit_roll_back(
    oauth_engine: AsyncEngine,
    login_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
):
    sessions = async_sessionmaker(oauth_engine)
    async with sessions() as db:
        service = GoogleSessionAuthService(db, login_settings)
        state, binding = await begin(service)

        def reject(*args):
            raise GoogleLoginRejected()

        monkeypatch.setattr(service, "_exchange_and_verify", reject)
        with pytest.raises(GoogleLoginRejected):
            await service.callback(code="code", state=state, binding=binding, credential=None)
        assert await db.scalar(select(func.count()).select_from(ApplicationSession)) == 0
        state, binding = await begin(service)
        verified(monkeypatch, "new-subject", "new@example.invalid")
        monkeypatch.delattr(service, "_exchange_and_verify")
        original_commit = db.commit
        calls = 0

        async def fail_final():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise SQLAlchemyError("synthetic database failure")
            await original_commit()

        monkeypatch.setattr(db, "commit", fail_final)
        with pytest.raises(SessionStoreUnavailable):
            await service.callback(code="code", state=state, binding=binding, credential=None)
        assert await db.scalar(select(func.count()).select_from(ApplicationSession)) == 0
        assert await db.scalar(select(User.id).where(User.google_id == "new-subject")) is None


async def test_migration_legacy_rows_constraints_and_roundtrip(oauth_engine: AsyncEngine):
    async with oauth_engine.begin() as connection:
        await connection.execute(
            insert(OAuthPendingState).values(
                state="legacy",
                code_verifier="legacy-verifier",
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
            )
        )
        await connection.execute(
            insert(OAuthPendingState).values(
                state="secure-before-rollback",
                code_verifier="secure-verifier",
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
                browser_binding_hash=b"x" * 32,
                nonce="n" * 43,
                intent="LOGIN",
            )
        )
        await connection.run_sync(apply_revision, REVISION, downgrade=True)
        await connection.run_sync(apply_revision, REVISION)
        assert (
            await connection.scalar(
                select(OAuthPendingState.state).where(
                    OAuthPendingState.state == "secure-before-rollback"
                )
            )
            is None
        )
        assert (
            await connection.scalar(
                select(OAuthPendingState.code_verifier).where(OAuthPendingState.state == "legacy")
            )
            == "legacy-verifier"
        )
    for invalid in (
        {"intent": "LOGIN"},
        {"browser_binding_hash": b"short", "nonce": "a" * 43, "intent": "LOGIN"},
        {"browser_binding_hash": b"x" * 32, "nonce": "a" * 43, "intent": "CONNECT_DRIVE"},
    ):
        with pytest.raises(IntegrityError):
            async with oauth_engine.begin() as connection:
                await connection.execute(
                    insert(OAuthPendingState).values(
                        state="invalid",
                        code_verifier="pkce",
                        expires_at=datetime.now(UTC) + timedelta(minutes=10),
                        **invalid,
                    )
                )


async def test_http_lifecycle_cookies_csrf_gate_and_no_bearer_json(
    oauth_engine: AsyncEngine,
    login_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
):
    verified(monkeypatch)
    sessions = async_sessionmaker(oauth_engine)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    async def database():
        async with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_settings] = lambda: login_settings
    headers = {"Origin": login_settings.frontend_url, "X-DriveMind-Auth": "1"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=login_settings.frontend_url
    ) as client:
        login_settings.google_application_sessions_enabled = False
        assert (
            await client.post(
                "/api/v1/auth/session/google", json={"intent": "LOGIN"}, headers=headers
            )
        ).status_code == 404
        login_settings.google_application_sessions_enabled = True
        login_settings.demo_mode = True
        assert (
            await client.post(
                "/api/v1/auth/session/google", json={"intent": "LOGIN"}, headers=headers
            )
        ).status_code == 403
        login_settings.demo_mode = False
        assert (
            await client.post("/api/v1/auth/session/google", json={"intent": "LOGIN"})
        ).status_code == 403
        assert (
            await client.post(
                "/api/v1/auth/session/google",
                json={"intent": "LOGIN", "user_id": str(USER_B)},
                headers=headers,
            )
        ).status_code == 422
        started = await client.post(
            "/api/v1/auth/session/google", json={"intent": "LOGIN"}, headers=headers
        )
        assert started.status_code == 200 and started.headers["cache-control"] == "no-store"
        state = parse_qs(urlsplit(started.json()["authorization_url"]).query)["state"][0]
        completed = await client.get(
            "/api/v1/auth/session/google/callback", params={"code": "code", "state": state}
        )
        assert completed.status_code == 303
        credential = client.cookies.get("__Host-drivemind-session")
        assert credential and credential not in completed.text
        cookie = completed.headers.get_list("set-cookie")[0]
        assert (
            "HttpOnly" in cookie
            and "Secure" in cookie
            and "SameSite=lax" in cookie
            and "Path=/" in cookie
            and "Domain=" not in cookie
        )
        inspected = await client.get("/api/v1/auth/session")
        assert inspected.status_code == 200 and inspected.json()["user_id"] == str(USER_A)
        assert credential not in inspected.text
        assert (
            await client.post(
                "/api/v1/auth/session/logout", headers={"Origin": login_settings.frontend_url}
            )
        ).status_code == 403
        logged_out = await client.post(
            "/api/v1/auth/session/logout",
            headers={
                "Origin": login_settings.frontend_url,
                "X-CSRF-Token": inspected.json()["csrf_token"],
            },
        )
        assert logged_out.status_code == 204 and "Max-Age=0" in logged_out.headers["set-cookie"]
        assert (await client.get("/api/v1/auth/session")).status_code == 401
        client.cookies.set("__Host-drivemind-session", credential)
        assert (await client.get("/api/v1/auth/session")).status_code == 401


async def test_login_rotation_browser_account_change_and_logout_during_login(
    oauth_engine: AsyncEngine,
    login_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
):
    verified(monkeypatch)
    async with async_sessionmaker(oauth_engine, expire_on_commit=False)() as db:
        sessions = ApplicationSessionService(db, login_settings)
        old = await sessions.issue_google(VerifiedGoogleIdentity("verified-subject-a"))
        other = await sessions.issue_google(VerifiedGoogleIdentity("verified-subject-b"))
        await db.commit()
        token = old.credential.get_secret_value()
        service = GoogleSessionAuthService(db, login_settings)
        state, binding = await begin(service, credential=token)
        with pytest.raises(GoogleLoginRejected):
            await service.callback(
                code="code",
                state=state,
                binding=binding,
                credential=other.credential.get_secret_value(),
            )
        state, binding = await begin(service, credential=token)
        new = await service.callback(code="code", state=state, binding=binding, credential=token)
        with pytest.raises(InvalidApplicationSession):
            await sessions.resolve_principal(token)
        current = new.credential.get_secret_value()
        state, binding = await begin(service, credential=current)
        await sessions.revoke(current)
        await db.commit()
        with pytest.raises(GoogleLoginRejected):
            await service.callback(code="code", state=state, binding=binding, credential=current)
        assert await db.scalar(select(func.count()).select_from(ApplicationSession)) == 3


async def test_callback_cancellation_does_not_persist_session(
    oauth_engine: AsyncEngine,
    login_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
):
    import threading

    started, release = threading.Event(), threading.Event()

    def exchange(*args):
        started.set()
        release.wait(timeout=3)
        raise GoogleLoginRejected()

    async with async_sessionmaker(oauth_engine)() as db:
        service = GoogleSessionAuthService(db, login_settings)
        state, binding = await begin(service)
        monkeypatch.setattr(service, "_exchange_and_verify", exchange)
        task = asyncio.create_task(
            service.callback(code="code", state=state, binding=binding, credential=None)
        )
        try:
            assert await asyncio.to_thread(started.wait, 3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            release.set()
        assert await db.scalar(select(func.count()).select_from(ApplicationSession)) == 0
        assert await db.scalar(select(func.count()).select_from(OAuthPendingState)) == 0


async def test_http_commit_failure_sets_no_application_cookie(
    oauth_engine: AsyncEngine,
    login_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
):
    from app.api.google_session_auth import get_google_session_service

    verified(monkeypatch, "new-subject", "new@example.invalid")
    async with async_sessionmaker(oauth_engine)() as db:
        service = GoogleSessionAuthService(db, login_settings)
        state, binding = await begin(service)
        original_commit = db.commit
        calls = 0

        async def commit():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise SQLAlchemyError("synthetic secret-bearing provider/database failure")
            await original_commit()

        monkeypatch.setattr(db, "commit", commit)
        app = FastAPI()
        app.include_router(router, prefix="/api/v1")
        app.dependency_overrides[get_settings] = lambda: login_settings
        app.dependency_overrides[get_google_session_service] = lambda: service
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url=login_settings.frontend_url
        ) as client:
            client.cookies.set("__Host-drivemind-session-oauth", binding)
            response = await client.get(
                "/api/v1/auth/session/google/callback", params={"code": "code", "state": state}
            )
            assert response.status_code == 503
            assert "secret-bearing" not in response.text and "new-subject" not in response.text
            assert all(
                not value.startswith("__Host-drivemind-session=")
                for value in response.headers.get_list("set-cookie")
            )
            assert await db.scalar(select(User.id).where(User.google_id == "new-subject")) is None
            assert await db.scalar(select(func.count()).select_from(ApplicationSession)) == 0


async def test_authorization_protocol_and_connect_requires_verified_session(
    oauth_engine: AsyncEngine,
    login_settings: Settings,
):
    import hashlib
    from app.security.session_helpers import credential_digest

    async with async_sessionmaker(oauth_engine)() as db:
        service = GoogleSessionAuthService(db, login_settings)
        with pytest.raises(InvalidApplicationSession):
            await begin(service, GoogleAuthIntent.CONNECT_DRIVE)
        started = await service.start(GoogleAuthIntent.LOGIN, None)
        query = parse_qs(urlsplit(started.authorization_url).query)
        row = await db.scalar(
            select(OAuthPendingState).where(OAuthPendingState.state == query["state"][0])
        )
        assert row is not None and row.nonce == query["nonce"][0]
        assert row.browser_binding_hash == credential_digest(
            started.browser_binding.get_secret_value()
        )
        assert query["code_challenge_method"] == ["S256"]
        assert query["code_challenge"] == [
            encode_token(hashlib.sha256(row.code_verifier.encode()).digest())
        ]
        assert "drive.readonly" not in query["scope"][0]
        assert query["redirect_uri"] == [login_settings.google_session_redirect_uri]
        assert row.code_verifier not in started.authorization_url
        issued = await ApplicationSessionService(db, login_settings).issue_google(
            VerifiedGoogleIdentity("verified-subject-a")
        )
        await db.commit()
        started = await service.start(
            GoogleAuthIntent.CONNECT_DRIVE, issued.credential.get_secret_value()
        )
        query = parse_qs(urlsplit(started.authorization_url).query)
        assert login_settings.google_drive_scopes in query["scope"][0]
        assert query["access_type"] == ["offline"]
        assert query["include_granted_scopes"] == ["true"]


async def test_timeout_is_safe_and_does_not_issue_session(
    oauth_engine: AsyncEngine,
    login_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
):
    async with async_sessionmaker(oauth_engine)() as db:
        service = GoogleSessionAuthService(db, login_settings)
        state, binding = await begin(service)

        def timeout(*args):
            raise TimeoutError("synthetic transport detail")

        monkeypatch.setattr(service, "_exchange_and_verify", timeout)
        with pytest.raises(GoogleLoginRejected) as failure:
            await service.callback(code="code", state=state, binding=binding, credential=None)
        assert "transport detail" not in str(failure.value)
        assert await db.scalar(select(func.count()).select_from(ApplicationSession)) == 0
        assert await db.scalar(select(func.count()).select_from(OAuthPendingState)) == 0


async def test_retired_routes_preserve_grants_and_legacy_state(
    oauth_engine: AsyncEngine, login_settings: Settings, monkeypatch: pytest.MonkeyPatch
):
    """Actual application routing cannot consume old state or write credentials."""
    from app.main import create_app

    sessions = async_sessionmaker(oauth_engine, expire_on_commit=False)
    async with sessions() as db:
        db.add(synthetic_oauth_row(user_id=USER_A, scopes=login_settings.google_drive_scopes))
        db.add(
            OAuthPendingState(
                state="retired-legacy-state",
                code_verifier="synthetic-pkce",
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
            )
        )
        await db.commit()

    async def snapshot():
        async with sessions() as db:
            return (
                (await db.execute(select(GoogleOAuthToken.__table__))).all(),
                (await db.execute(select(OAuthPendingState.__table__))).all(),
                (await db.execute(select(User.__table__))).all(),
                (await db.execute(select(ApplicationSession.__table__))).all(),
            )

    before = await snapshot()
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: login_settings

    async def database():
        async with sessions() as db:
            yield db

    application.dependency_overrides[get_db] = database

    # Any accidental route remount would be caught without contacting Google.
    def forbidden_exchange(*args, **kwargs):
        raise AssertionError("Retired routes must not call Google")

    monkeypatch.setattr(GoogleOAuthService, "_fetch_credentials", forbidden_exchange)
    monkeypatch.setattr(GoogleOAuthService, "_build_flow", forbidden_exchange)
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url=login_settings.frontend_url
    ) as client:
        for demo in (False, True):
            login_settings.demo_mode = demo
            for path in ("/auth/google", "/auth/google/callback"):
                response = await client.get(
                    "/api/v1" + path,
                    params={"code": "synthetic-code", "state": "retired-legacy-state"},
                    follow_redirects=False,
                )
                assert response.status_code == 404
                assert "location" not in response.headers and "set-cookie" not in response.headers
    assert await snapshot() == before


@pytest.mark.parametrize("subject", ["verified-subject-a", "verified-subject-b"])
async def test_connect_real_scope_parser_and_encrypted_owner_grant(
    oauth_engine, login_settings, oidc, monkeypatch, subject
):
    sessions = async_sessionmaker(oauth_engine, expire_on_commit=False)
    async with sessions() as db:
        old = await ApplicationSessionService(db, login_settings).issue_google(
            VerifiedGoogleIdentity("verified-subject-a")
        )
        credential = old.credential.get_secret_value()
        csrf = await ApplicationSessionService(db, login_settings).csrf_token(credential)
        other = synthetic_oauth_row(user_id=USER_B, scopes=login_settings.google_drive_scopes)
        db.add(other)
        await db.commit()
        previous_other_envelope = other.encrypted_credentials
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    async def database():
        async with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_settings] = lambda: login_settings
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=login_settings.frontend_url
    ) as client:
        client.cookies.set(
            "__Host-drivemind-session",
            credential,
            domain=urlsplit(login_settings.frontend_url).hostname,
        )
        started = await client.post(
            "/api/v1/auth/session/google",
            json={"intent": "CONNECT_DRIVE"},
            headers={
                "Origin": login_settings.frontend_url,
                "X-DriveMind-Auth": "1",
                "X-CSRF-Token": csrf.get_secret_value(),
            },
        )
        assert started.status_code == 200
        query = parse_qs(urlsplit(started.json()["authorization_url"]).query)
        install_token_response(
            monkeypatch, oidc(sub=subject, nonce=query["nonce"][0]), query["scope"][0]
        )
        monkeypatch.setattr(
            GoogleSessionAuthService,
            "_fetch_google_profile",
            lambda self, creds: {"google_id": subject, "email": "synthetic@example.invalid"},
        )
        callback = await client.get(
            "/api/v1/auth/session/google/callback",
            params={"code": "synthetic-code", "state": query["state"][0]},
        )
        assert callback.status_code == (303 if subject == "verified-subject-a" else 400)
        assert callback.headers["cache-control"] == "no-store"
        assert "synthetic-access" not in str(callback.headers) + callback.text
        assert "synthetic-new-refresh" not in str(callback.headers) + callback.text
        async with sessions() as db:
            assert (
                await db.get(GoogleOAuthToken, other.id)
            ).encrypted_credentials == previous_other_envelope
            assert await db.scalar(select(func.count()).select_from(OAuthPendingState)) == 0
            service = ApplicationSessionService(db, login_settings)
            if subject == "verified-subject-a":
                grant = await GoogleCredentialRepository(db, login_settings).load_encrypted(USER_A)
                assert secret_value(grant.payload.access_token) == "synthetic-access"
                assert secret_value(grant.payload.refresh_token) == "synthetic-new-refresh"
                assert login_settings.google_drive_scopes in grant.record.scopes.split()
                assert (
                    await service.resolve_principal(client.cookies.get("__Host-drivemind-session"))
                ).authenticated_user_id == USER_A
                with pytest.raises(InvalidApplicationSession):
                    await service.resolve_principal(credential)
            else:
                assert await db.scalar(select(func.count()).select_from(GoogleOAuthToken)) == 1
                assert (await service.resolve_principal(credential)).authenticated_user_id == USER_A
