"""Managed Google refresh, with independent short DB transactions and no silent retry."""

import asyncio
import time
from collections.abc import Coroutine
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import UTC, datetime
from typing import Any, TypeVar
from uuid import UUID

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from pydantic import SecretStr
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.connectors.google_drive.client import DriveClientError, DriveTokens, GoogleDriveClient
from app.core.config import Settings
from app.core.credential_diagnostics import failure_category
from app.security.google_credential_crypto import CredentialCryptoError, GoogleCredentialCrypto
from app.services.google_credential_repository import (
    CredentialNotFound,
    CredentialRecordChanged,
    CredentialRecoveryRequired,
    CredentialReauthorizationRequired,
    CredentialRepositoryError,
    CredentialSnapshot,
    GoogleCredentialRepository,
    RefreshClaim,
)

T = TypeVar("T")


def utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class SingleRefreshRequest:
    """Only one token endpoint attempt. SDK retries must not reuse an uncertain token."""

    def __init__(self) -> None:
        self.request = Request()
        self.attempted = False

    def close(self) -> None:
        session = getattr(self.request, "session", None)
        if session is not None:
            session.close()

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if self.attempted:
            raise DriveClientError("Google refresh recovery is required.")
        self.attempted = True
        kwargs["timeout"] = (5, 10)
        response = self.request(*args, **kwargs)
        if response.status == 429 or 500 <= response.status <= 599:
            raise DriveClientError(
                "Google is temporarily unavailable; refresh recovery is pending.",
                category="temporary_provider_failure",
            )
        return response


class GoogleCredentialService:
    """The existing SDK thread owns refresh and persistence even if its awaiter cancels.

    SDK credentials contain no refresh token: explicit/implicit refresh uses its
    supported refresh_handler. DB callbacks use fresh sessions on the captured
    application loop. No request AsyncSession is used concurrently or committed.
    Loss of that loop/process leaves a persisted claim; it is never blindly stolen.
    """

    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        if settings.demo_mode or not isinstance(db.bind, AsyncEngine):
            raise DriveClientError(
                "Google credential configuration is unavailable.", category="configuration_error"
            )
        self.settings = settings
        self.loop = asyncio.get_running_loop()
        self.sessions = async_sessionmaker(db.bind, expire_on_commit=False)

    async def load(self, user_id: UUID) -> CredentialSnapshot:
        try:
            GoogleCredentialCrypto.from_settings(self.settings)
            async with self.sessions() as db:
                snapshot = await GoogleCredentialRepository(db, self.settings).load_encrypted(
                    user_id
                )
            record = snapshot.record
            if record.grant_status == "REAUTH_REQUIRED":
                raise CredentialReauthorizationRequired()
            if record.grant_status == "RECOVERY_REQUIRED" or (
                record.refresh_claim_state == "SUBMITTED"
                and record.refresh_claim_expires_at is not None
                and record.refresh_claim_expires_at <= datetime.now(UTC)
            ):
                raise CredentialRecoveryRequired()
            return snapshot
        except CredentialCryptoError:
            raise DriveClientError(
                "Google credential encryption is unavailable.", category="configuration_error"
            ) from None
        except CredentialReauthorizationRequired:
            raise DriveClientError(
                "Reconnect Google Drive to authorize this operation.",
                category="reauthorization_required",
            ) from None
        except CredentialRecoveryRequired:
            raise DriveClientError(
                "Google refresh recovery is pending; try later or reconnect.",
                category="temporary_provider_failure",
            ) from None
        except CredentialRepositoryError:
            raise DriveClientError(
                "Google credentials are unavailable; try later or reconnect."
            ) from None

    def _on_loop(self, coroutine: Coroutine[Any, Any, T]) -> T:
        # Called only by SDK worker threads. Its future is independent of the HTTP task.
        if self.loop.is_closed():
            coroutine.close()
            raise DriveClientError("Google refresh recovery is required.")

        async def bounded() -> T:
            async with asyncio.timeout(5):
                return await coroutine

        future = asyncio.run_coroutine_threadsafe(bounded(), self.loop)
        try:
            return future.result(timeout=10)
        except FutureTimeout:
            # Do not cancel: a submitted DB commit can still finish. Never start
            # Google I/O after an uncertain claim/submit operation.
            raise DriveClientError("Google refresh recovery is pending.") from None
        except (CredentialRepositoryError, CredentialCryptoError, SQLAlchemyError):
            raise DriveClientError(
                "Google refresh is unavailable; try later or reconnect."
            ) from None

    async def _claim(self, snapshot: CredentialSnapshot) -> RefreshClaim:
        async with self.sessions() as db:
            claim = await GoogleCredentialRepository(db, self.settings).claim_refresh(
                snapshot.record
            )
            await db.commit()
            return claim

    async def _submit(self, claim: RefreshClaim) -> None:
        async with self.sessions() as db:
            await GoogleCredentialRepository(db, self.settings).submit_refresh(claim)
            await db.commit()

    async def _complete(self, claim: RefreshClaim, credentials: Credentials) -> CredentialSnapshot:
        expiry = utc(credentials.expiry)
        if not credentials.token or expiry is None:
            raise DriveClientError("Google returned unusable refresh credentials.")
        async with self.sessions() as db:
            snapshot = await GoogleCredentialRepository(db, self.settings).complete_refresh(
                claim,
                access_token=SecretStr(credentials.token),
                refresh_token=SecretStr(credentials.refresh_token)
                if credentials.refresh_token
                else None,
                token_expiry=expiry,
                scopes=" ".join(
                    credentials.granted_scopes
                    or credentials.scopes
                    or claim.snapshot.record.scopes.split()
                ),
            )
            await db.commit()
            return snapshot

    async def _fail(
        self, claim: RefreshClaim, revoked: bool, before_submission: bool = False
    ) -> None:
        async with self.sessions() as db:
            try:
                await GoogleCredentialRepository(db, self.settings).fail_refresh(
                    claim, revoked=revoked, before_submission=before_submission
                )
                await db.commit()
            except (CredentialRecordChanged, CredentialNotFound):
                # Reconnect/deletion won: a stale failure cannot change the new grant.
                await db.rollback()

    def client(self, snapshot: CredentialSnapshot) -> GoogleDriveClient:
        payload = snapshot.payload
        if payload.access_token is None:
            raise DriveClientError("Google access credentials are unavailable.")
        if not self.settings.google_client_id or not self.settings.google_client_secret:
            raise DriveClientError(
                "Google credential configuration is unavailable.", category="configuration_error"
            )
        current = snapshot

        def refresh_handler(request: Any, scopes: Any = None) -> tuple[str, datetime]:
            nonlocal current
            deadline = time.monotonic() + 3
            while True:
                try:
                    claim = self._on_loop(self._claim(current))
                    break
                except DriveClientError:
                    # Reload is bounded; only a changed successful revision can
                    # supply a reusable result. Never retry an unknown refresh.
                    latest = self._on_loop(self.load(current.record.user_id))
                    if (
                        latest.record.id != current.record.id
                        or latest.record.grant_epoch != current.record.grant_epoch
                    ):
                        raise DriveClientError(
                            "Google connection changed; retry this operation."
                        ) from None
                    if latest.record.credential_revision != current.record.credential_revision:
                        current = latest
                        if latest.payload.access_token and latest.record.token_expiry:
                            return (
                                latest.payload.access_token.get_secret_value(),
                                latest.record.token_expiry.astimezone(UTC).replace(tzinfo=None),
                            )
                    if time.monotonic() >= deadline:
                        raise DriveClientError(
                            "Google credential refresh is busy; try later."
                        ) from None
                    time.sleep(0.05)
            native = Credentials(  # type: ignore[no-untyped-call]
                token=claim.snapshot.payload.access_token.get_secret_value()
                if claim.snapshot.payload.access_token
                else None,
                refresh_token=claim.snapshot.payload.refresh_token.get_secret_value()
                if claim.snapshot.payload.refresh_token
                else None,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=self.settings.google_client_id,
                client_secret=self.settings.google_client_secret,
                scopes=claim.snapshot.record.scopes.split(),
            )
            requester = SingleRefreshRequest()
            try:
                self._on_loop(self._submit(claim))  # committed BEFORE any Google refresh I/O
                native.refresh(requester)  # type: ignore[no-untyped-call]
                current = self._on_loop(self._complete(claim, native))
            except Exception as exc:
                category = failure_category(exc)
                try:
                    self._on_loop(
                        self._fail(
                            claim, category == "reauthorization_required", not requester.attempted
                        )
                    )
                except Exception:
                    pass  # persisted claim itself prevents unsafe reuse if recovery storage failed
                raise DriveClientError(
                    "Google refresh failed; try later or reconnect.", category=category
                ) from None
            finally:
                requester.close()
            assert (
                current.payload.access_token is not None and current.record.token_expiry is not None
            )
            return (
                current.payload.access_token.get_secret_value(),
                current.record.token_expiry.astimezone(UTC).replace(tzinfo=None),
            )

        return GoogleDriveClient(
            DriveTokens(
                payload.access_token.get_secret_value(),
                None,
                snapshot.record.token_expiry,
                snapshot.record.scopes,
            ),
            settings=self.settings,
            refresh_handler=refresh_handler,
        )
