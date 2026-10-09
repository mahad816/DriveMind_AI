"""Inactive shared session issuance and fresh database-backed validation."""

import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.enums import ApplicationSessionKind
from app.db.models.application_session import ApplicationSession
from app.db.models.user import User
from app.security.principal import ApplicationPrincipal, ConversationOwner, VerifiedGoogleIdentity
from app.security.session_helpers import (
    InvalidApplicationSession,
    SessionStoreUnavailable,
    credential_digest,
    encode_token,
    verify_csrf_secret,
)

GOOGLE_SESSION_LIFETIME = timedelta(days=7)
DEMO_SESSION_LIFETIME = timedelta(days=30)


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class IssuedApplicationSession:
    session_id: UUID
    expires_at: datetime
    credential: SecretStr = field(repr=False)
    csrf_token: SecretStr = field(repr=False)


class ApplicationSessionService:
    """Caller owns commit/rollback. No authentication result is cached.

    Issuance requires trusted server code; there is deliberately no public issuer.
    These absolute lifetimes are inactive defaults, not a deployed login policy.
    """

    def __init__(
        self,
        db: AsyncSession,
        settings: Settings,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.db = db
        self.settings = settings
        self.clock = clock

    def _now(self) -> datetime:
        now = self.clock()
        if now.tzinfo is None:
            raise ValueError("Session clock must be timezone-aware")
        return now.astimezone(UTC)

    def _kind(self) -> ApplicationSessionKind:
        return (
            ApplicationSessionKind.DEMO_VISITOR
            if self.settings.demo_mode
            else ApplicationSessionKind.GOOGLE_ACCOUNT
        )

    async def _require_user(self, user_id: UUID) -> None:
        existing = await self.db.scalar(select(User.id).where(User.id == user_id))
        if existing != user_id:
            raise InvalidApplicationSession()

    async def _demo_user(self) -> UUID:
        try:
            user_id = UUID(self.settings.demo_user_id)
        except (ValueError, TypeError, AttributeError):
            raise InvalidApplicationSession() from None
        await self._require_user(user_id)
        return user_id

    async def _issue(self, user_id: UUID | None) -> IssuedApplicationSession:
        credential = secrets.token_bytes(32)
        csrf = secrets.token_bytes(32)
        now = self._now()
        expires = now + (
            DEMO_SESSION_LIFETIME if self.settings.demo_mode else GOOGLE_SESSION_LIFETIME
        )
        row = ApplicationSession(
            credential_hash=hashlib.sha256(credential).digest(),
            kind=self._kind(),
            user_id=user_id,
            created_at=now,
            expires_at=expires,
            csrf_secret=csrf,
        )
        self.db.add(row)
        await self.db.flush()
        return IssuedApplicationSession(
            session_id=row.id,
            expires_at=expires,
            credential=SecretStr(encode_token(credential)),
            csrf_token=SecretStr(encode_token(csrf)),
        )

    async def issue_google(self, identity: VerifiedGoogleIdentity) -> IssuedApplicationSession:
        if self.settings.demo_mode or not isinstance(identity, VerifiedGoogleIdentity):
            raise InvalidApplicationSession()
        try:
            user_id = await self.db.scalar(
                select(User.id).where(User.google_id == identity.subject)
            )
            if not isinstance(user_id, UUID):
                raise InvalidApplicationSession()
            return await self._issue(user_id)
        except SQLAlchemyError:
            raise SessionStoreUnavailable() from None

    async def issue_demo(self) -> IssuedApplicationSession:
        if not self.settings.demo_mode:
            raise InvalidApplicationSession()
        try:
            await self._demo_user()
            return await self._issue(None)
        except SQLAlchemyError:
            raise SessionStoreUnavailable() from None

    async def _lookup(self, credential: str | None) -> ApplicationSession:
        digest = credential_digest(credential)
        row = await self.db.scalar(
            select(ApplicationSession)
            .where(
                ApplicationSession.credential_hash == digest,
                ApplicationSession.kind == self._kind(),
                ApplicationSession.revoked_at.is_(None),
                ApplicationSession.expires_at > self._now(),
            )
            .execution_options(populate_existing=True)
        )
        if not isinstance(row, ApplicationSession):
            raise InvalidApplicationSession()
        return row

    async def _principal(self, row: ApplicationSession) -> ApplicationPrincipal:
        if self.settings.demo_mode:
            if row.user_id is not None or row.kind != ApplicationSessionKind.DEMO_VISITOR:
                raise InvalidApplicationSession()
            corpus_user_id = await self._demo_user()
            owner = ConversationOwner("APPLICATION_SESSION", row.id)
        else:
            if row.user_id is None or row.kind != ApplicationSessionKind.GOOGLE_ACCOUNT:
                raise InvalidApplicationSession()
            await self._require_user(row.user_id)
            corpus_user_id = row.user_id
            owner = ConversationOwner("USER", row.user_id)
        return ApplicationPrincipal(
            session_id=row.id,
            kind=row.kind,
            authenticated_user_id=row.user_id,
            conversation_owner=owner,
            corpus_user_id=corpus_user_id,
            demo_mode=self.settings.demo_mode,
        )

    async def resolve_principal(self, credential: str | None) -> ApplicationPrincipal:
        try:
            return await self._principal(await self._lookup(credential))
        except SQLAlchemyError:
            raise SessionStoreUnavailable() from None

    async def verify_csrf(
        self, credential: str | None, csrf_token: str | None
    ) -> ApplicationPrincipal:
        try:
            row = await self._lookup(credential)
            verify_csrf_secret(row.csrf_secret, csrf_token)
            return await self._principal(row)
        except SQLAlchemyError:
            raise SessionStoreUnavailable() from None

    async def revoke(self, credential: str | None) -> bool:
        digest = credential_digest(credential)
        try:
            revoked = await self.db.scalar(
                update(ApplicationSession)
                .where(
                    ApplicationSession.credential_hash == digest,
                    ApplicationSession.kind == self._kind(),
                    ApplicationSession.revoked_at.is_(None),
                )
                .values(revoked_at=self._now())
                .returning(ApplicationSession.id)
            )
            return revoked is not None
        except SQLAlchemyError:
            raise SessionStoreUnavailable() from None
