"""Real migration, constraints, transaction and fresh-authorization tests."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.config import Settings
from app.db.enums import ApplicationSessionKind
from app.db.models.application_session import ApplicationSession
from app.db.models.user import User
from app.security.principal import VerifiedGoogleIdentity
from app.security.session_helpers import (
    InvalidApplicationSession,
    InvalidSessionRequest,
    credential_digest,
    parse_token,
)
from app.services.application_session_service import (
    ApplicationSessionService,
    GOOGLE_SESSION_LIFETIME,
)
from .conftest import USER_A, USER_B, DEMO_USER, SESSION_REVISION, apply_revision


async def test_google_issuance_hashes_secrets_and_preserves_identity(
    pg_engine: AsyncEngine,
    settings: Settings,
) -> None:
    sessions = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with sessions() as db:
        service = ApplicationSessionService(db, settings)
        issued = await service.issue_google(VerifiedGoogleIdentity("verified-subject-a"))
        await db.commit()
        row = await db.get(ApplicationSession, issued.session_id)
        assert row is not None and row.user_id == USER_A
        token = issued.credential.get_secret_value()
        assert len(parse_token(token)) == 32
        assert row.credential_hash == credential_digest(token)
        assert row.credential_hash != parse_token(token)
        assert row.csrf_secret == parse_token(issued.csrf_token.get_secret_value())
        assert token not in repr(issued) and issued.csrf_token.get_secret_value() not in repr(
            issued
        )
        principal = await service.resolve_principal(token)
        assert principal.kind == ApplicationSessionKind.GOOGLE_ACCOUNT
        assert principal.authenticated_user_id == principal.corpus_user_id == USER_A
        assert principal.conversation_owner.kind == "USER"
        assert principal.conversation_owner.id == USER_A
        assert not principal.demo_mode
        assert row.expires_at.tzinfo is not None and row.created_at.tzinfo is not None
        assert row.expires_at - row.created_at == GOOGLE_SESSION_LIFETIME
        with pytest.raises(FrozenInstanceError):
            principal.demo_mode = True  # type: ignore[misc]
        with pytest.raises(FrozenInstanceError):
            principal.conversation_owner.id = USER_B  # type: ignore[misc]
        with pytest.raises(InvalidApplicationSession):
            await service.resolve_principal(str(issued.session_id))
        assert (
            await db.scalar(select(User.google_id).where(User.id == USER_A)) == "verified-subject-a"
        )


async def test_demo_ownership_is_anonymous_without_adding_users(
    pg_engine: AsyncEngine,
    settings: Settings,
) -> None:
    settings.demo_mode = True
    async with async_sessionmaker(pg_engine, expire_on_commit=False)() as db:
        service = ApplicationSessionService(db, settings)
        count = await db.scalar(select(func.count()).select_from(User))
        issued = await service.issue_demo()
        await db.commit()
        principal = await service.resolve_principal(issued.credential.get_secret_value())
        assert principal.kind == ApplicationSessionKind.DEMO_VISITOR
        assert principal.authenticated_user_id is None
        assert principal.conversation_owner.kind == "APPLICATION_SESSION"
        assert principal.conversation_owner.id == issued.session_id
        assert principal.corpus_user_id == DEMO_USER
        assert principal.demo_mode
        assert await db.scalar(select(func.count()).select_from(User)) == count
        row = await db.get(ApplicationSession, issued.session_id)
        assert row is not None and row.user_id is None


async def test_distinct_browsers_and_accounts_have_independent_credentials_and_csrf(
    pg_engine: AsyncEngine,
    settings: Settings,
) -> None:
    async with async_sessionmaker(pg_engine)() as db:
        service = ApplicationSessionService(db, settings)
        a = await service.issue_google(VerifiedGoogleIdentity("verified-subject-a"))
        b = await service.issue_google(VerifiedGoogleIdentity("verified-subject-b"))
        again = await service.issue_google(VerifiedGoogleIdentity("verified-subject-a"))
        await db.commit()
        issued = [a, b, again]
        assert len({i.session_id for i in issued}) == 3
        assert len({i.credential.get_secret_value() for i in issued}) == 3
        assert len({i.csrf_token.get_secret_value() for i in issued}) == 3
        assert (
            await service.resolve_principal(a.credential.get_secret_value())
        ).corpus_user_id == USER_A
        assert (
            await service.resolve_principal(b.credential.get_secret_value())
        ).corpus_user_id == USER_B
        assert (
            await service.resolve_principal(again.credential.get_secret_value())
        ).conversation_owner.id == USER_A
        assert (
            await service.verify_csrf(
                a.credential.get_secret_value(), a.csrf_token.get_secret_value()
            )
        ).corpus_user_id == USER_A
        with pytest.raises(InvalidSessionRequest):
            await service.verify_csrf(
                a.credential.get_secret_value(), b.csrf_token.get_secret_value()
            )
        with pytest.raises(InvalidApplicationSession):
            await service.resolve_principal(
                "A" + a.credential.get_secret_value()[1:]
                if not a.credential.get_secret_value().startswith("A")
                else "B" + a.credential.get_secret_value()[1:]
            )


async def test_demo_browsers_share_corpus_but_not_ownership(
    pg_engine: AsyncEngine, settings: Settings
) -> None:
    settings.demo_mode = True
    async with async_sessionmaker(pg_engine)() as db:
        service = ApplicationSessionService(db, settings)
        a, b = await service.issue_demo(), await service.issue_demo()
        await db.commit()
        pa = await service.resolve_principal(a.credential.get_secret_value())
        pb = await service.resolve_principal(b.credential.get_secret_value())
        assert pa.corpus_user_id == pb.corpus_user_id == DEMO_USER
        assert pa.conversation_owner != pb.conversation_owner


async def test_absolute_expiry_and_revocation_are_fresh_across_sessions(
    pg_engine: AsyncEngine,
    settings: Settings,
) -> None:
    sessions = async_sessionmaker(pg_engine, expire_on_commit=False)
    clock = [datetime.now(UTC)]
    async with sessions() as db:
        service = ApplicationSessionService(db, settings, clock=lambda: clock[0])
        issued = await service.issue_google(VerifiedGoogleIdentity("verified-subject-a"))
        await db.commit()
        token = issued.credential.get_secret_value()
        assert await service.resolve_principal(token)
        clock[0] = issued.expires_at
        with pytest.raises(InvalidApplicationSession):
            await service.resolve_principal(token)
        clock[0] = issued.expires_at - timedelta(seconds=1)
        assert await service.resolve_principal(token)
        async with sessions() as other:
            assert await ApplicationSessionService(other, settings).revoke(token)
            await other.commit()
        with pytest.raises(InvalidApplicationSession):
            await service.resolve_principal(token)
        assert not await service.revoke(token)
        await db.commit()


async def test_runtime_mismatch_and_missing_identity_never_fall_back(
    pg_engine: AsyncEngine,
    settings: Settings,
) -> None:
    async with async_sessionmaker(pg_engine)() as db:
        normal = ApplicationSessionService(db, settings)
        a = await normal.issue_google(VerifiedGoogleIdentity("verified-subject-a"))
        demo_settings = settings.model_copy(update={"demo_mode": True})
        demo = ApplicationSessionService(db, demo_settings)
        b = await demo.issue_demo()
        await db.commit()
        for service, token in ((normal, b), (demo, a)):
            with pytest.raises(InvalidApplicationSession):
                await service.resolve_principal(token.credential.get_secret_value())
        for configured in ("", "not-a-uuid", str(uuid4())):
            demo_settings.demo_user_id = configured
            with pytest.raises(InvalidApplicationSession):
                await demo.resolve_principal(b.credential.get_secret_value())
        with pytest.raises(InvalidApplicationSession):
            await normal.issue_demo()
        with pytest.raises(InvalidApplicationSession):
            await demo.issue_google(VerifiedGoogleIdentity("verified-subject-a"))
        with pytest.raises(InvalidApplicationSession):
            await normal.issue_google(VerifiedGoogleIdentity("unregistered-subject"))


async def test_issuance_and_revocation_are_owned_by_caller_transaction(
    pg_engine: AsyncEngine,
    settings: Settings,
) -> None:
    sessions = async_sessionmaker(pg_engine)
    async with sessions() as issuer, sessions() as reader:
        service = ApplicationSessionService(issuer, settings)
        issued = await service.issue_google(VerifiedGoogleIdentity("verified-subject-a"))
        token = issued.credential.get_secret_value()
        with pytest.raises(InvalidApplicationSession):
            await ApplicationSessionService(reader, settings).resolve_principal(token)
        await issuer.commit()
        assert await ApplicationSessionService(reader, settings).resolve_principal(token)
        await service.revoke(token)
        await issuer.rollback()
        assert await ApplicationSessionService(reader, settings).resolve_principal(token)
        rolled_back = await service.issue_google(VerifiedGoogleIdentity("verified-subject-b"))
        await issuer.rollback()
        with pytest.raises(InvalidApplicationSession):
            await ApplicationSessionService(reader, settings).resolve_principal(
                rolled_back.credential.get_secret_value()
            )


@pytest.mark.parametrize(
    "invalid",
    [
        "google_without_user",
        "demo_with_user",
        "unknown_kind",
        "missing_user",
        "short_digest",
        "short_csrf",
        "expired_at_creation",
        "duplicate_digest",
    ],
)
async def test_database_constraints_reject_invalid_rows(
    pg_engine: AsyncEngine,
    invalid: str,
) -> None:
    values: dict[str, object] = {
        "id": uuid4(),
        "credential_hash": b"h" * 32,
        "kind": "DEMO_VISITOR",
        "user_id": None,
        "csrf_secret": b"c" * 32,
        "created_at": datetime.now(UTC),
        "expires_at": datetime.now(UTC) + timedelta(days=1),
    }
    if invalid == "google_without_user":
        values["kind"] = "GOOGLE_ACCOUNT"
    elif invalid == "demo_with_user":
        values["user_id"] = USER_A
    elif invalid == "unknown_kind":
        values["kind"] = "OTHER"
    elif invalid == "missing_user":
        values.update(kind="GOOGLE_ACCOUNT", user_id=uuid4())
    elif invalid == "short_digest":
        values["credential_hash"] = b"h"
    elif invalid == "short_csrf":
        values["csrf_secret"] = b"c"
    elif invalid == "expired_at_creation":
        values["expires_at"] = values["created_at"]
    query = text(
        "INSERT INTO application_sessions (id, credential_hash, kind, user_id, csrf_secret, created_at, expires_at) VALUES (:id, :credential_hash, :kind, :user_id, :csrf_secret, :created_at, :expires_at)"
    )
    if invalid == "duplicate_digest":
        async with pg_engine.begin() as connection:
            await connection.execute(query, values)
        values["id"] = uuid4()
    with pytest.raises(IntegrityError):
        async with pg_engine.begin() as connection:
            await connection.execute(query, values)
    # A rejected transaction leaves no invalid row behind.
    async with pg_engine.connect() as connection:
        count = await connection.scalar(text("SELECT count(*) FROM application_sessions"))
        assert count == (1 if invalid == "duplicate_digest" else 0)


async def test_user_delete_cascades_only_account_sessions(
    pg_engine: AsyncEngine, settings: Settings
) -> None:
    async with async_sessionmaker(pg_engine)() as db:
        account = await ApplicationSessionService(db, settings).issue_google(
            VerifiedGoogleIdentity("verified-subject-a")
        )
        demo = await ApplicationSessionService(
            db, settings.model_copy(update={"demo_mode": True})
        ).issue_demo()
        await db.commit()
        await db.execute(delete(User).where(User.id == USER_A))
        await db.commit()
        assert await db.get(ApplicationSession, account.session_id) is None
        assert await db.get(ApplicationSession, demo.session_id) is not None


async def test_additive_migration_downgrade_upgrade_preserves_existing_users(
    pg_engine: AsyncEngine,
) -> None:
    async with pg_engine.begin() as connection:
        before = (
            await connection.execute(select(User.id, User.email, User.google_id).order_by(User.id))
        ).all()
        await connection.run_sync(
            lambda conn: apply_revision(conn, SESSION_REVISION, downgrade=True)
        )
        assert await connection.scalar(text("SELECT to_regclass('application_sessions')")) is None
        assert await connection.scalar(text("SELECT to_regclass('drive_files')")) is not None
        assert (
            await connection.execute(select(User.id, User.email, User.google_id).order_by(User.id))
        ).all() == before
        await connection.run_sync(apply_revision, SESSION_REVISION)
        assert (
            await connection.scalar(text("SELECT to_regclass('application_sessions')")) is not None
        )
        assert (
            await connection.execute(select(User.id, User.email, User.google_id).order_by(User.id))
        ).all() == before


async def test_database_csrf_change_invalidates_previous_token_in_same_orm_session(
    pg_engine: AsyncEngine,
    settings: Settings,
) -> None:
    from sqlalchemy import update

    sessions = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with sessions() as reader:
        service = ApplicationSessionService(reader, settings)
        issued = await service.issue_google(VerifiedGoogleIdentity("verified-subject-a"))
        await reader.commit()
        token = issued.credential.get_secret_value()
        csrf = issued.csrf_token.get_secret_value()
        assert await service.verify_csrf(token, csrf)
        async with sessions() as writer:
            await writer.execute(
                update(ApplicationSession)
                .where(ApplicationSession.id == issued.session_id)
                .values(csrf_secret=b"z" * 32)
            )
            await writer.commit()
        with pytest.raises(InvalidSessionRequest):
            await service.verify_csrf(token, csrf)


async def test_real_migration_installs_named_checks_indexes_and_foreign_key(
    pg_engine: AsyncEngine,
) -> None:
    from sqlalchemy import inspect

    async with pg_engine.connect() as connection:
        checks = await connection.run_sync(
            lambda c: inspect(c).get_check_constraints("application_sessions")
        )
        assert {check["name"] for check in checks} == {
            "ck_application_sessions_kind",
            "ck_application_sessions_owner",
            "ck_application_sessions_digest",
            "ck_application_sessions_csrf",
            "ck_application_sessions_expiry",
        }
        indexes = await connection.run_sync(
            lambda c: inspect(c).get_indexes("application_sessions")
        )
        assert {index["name"] for index in indexes} >= {
            "ix_application_sessions_user_id",
            "ix_application_sessions_expires_at",
            "uq_application_sessions_credential_hash",
        }
        fks = await connection.run_sync(
            lambda c: inspect(c).get_foreign_keys("application_sessions")
        )
        assert len(fks) == 1 and fks[0]["referred_table"] == "users"
        assert fks[0].get("options", {}).get("ondelete") == "CASCADE"
