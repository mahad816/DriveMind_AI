"""Synthetic-only tests for credential-bearing diagnostics."""

import logging
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError
from sqlalchemy import create_engine, text
from sqlalchemy.exc import StatementError

from app.connectors.google_drive.client import DriveClientError, DriveTokens, GoogleDriveClient
from app.core.credential_diagnostics import failure_category, log_safe_failure
from app.core.public_safety import PUBLIC_ERROR, public_error_detail
from app.db.session import engine
from app.services.google_oauth_service import GoogleOAuthService

SECRETS = (
    "synthetic-access-918",
    "synthetic-refresh-732",
    "synthetic-code-541",
    "synthetic-key-129",
)
RAW = " ".join(SECRETS)


def assert_clean(value: str) -> None:
    assert all(secret not in value for secret in SECRETS)


@pytest.mark.parametrize("debug,demo", [(False, False), (True, False), (False, True)])
def test_public_errors_never_reveal_provider_or_sql_details(
    debug: bool, demo: bool, caplog: pytest.LogCaptureFixture
) -> None:
    error = StatementError(RAW, "INSERT credential", {"token": RAW}, RuntimeError(RAW))
    with patch(
        "app.core.public_safety.get_settings", return_value=MagicMock(debug=debug, demo_mode=demo)
    ):
        assert public_error_detail(error) == PUBLIC_ERROR
    assert_clean(caplog.text)
    assert all(record.exc_info is None for record in caplog.records)


def test_sql_parameters_hidden(caplog: pytest.LogCaptureFixture) -> None:
    assert engine.sync_engine.hide_parameters and not engine.echo
    diagnostic_engine = create_engine("sqlite://", hide_parameters=True, echo=False)
    try:
        with caplog.at_level(logging.INFO, logger="sqlalchemy.engine.Engine"):
            with diagnostic_engine.connect() as connection:
                with pytest.raises(StatementError) as caught:
                    connection.execute(text("SELECT missing_function(:secret)"), {"secret": RAW})
        assert_clean(str(caught.value))
        assert_clean(caplog.text)
    finally:
        diagnostic_engine.dispose()


def test_classification_uses_structured_evidence_only() -> None:
    assert (
        failure_category(RefreshError(RAW, {"error": "invalid_grant"}))
        == "reauthorization_required"
    )
    assert failure_category(RefreshError("invalid_grant " + RAW)) == "unexpected_failure"
    for status, category in [
        (401, "authentication_expired"),
        (403, "unexpected_failure"),
        (503, "temporary_provider_failure"),
    ]:
        assert failure_category(HttpError(MagicMock(status=status), RAW.encode())) == category


def test_oauth_exchange_suppresses_provider_details() -> None:
    service = GoogleOAuthService(db=MagicMock())
    flow = MagicMock()
    flow.fetch_token.side_effect = RuntimeError(RAW)
    with patch.object(service, "_build_flow", return_value=flow):
        with pytest.raises(ValueError) as caught:
            service._fetch_credentials("synthetic-code-541", "verifier")
    assert_clean(str(caught.value))
    assert caught.value.__suppress_context__


def test_drive_refresh_errors_and_representations_are_safe(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tokens = DriveTokens(SECRETS[0], SECRETS[1], None, "readonly")
    assert_clean(repr(tokens))
    client = GoogleDriveClient(tokens)
    credentials = MagicMock()
    credentials.refresh.side_effect = RefreshError(RAW, {"error": "invalid_grant"})
    with pytest.raises(DriveClientError) as caught:
        client._refresh(credentials)
    assert "reauthorization_required" in str(caught.value)
    assert_clean(str(caught.value))
    assert caught.value.__suppress_context__
    log_safe_failure(logging.getLogger(__name__), "Drive refresh", caught.value)
    assert_clean(caplog.text)


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint,status", [("oauth", 503), ("content", 502)])
async def test_credential_api_failures_are_safe(
    async_client: "AsyncClient", caplog: pytest.LogCaptureFixture, endpoint: str, status: int
) -> None:
    from unittest.mock import AsyncMock
    from uuid import uuid4

    from sqlalchemy.exc import SQLAlchemyError

    from app.api.google_session_auth import get_google_session_service
    from app.api.files import get_drive_content_service
    from app.api.dependencies import require_resource_user
    from app.core.config import Settings, get_settings
    from app.main import app

    service = MagicMock()
    if endpoint == "oauth":
        dependency = get_google_session_service
        service.settings = Settings(
            google_application_sessions_enabled=True,
            google_client_id="synthetic-client",
            google_client_secret="synthetic-secret",
            google_session_redirect_uri="http://localhost:3000/api/v1/auth/session/google/callback",
        )
        app.dependency_overrides[get_settings] = lambda: service.settings
        service.callback = AsyncMock(side_effect=SQLAlchemyError(RAW))
        url = "/api/v1/auth/session/google/callback?code=synthetic-code-541&state=state"
    else:
        dependency = get_drive_content_service
        service.fetch_file_content = AsyncMock(side_effect=DriveClientError(RAW))
        url = f"/api/v1/files/{uuid4()}/content"
    app.dependency_overrides[dependency] = lambda: service
    if endpoint == "content":
        app.dependency_overrides[require_resource_user] = lambda: uuid4()
    try:
        response = await async_client.get(url, headers={"Accept": "application/json"})
        assert response.status_code == status
        assert response.json()["detail"] == (
            "Application login is temporarily unavailable." if endpoint == "oauth" else PUBLIC_ERROR
        )
        assert_clean(response.text)
        assert_clean(caplog.text)
    finally:
        app.dependency_overrides.pop(dependency, None)
        app.dependency_overrides.pop(require_resource_user, None)
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_indexing_failure_logs_no_provider_details(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging
    from app.core.credential_diagnostics import log_safe_failure

    log_safe_failure(
        logging.getLogger("app.api.index"), "Indexing storage operation", DriveClientError(RAW)
    )
    assert caplog.records
    assert_clean(caplog.text)
    assert all(record.exc_info is None for record in caplog.records)


def test_implicit_sdk_refresh_failure_is_safe() -> None:
    service = MagicMock()
    service.files.return_value.get.return_value.execute.side_effect = RefreshError(
        RAW, {"error": "invalid_grant"}
    )
    client = GoogleDriveClient(
        DriveTokens(SECRETS[0], SECRETS[1], None, "readonly"), service=service
    )
    with pytest.raises(DriveClientError) as caught:
        client.get_file_metadata("synthetic-file")
    assert_clean(str(caught.value))
    assert failure_category(caught.value) == "reauthorization_required"


@pytest.mark.asyncio
async def test_status_api_returns_safe_new_job_error(async_client: AsyncClient) -> None:
    from datetime import UTC, datetime
    from unittest.mock import AsyncMock
    from uuid import uuid4

    from app.api.index import (
        get_drive_sync_service,
        get_indexing_job_service,
        require_index_read_user,
    )
    from app.core.credential_diagnostics import safe_failure
    from app.db.enums import IndexingJobStatus
    from app.db.models.indexing_job import IndexingJob
    from app.main import app

    job = IndexingJob(
        id=uuid4(),
        user_id=uuid4(),
        status=IndexingJobStatus.FAILED,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        error=safe_failure(RefreshError(RAW, {"error": "invalid_grant"}), "Drive sync"),
    )
    service = MagicMock()
    service.is_connected = AsyncMock(return_value=True)
    jobs = MagicMock()
    jobs.get_job = AsyncMock(return_value=job)
    job.full_sync = job.recovery_required = False
    job.total = job.processed = job.succeeded = job.failed = job.skipped = 0
    app.dependency_overrides[require_index_read_user] = lambda: job.user_id
    app.dependency_overrides[get_indexing_job_service] = lambda: jobs
    app.dependency_overrides[get_drive_sync_service] = lambda: service
    try:
        response = await async_client.get("/api/v1/index/status")
        assert response.status_code == 200
        assert response.json()["job"]["status"] == "failed"
        assert "reauthorization_required" in response.json()["job"]["error"]
        assert_clean(response.text)
    finally:
        app.dependency_overrides.pop(get_drive_sync_service, None)
        app.dependency_overrides.pop(require_index_read_user, None)
        app.dependency_overrides.pop(get_indexing_job_service, None)
