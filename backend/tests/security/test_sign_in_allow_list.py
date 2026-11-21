"""M0-SEC ticket 03: application-level Google sign-in allow-list (synthetic identities only)."""

import logging
from uuid import uuid4

import pytest
from google.oauth2.credentials import Credentials
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.config import Settings, get_settings
from app.db.models.application_session import ApplicationSession
from app.db.models.google_oauth_token import GoogleOAuthToken
from app.db.models.user import User
from app.db.session import get_db
from app.main import create_app
from app.security.allow_list import allowed_sign_in_emails, is_sign_in_allowed
from app.security.principal import VerifiedGoogleIdentity
from app.security.session_helpers import (
    InvalidApplicationSession,
    InvalidSessionRequest,
    session_cookie_policy,
)
from app.services import google_session_auth_service as module
from app.services.application_session_service import ApplicationSessionService
from app.services.google_session_auth_service import (
    GoogleAuthIntent,
    GoogleLoginRejected,
    GoogleSessionAuthService,
)

from .conftest import USER_A
from .test_google_session_postgres import begin, login_settings, oauth_engine, verified

__all__ = ["oauth_engine", "login_settings"]

PREFIX = "/api/v1"
UNLISTED = "stranger@example.invalid"


async def counts(factory) -> tuple[int, int, int]:
    async with factory() as db:
        users = await db.scalar(select(func.count()).select_from(User))
        sessions = await db.scalar(select(func.count()).select_from(ApplicationSession))
        tokens = await db.scalar(select(func.count()).select_from(GoogleOAuthToken))
    return users or 0, sessions or 0, tokens or 0


async def attempt(db, settings, intent=GoogleAuthIntent.LOGIN, credential=None):
    service = GoogleSessionAuthService(db, settings)
    state, binding = await begin(service, intent, credential)
    return await service.callback(code="code", state=state, binding=binding, credential=credential)


# --- The setting itself ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", set()),
        (" , ,", set()),
        ("A@Example.invalid", {"a@example.invalid"}),
        (" a@example.invalid , B@EXAMPLE.invalid,,", {"a@example.invalid", "b@example.invalid"}),
    ],
)
def test_the_list_is_trimmed_case_insensitive_and_ignores_blanks(settings: Settings, raw, expected):
    settings.google_sign_in_allowed_emails = raw
    assert allowed_sign_in_emails(settings) == expected


def test_unset_list_allows_nobody_and_non_strings_never_match(settings: Settings):
    settings.google_sign_in_allowed_emails = ""
    assert not is_sign_in_allowed(settings, "a@example.invalid")
    settings.google_sign_in_allowed_emails = "a@example.invalid"
    assert is_sign_in_allowed(settings, " A@Example.INVALID ")
    assert not is_sign_in_allowed(settings, None)
    assert not is_sign_in_allowed(settings, "")
    assert not is_sign_in_allowed(settings, "a@example.invalid.evil.invalid")


# --- Sign-in -----------------------------------------------------------------------------------


async def test_unlisted_verified_account_gets_nothing_and_is_never_logged(
    oauth_engine: AsyncEngine,
    login_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    factory = async_sessionmaker(oauth_engine, expire_on_commit=False)
    before = await counts(factory)
    verified(monkeypatch, "stranger-subject", UNLISTED)
    caplog.set_level(logging.DEBUG)
    async with factory() as db:
        with pytest.raises(GoogleLoginRejected) as raised:
            await attempt(db, login_settings)
    assert await counts(factory) == before
    assert "stranger" not in str(raised.value) + repr(raised.value) + caplog.text
    async with factory() as db:
        assert await db.scalar(select(User).where(User.google_id == "stranger-subject")) is None


@pytest.mark.parametrize("raw", ["", " , "])
async def test_unset_or_empty_list_refuses_every_sign_in(
    oauth_engine: AsyncEngine,
    login_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
):
    login_settings.google_sign_in_allowed_emails = raw
    factory = async_sessionmaker(oauth_engine, expire_on_commit=False)
    before = await counts(factory)
    verified(monkeypatch)  # a@example.invalid, an existing user
    async with factory() as db:
        with pytest.raises(GoogleLoginRejected):
            await attempt(db, login_settings)
    assert await counts(factory) == before


async def test_listed_account_signs_in_in_any_case_and_a_returning_user_keeps_its_row(
    oauth_engine: AsyncEngine, login_settings: Settings, monkeypatch: pytest.MonkeyPatch
):
    login_settings.google_sign_in_allowed_emails = " A@EXAMPLE.invalid, New@Example.Invalid "
    factory = async_sessionmaker(oauth_engine, expire_on_commit=False)
    async with factory() as db:
        verified(monkeypatch, "verified-subject-a", "A@Example.Invalid")
        issued = await attempt(db, login_settings)
        principal = await ApplicationSessionService(db, login_settings).resolve_principal(
            issued.credential.get_secret_value()
        )
        assert principal.corpus_user_id == USER_A
        verified(monkeypatch, "brand-new-subject", "new@example.invalid")
        created = await attempt(db, login_settings)
        second = await ApplicationSessionService(db, login_settings).resolve_principal(
            created.credential.get_secret_value()
        )
        assert second.corpus_user_id != USER_A


async def test_a_listed_address_with_an_unverified_email_claim_is_still_rejected(
    login_settings: Settings, monkeypatch: pytest.MonkeyPatch
):
    # The allow-list does not replace Google's email_verified check in the token verifier.
    claims = {"sub": "s", "email": "a@example.invalid", "nonce": "n", "email_verified": False}
    monkeypatch.setattr(module.id_token, "verify_oauth2_token", lambda *a, **k: claims)
    with pytest.raises(GoogleLoginRejected):
        module.verify_google_token(Credentials(token="t", id_token="x.y.z"), "n", login_settings)


async def test_drive_connect_of_an_unlisted_account_stores_no_credential(
    oauth_engine: AsyncEngine, login_settings: Settings, monkeypatch: pytest.MonkeyPatch
):
    factory = async_sessionmaker(oauth_engine, expire_on_commit=False)
    async with factory() as db:
        verified(monkeypatch)
        issued = await attempt(db, login_settings)
        credential = issued.credential.get_secret_value()
        service = GoogleSessionAuthService(db, login_settings)
        state, binding = await begin(service, GoogleAuthIntent.CONNECT_DRIVE, credential)
        before = await counts(factory)
        # The Owner removes the address, or Google now reports an unlisted e-mail for the subject.
        verified(monkeypatch, "verified-subject-a", UNLISTED)
        with pytest.raises(GoogleLoginRejected):
            await service.callback(code="code", state=state, binding=binding, credential=credential)
    assert await counts(factory) == before
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(GoogleOAuthToken)) == 0
        assert await db.scalar(select(User.email).where(User.id == USER_A)) == "a@example.invalid"


async def test_a_returning_subject_with_an_unlisted_current_email_is_refused(
    oauth_engine: AsyncEngine, login_settings: Settings, monkeypatch: pytest.MonkeyPatch
):
    factory = async_sessionmaker(oauth_engine, expire_on_commit=False)
    before = await counts(factory)
    verified(monkeypatch, "verified-subject-a", UNLISTED)
    async with factory() as db:
        with pytest.raises(GoogleLoginRejected):
            await attempt(db, login_settings)
    assert await counts(factory) == before
    async with factory() as db:
        assert await db.scalar(select(User.email).where(User.id == USER_A)) == "a@example.invalid"


async def test_login_with_the_cookie_of_a_removed_address_is_refused(
    oauth_engine: AsyncEngine, login_settings: Settings, monkeypatch: pytest.MonkeyPatch
):
    factory = async_sessionmaker(oauth_engine, expire_on_commit=False)
    async with factory() as db:
        verified(monkeypatch)
        issued = await attempt(db, login_settings)
        credential = issued.credential.get_secret_value()
        service = GoogleSessionAuthService(db, login_settings)
        state, binding = await begin(service, GoogleAuthIntent.LOGIN, credential)
        before = await counts(factory)
        login_settings.google_sign_in_allowed_emails = "b@example.invalid"
        with pytest.raises(GoogleLoginRejected):
            await service.callback(code="code", state=state, binding=binding, credential=credential)
    assert await counts(factory) == before


# --- Principal resolution ----------------------------------------------------------------------


@pytest.fixture
async def http(oauth_engine: AsyncEngine, login_settings: Settings, monkeypatch):
    factory = async_sessionmaker(oauth_engine, expire_on_commit=False)
    app = create_app()

    async def database():
        async with factory() as db:
            yield db

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_settings] = lambda: login_settings
    async with factory() as db:
        issued = await ApplicationSessionService(db, login_settings).issue_google(
            VerifiedGoogleIdentity("verified-subject-a")
        )
        await db.commit()
    cookie = session_cookie_policy(login_settings).name
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=login_settings.frontend_url
    ) as client:
        client.cookies.set(cookie, issued.credential.get_secret_value())
        yield client, login_settings, issued, factory
    app.dependency_overrides.clear()


def protected_calls(settings: Settings, csrf: str):
    origin = {"Origin": settings.frontend_url, "X-CSRF-Token": csrf}
    some = uuid4()
    return [
        ("GET", "/auth/session", {}),
        ("GET", "/conversations", {}),
        ("GET", f"/conversations/{some}", {}),
        ("GET", "/files", {}),
        ("GET", "/index/status", {}),
        ("GET", "/index/pending", {}),
        ("GET", f"/sources/{some}", {}),
        ("POST", "/chat", {"headers": origin, "json": {"question": "hi"}}),
        ("POST", "/conversations", {"headers": origin, "json": {}}),
        ("DELETE", f"/conversations/{some}", {"headers": origin}),
        ("POST", "/index/sync", {"headers": origin}),
        ("POST", "/index/ingest", {"headers": origin}),
        ("POST", "/index/chunk", {"headers": origin}),
        ("POST", "/index/build", {"headers": origin}),
    ]


async def test_listed_session_is_accepted_and_removal_is_401_on_every_private_route(http):
    client, settings, issued, _ = http
    csrf = issued.csrf_token.get_secret_value()
    assert (await client.get(PREFIX + "/auth/session")).status_code == 200
    for allowed in ("", " , ", "b@example.invalid"):
        settings.google_sign_in_allowed_emails = allowed
        for method, path, kwargs in protected_calls(settings, csrf):
            response = await client.request(method, PREFIX + path, **kwargs)
            assert response.status_code == 401, (allowed, method, path, response.status_code)


async def test_re_adding_an_address_restores_an_unrevoked_session(http):
    client, settings, *_ = http
    listed = settings.google_sign_in_allowed_emails
    settings.google_sign_in_allowed_emails = ""
    assert (await client.get(PREFIX + "/auth/session")).status_code == 401
    settings.google_sign_in_allowed_emails = listed
    assert (await client.get(PREFIX + "/auth/session")).status_code == 200


async def test_logout_of_a_removed_address_revokes_the_session_for_good(http):
    client, settings, issued, factory = http
    csrf = issued.csrf_token.get_secret_value()
    listed = settings.google_sign_in_allowed_emails
    settings.google_sign_in_allowed_emails = ""
    origin = settings.frontend_url
    url = PREFIX + "/auth/session/logout"
    # Refused as today: no / wrong Origin, no / wrong CSRF token, invalid cookie.
    assert (await client.post(url, headers={"X-CSRF-Token": csrf})).status_code == 403
    assert (
        await client.post(
            url, headers={"Origin": "https://evil.example.invalid", "X-CSRF-Token": csrf}
        )
    ).status_code == 403
    assert (await client.post(url, headers={"Origin": origin})).status_code == 403
    assert (
        await client.post(url, headers={"Origin": origin, "X-CSRF-Token": "AAAA" * 11})
    ).status_code == 403
    async with factory() as db:
        assert await db.scalar(select(ApplicationSession.revoked_at)) is None
    cookie = session_cookie_policy(settings).name
    saved = client.cookies.get(cookie)
    client.cookies.set(cookie, "not-a-session")
    assert (
        await client.post(url, headers={"Origin": origin, "X-CSRF-Token": csrf})
    ).status_code == 401
    client.cookies.set(cookie, saved)
    # Still no protected access while removed.
    assert (await client.get(PREFIX + "/conversations")).status_code == 401
    done = await client.post(url, headers={"Origin": origin, "X-CSRF-Token": csrf})
    assert done.status_code == 204
    async with factory() as db:
        assert await db.scalar(select(ApplicationSession.revoked_at)) is not None
    settings.google_sign_in_allowed_emails = listed
    client.cookies.set(cookie, saved)
    assert (await client.get(PREFIX + "/auth/session")).status_code == 401
    assert (
        await client.post(url, headers={"Origin": origin, "X-CSRF-Token": csrf})
    ).status_code == 401


async def test_logout_authorization_is_never_a_principal_and_skips_only_the_allow_list(
    oauth_engine: AsyncEngine, login_settings: Settings
):
    factory = async_sessionmaker(oauth_engine, expire_on_commit=False)
    async with factory() as db:
        service = ApplicationSessionService(db, login_settings)
        issued = await service.issue_google(VerifiedGoogleIdentity("verified-subject-a"))
        credential, csrf = (
            issued.credential.get_secret_value(),
            issued.csrf_token.get_secret_value(),
        )
        login_settings.google_sign_in_allowed_emails = ""
        assert await service.authorize_logout(credential, csrf) == issued.session_id
        with pytest.raises(InvalidSessionRequest):
            await service.authorize_logout(credential, "AAAA" * 11)
        with pytest.raises(InvalidApplicationSession):
            await service.authorize_logout("bad", csrf)
        for resolve in (
            service.resolve_principal(credential),
            service.verify_csrf(credential, csrf),
            service.csrf_token(credential),
        ):
            with pytest.raises(InvalidApplicationSession):
                await resolve


async def test_demo_mode_sessions_ignore_the_allow_list(
    oauth_engine: AsyncEngine, settings: Settings
):
    settings.demo_mode = True
    settings.google_sign_in_allowed_emails = ""
    factory = async_sessionmaker(oauth_engine, expire_on_commit=False)
    async with factory() as db:
        service = ApplicationSessionService(db, settings)
        issued = await service.issue_demo()
        principal = await service.resolve_principal(issued.credential.get_secret_value())
        assert principal.demo_mode and principal.authenticated_user_id is None
