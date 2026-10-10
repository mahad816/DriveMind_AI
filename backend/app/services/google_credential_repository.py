"""Inactive owner-scoped Google credential boundary, with explicit compatibility I/O.

Callers establish trusted ownership and control commit/rollback. No network calls,
first-account fallback, automatic backfill or production wiring exist here.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models.google_oauth_token import GoogleOAuthToken
from app.db.models.user import User
from app.security.google_credential_crypto import (
    GoogleCredentialCrypto,
    GoogleCredentialPayload,
    InvalidCredentialPayload,
)


class CredentialRepositoryError(RuntimeError):
    message = "Google credentials are unavailable."

    def __init__(self) -> None:
        super().__init__(self.message)


class CredentialNotFound(CredentialRepositoryError):
    message = "Google credentials were not found."


class EncryptedCredentialsUnavailable(CredentialRepositoryError):
    message = "Encrypted Google credentials are unavailable."


class LegacyCredentialReadRejected(CredentialRepositoryError):
    message = "Legacy Google credential access is unavailable."


class InvalidCredentialOwner(CredentialRepositoryError):
    message = "Google credential ownership could not be verified."


class CredentialRecordChanged(CredentialRepositoryError):
    message = "Google credential record changed. Please reload it."


class CredentialStoreUnavailable(CredentialRepositoryError):
    message = "Google credential storage is temporarily unavailable."


class UnsafeCredentialDatabaseConfiguration(CredentialRepositoryError):
    message = "Google credential database security configuration is unavailable."


class ExistingCredentialStorage(StrEnum):
    ENCRYPTED = "ENCRYPTED"
    LEGACY = "LEGACY"


@dataclass(frozen=True)
class CredentialRecord:
    id: UUID = field(repr=False)
    user_id: UUID = field(repr=False)
    encrypted_credentials: SecretStr | None = field(repr=False)
    token_expiry: datetime | None = field(repr=False)
    scopes: str = field(repr=False)


@dataclass(frozen=True)
class CredentialSnapshot:
    record: CredentialRecord = field(repr=False)
    payload: GoogleCredentialPayload = field(repr=False)
    storage: ExistingCredentialStorage


class GoogleCredentialRepository:
    """No commits, rollback or logging; SQL failures become fixed safe exceptions.

    Explicit compatibility writes maintain plaintext mirrors because the existing
    schema requires access_token. This is not encrypted-only storage. Call only
    after provider I/O; writer locks last until the caller commits or rolls back.
    """

    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    @staticmethod
    def _owner(user_id: UUID) -> None:
        if not isinstance(user_id, UUID):
            raise InvalidCredentialOwner()

    def _safe_database(self) -> None:
        # Do not mutate the application's legacy engine or logging configuration.
        bind = self.db.get_bind(mapper=GoogleOAuthToken)
        engine = bind.engine if isinstance(bind, Connection) else bind
        logger = engine.logger
        actual_logger = logger if isinstance(logger, logging.Logger) else logger.logger
        if not engine.hide_parameters or engine.echo or actual_logger.isEnabledFor(logging.DEBUG):
            raise UnsafeCredentialDatabaseConfiguration()

    async def _find(self, user_id: UUID, *, lock: bool = False) -> GoogleOAuthToken:
        self._owner(user_id)
        try:
            self._safe_database()
            statement = select(GoogleOAuthToken).where(GoogleOAuthToken.user_id == user_id)
            if lock:
                statement = statement.with_for_update()
            row = await self.db.scalar(
                statement.execution_options(populate_existing=True, autoflush=False)
            )
        except SQLAlchemyError:
            raise CredentialStoreUnavailable() from None
        if row is None:
            raise CredentialNotFound()
        return row

    @staticmethod
    def _record(row: GoogleOAuthToken) -> CredentialRecord:
        return CredentialRecord(
            row.id,
            row.user_id,
            SecretStr(row.encrypted_credentials) if row.encrypted_credentials is not None else None,
            row.token_expiry,
            row.scopes,
        )

    def _read(self, row: GoogleOAuthToken, mode: ExistingCredentialStorage) -> CredentialSnapshot:
        if mode == ExistingCredentialStorage.ENCRYPTED:
            if row.encrypted_credentials is None:
                raise EncryptedCredentialsUnavailable()
            payload = GoogleCredentialCrypto.from_settings(self.settings).decrypt(
                row.encrypted_credentials,
                user_id=row.user_id,
                credential_id=row.id,
                provider="google",
            )
        elif mode == ExistingCredentialStorage.LEGACY:
            # Explicit legacy access cannot override present but unusable ciphertext.
            if row.encrypted_credentials is not None:
                raise LegacyCredentialReadRejected()
            payload = GoogleCredentialPayload(
                row.user_id,
                row.id,
                SecretStr(row.access_token),
                SecretStr(row.refresh_token) if row.refresh_token is not None else None,
            )
        else:
            raise LegacyCredentialReadRejected()
        return CredentialSnapshot(self._record(row), payload, mode)

    async def load_record(self, user_id: UUID) -> CredentialRecord:
        return self._record(await self._find(user_id))

    async def load_encrypted(self, user_id: UUID) -> CredentialSnapshot:
        return self._read(await self._find(user_id), ExistingCredentialStorage.ENCRYPTED)

    async def load_legacy(self, user_id: UUID) -> CredentialSnapshot:
        return self._read(await self._find(user_id), ExistingCredentialStorage.LEGACY)

    def prepare_encrypted(
        self,
        user_id: UUID,
        credential_id: UUID,
        *,
        access_token: SecretStr,
        refresh_token: SecretStr | None,
    ) -> SecretStr:
        """Pure preparation, not authorization: IDs must be stable application-owned IDs."""
        self._owner(user_id)
        if not isinstance(credential_id, UUID) or not isinstance(access_token, SecretStr):
            raise InvalidCredentialPayload()
        return GoogleCredentialCrypto.from_settings(self.settings).encrypt(
            GoogleCredentialPayload(user_id, credential_id, access_token, refresh_token)
        )

    async def write_encrypted_compatibility(
        self,
        user_id: UUID,
        *,
        access_token: SecretStr,
        refresh_token: SecretStr | None,
        token_expiry: datetime | None,
        scopes: str,
        existing_storage: ExistingCredentialStorage = ExistingCredentialStorage.ENCRYPTED,
        expected_record_id: UUID | None = None,
    ) -> CredentialRecord:
        """Flush an explicit encrypted+plaintext mirror write; caller owns transaction.

        None refresh_token means preserve the current grant, not clear it. Legacy
        upgrades require explicit LEGACY selection. Wrong/corrupt ciphertext is
        never bypassed, even when replacement tokens are provided.
        """
        self._owner(user_id)
        if (
            not isinstance(existing_storage, ExistingCredentialStorage)
            or not isinstance(access_token, SecretStr)
            or (refresh_token is not None and not isinstance(refresh_token, SecretStr))
            or (expected_record_id is not None and not isinstance(expected_record_id, UUID))
            or not isinstance(scopes, str)
            or len(scopes) > 8192
            or (
                token_expiry is not None
                and (not isinstance(token_expiry, datetime) or token_expiry.tzinfo is None)
            )
        ):
            raise InvalidCredentialPayload()
        try:
            scopes.encode("utf-8")
        except UnicodeError:
            raise InvalidCredentialPayload() from None
        # Fail on missing/malformed keys before acquiring database locks.
        crypto = GoogleCredentialCrypto.from_settings(self.settings)
        try:
            self._safe_database()
            # Lock the stable owner, including when no token row exists yet.
            # Cooperating writers for different owners remain independent.
            owner = await self.db.scalar(
                select(User.id)
                .where(User.id == user_id)
                .with_for_update()
                .execution_options(autoflush=False)
            )
            if owner is None:
                raise CredentialNotFound()
            try:
                row = await self._find(user_id, lock=True)
            except CredentialNotFound:
                row = None
            if expected_record_id is not None and (row is None or row.id != expected_record_id):
                raise CredentialRecordChanged()
            merged_refresh = refresh_token
            if row is not None:
                existing = self._read(row, existing_storage)
                if merged_refresh is None:
                    merged_refresh = existing.payload.refresh_token
                row_id = row.id
            else:
                row_id = uuid4()  # Assigned once, BEFORE encryption and ORM flush.
            payload = GoogleCredentialPayload(user_id, row_id, access_token, merged_refresh)
            encrypted = crypto.encrypt(payload)
            expiry = token_expiry.astimezone(UTC) if token_expiry is not None else None
            if row is None:
                row = GoogleOAuthToken(id=row_id, user_id=user_id)
                self.db.add(row)
            row.access_token = access_token.get_secret_value()
            row.refresh_token = (
                merged_refresh.get_secret_value() if merged_refresh is not None else None
            )
            row.encrypted_credentials = encrypted.get_secret_value()
            row.token_expiry = expiry
            row.scopes = scopes
            self._safe_database()
            await self.db.flush([row])
            return self._record(row)
        except SQLAlchemyError:
            raise CredentialStoreUnavailable() from None
