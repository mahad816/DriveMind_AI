"""Encrypted-only, explicit-owner credential persistence. Caller owns transactions."""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
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


class InvalidCredentialOwner(CredentialRepositoryError):
    message = "Google credential ownership could not be verified."


class CredentialRecordChanged(CredentialRepositoryError):
    message = "Google credential grant changed. Please reload it."


class CredentialStoreUnavailable(CredentialRepositoryError):
    message = "Google credential storage is temporarily unavailable."


class UnsafeCredentialDatabaseConfiguration(CredentialRepositoryError):
    message = "Google credential database security configuration is unavailable."


class CredentialRecoveryRequired(CredentialRepositoryError):
    message = "Google credential recovery is pending. Try later or reconnect Google Drive."


class CredentialReauthorizationRequired(CredentialRepositoryError):
    message = "Reconnect Google Drive to authorize this operation."


class CredentialRefreshBusy(CredentialRepositoryError):
    message = "Google credential refresh is in progress. Please try again shortly."


@dataclass(frozen=True)
class CredentialRecord:
    id: UUID = field(repr=False)
    user_id: UUID = field(repr=False)
    encrypted_credentials: SecretStr = field(repr=False)
    token_expiry: datetime | None = field(repr=False)
    scopes: str = field(repr=False)
    credential_revision: int = field(repr=False)
    grant_epoch: int = field(repr=False)
    grant_status: str
    refresh_claim_id: UUID | None = field(repr=False)
    refresh_claim_state: str | None = field(repr=False)
    refresh_claim_expires_at: datetime | None = field(repr=False)


@dataclass(frozen=True)
class CredentialSnapshot:
    record: CredentialRecord = field(repr=False)
    payload: GoogleCredentialPayload = field(repr=False)


@dataclass(frozen=True)
class RefreshClaim:
    snapshot: CredentialSnapshot = field(repr=False)
    id: UUID = field(repr=False)


class GoogleCredentialRepository:
    """No commits, network calls, plaintext mirrors or first-account selection."""

    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db, self.settings = db, settings

    def _owner(self, user_id: UUID) -> None:
        if self.settings.demo_mode or not isinstance(user_id, UUID):
            raise InvalidCredentialOwner()

    def _safe_database(self) -> None:
        bind = self.db.get_bind(mapper=GoogleOAuthToken)
        engine = bind.engine if isinstance(bind, Connection) else bind
        logger = engine.logger
        actual = logger if isinstance(logger, logging.Logger) else logger.logger
        if not engine.hide_parameters or engine.echo or actual.isEnabledFor(logging.DEBUG):
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

    async def _flush(self, row: GoogleOAuthToken) -> None:
        try:
            await self.db.flush([row])
        except SQLAlchemyError:
            raise CredentialStoreUnavailable() from None

    @staticmethod
    def _record(row: GoogleOAuthToken) -> CredentialRecord:
        return CredentialRecord(
            row.id,
            row.user_id,
            SecretStr(row.encrypted_credentials),
            row.token_expiry,
            row.scopes,
            row.credential_revision,
            row.grant_epoch,
            row.grant_status,
            row.refresh_claim_id,
            row.refresh_claim_state,
            row.refresh_claim_expires_at,
        )

    def _read(self, row: GoogleOAuthToken) -> CredentialSnapshot:
        payload = GoogleCredentialCrypto.from_settings(self.settings).decrypt(
            row.encrypted_credentials, user_id=row.user_id, credential_id=row.id, provider="google"
        )
        return CredentialSnapshot(self._record(row), payload)

    async def load_record(self, user_id: UUID) -> CredentialRecord:
        return self._record(await self._find(user_id))

    async def load_encrypted(self, user_id: UUID) -> CredentialSnapshot:
        return self._read(await self._find(user_id))

    def prepare_encrypted(
        self,
        user_id: UUID,
        credential_id: UUID,
        *,
        access_token: SecretStr,
        refresh_token: SecretStr | None,
    ) -> SecretStr:
        self._owner(user_id)
        return GoogleCredentialCrypto.from_settings(self.settings).encrypt(
            GoogleCredentialPayload(user_id, credential_id, access_token, refresh_token)
        )

    @staticmethod
    def _clear_claim(row: GoogleOAuthToken) -> None:
        row.refresh_claim_id = row.refresh_claim_state = row.refresh_claim_expires_at = None

    async def write_verified_grant(
        self,
        user_id: UUID,
        *,
        access_token: SecretStr,
        refresh_token: SecretStr | None,
        token_expiry: datetime | None,
        scopes: str,
    ) -> CredentialRecord:
        """Caller has verified the Google subject. Fresh refresh tokens permit reconnect recovery.

        Omitted refresh tokens can only preserve an active, unclaimed, decryptable grant.
        Reconnect never recreates a row implicitly from a refresh result.
        """
        self._owner(user_id)
        crypto = GoogleCredentialCrypto.from_settings(self.settings)
        if (
            not isinstance(scopes, str)
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
        try:
            self._safe_database()
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
            if refresh_token is None:
                if row is None or row.grant_status != "ACTIVE" or row.refresh_claim_id is not None:
                    raise CredentialReauthorizationRequired()
                refresh_token = self._read(row).payload.refresh_token
                if refresh_token is None:
                    raise CredentialReauthorizationRequired()
            row_id = row.id if row is not None else uuid4()
            encrypted = crypto.encrypt(
                GoogleCredentialPayload(user_id, row_id, access_token, refresh_token)
            ).get_secret_value()
            if row is None:
                row = GoogleOAuthToken(
                    id=row_id, user_id=user_id, credential_revision=1, grant_epoch=1
                )
                self.db.add(row)
            else:
                row.credential_revision += 1
                row.grant_epoch += 1
            row.encrypted_credentials = encrypted
            row.scopes = scopes
            row.token_expiry = token_expiry.astimezone(UTC) if token_expiry else None
            row.grant_status = "ACTIVE"
            self._clear_claim(row)
            await self._flush(row)
            return self._record(row)
        except SQLAlchemyError:
            raise CredentialStoreUnavailable() from None

    @staticmethod
    def _same(row: GoogleOAuthToken, record: CredentialRecord) -> bool:
        return (row.id, row.user_id, row.credential_revision, row.grant_epoch) == (
            record.id,
            record.user_id,
            record.credential_revision,
            record.grant_epoch,
        )

    async def claim_refresh(self, record: CredentialRecord) -> RefreshClaim:
        row = await self._find(record.user_id, lock=True)
        if not self._same(row, record):
            raise CredentialRecordChanged()
        if row.grant_status == "REAUTH_REQUIRED":
            raise CredentialReauthorizationRequired()
        if row.grant_status == "RECOVERY_REQUIRED":
            raise CredentialRecoveryRequired()
        now = datetime.now(UTC)
        if row.refresh_claim_id is not None:
            if row.refresh_claim_expires_at is not None and row.refresh_claim_expires_at <= now:
                if row.refresh_claim_state == "SUBMITTED":
                    raise CredentialRecoveryRequired()  # retain claim: late completion remains recoverable
                # No network is permitted before SUBMITTED is committed. Old prepared claims can retire.
                self._clear_claim(row)
            else:
                raise CredentialRefreshBusy()
        snapshot = self._read(row)
        if snapshot.payload.refresh_token is None:
            raise CredentialReauthorizationRequired()
        claim_id = uuid4()
        row.refresh_claim_id, row.refresh_claim_state = claim_id, "PREPARED"
        row.refresh_claim_expires_at = now + timedelta(seconds=30)
        await self._flush(row)
        return RefreshClaim(snapshot, claim_id)

    async def _claimed(self, claim: RefreshClaim) -> GoogleOAuthToken:
        row = await self._find(claim.snapshot.record.user_id, lock=True)
        if not self._same(row, claim.snapshot.record) or row.refresh_claim_id != claim.id:
            raise CredentialRecordChanged()
        if row.grant_status not in {"ACTIVE", "RECOVERY_REQUIRED"}:
            raise CredentialRecordChanged()
        return row

    async def submit_refresh(self, claim: RefreshClaim) -> None:
        row = await self._claimed(claim)
        if (
            row.refresh_claim_state != "PREPARED"
            or row.refresh_claim_expires_at is None
            or row.refresh_claim_expires_at <= datetime.now(UTC)
        ):
            raise CredentialRecordChanged()
        row.refresh_claim_state = "SUBMITTED"
        await self._flush(row)

    async def complete_refresh(
        self,
        claim: RefreshClaim,
        *,
        access_token: SecretStr,
        refresh_token: SecretStr | None,
        token_expiry: datetime,
        scopes: str,
    ) -> CredentialSnapshot:
        row = await self._claimed(claim)
        if row.refresh_claim_state != "SUBMITTED" or token_expiry.tzinfo is None:
            raise CredentialRecordChanged()
        refresh = refresh_token or claim.snapshot.payload.refresh_token
        row.encrypted_credentials = self.prepare_encrypted(
            row.user_id, row.id, access_token=access_token, refresh_token=refresh
        ).get_secret_value()
        row.credential_revision += 1
        row.token_expiry, row.scopes = token_expiry.astimezone(UTC), scopes
        row.grant_status = "ACTIVE"
        self._clear_claim(row)
        await self._flush(row)
        return self._read(row)

    async def fail_refresh(
        self, claim: RefreshClaim, *, revoked: bool = False, before_submission: bool = False
    ) -> None:
        row = await self._claimed(claim)
        if before_submission:  # only the owning worker can attest that no request was sent
            self._clear_claim(row)
        elif revoked:
            row.grant_status = "REAUTH_REQUIRED"
            self._clear_claim(row)
        else:
            row.grant_status = "RECOVERY_REQUIRED"  # retain claim for a valid late result
        await self._flush(row)
