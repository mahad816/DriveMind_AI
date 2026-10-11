"""Synthetic SDK failures must not reach HTTP or server traceback diagnostics."""

import asyncio
import logging
import traceback
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import h11
import pytest
from google.auth.exceptions import RefreshError
from uvicorn._types import ASGI3Application
from uvicorn.protocols.http.h11_impl import RequestResponseCycle

from app.api.files import get_drive_content_service
from app.api.dependencies import require_resource_user
from app.connectors.google_drive.client import DriveClientError, DriveTokens, GoogleDriveClient
from app.core.credential_diagnostics import failure_category
from app.core.public_safety import PUBLIC_ERROR
from app.db.enums import IndexingJobStatus
from app.main import create_app
from app.services.drive_content_service import DriveContentService
from app.services.drive_sync_service import DriveSyncService
from app.services.google_oauth_service import GoogleOAuthService

SECRETS = (
    "synthetic-access-CONSTRUCTION-091",
    "synthetic-refresh-CONSTRUCTION-092",
    "synthetic-code-CONSTRUCTION-093",
    "synthetic-key-CONSTRUCTION-094",
    "synthetic-session-CONSTRUCTION-095",
)
RAW = " ".join(SECRETS)


def clean(value: str) -> None:
    assert all(secret not in value for secret in SECRETS)


def drive_client() -> GoogleDriveClient:
    return GoogleDriveClient(DriveTokens(SECRETS[0], SECRETS[1], None, "readonly"))


def test_successful_construction_is_reused() -> None:
    client = drive_client()
    credentials, service = MagicMock(), MagicMock()
    with (
        patch.object(client, "_ensure_credentials", return_value=credentials) as ensure,
        patch("app.connectors.google_drive.client.build", return_value=service) as build,
    ):
        assert client._get_service() is service
        assert client._get_service() is service
    ensure.assert_called_once_with()
    build.assert_called_once_with("drive", "v3", credentials=credentials, cache_discovery=False)


@pytest.mark.parametrize(
    "error,category",
    [
        (RuntimeError(RAW), "unexpected_failure"),
        (RefreshError(RAW, {"error": "invalid_grant"}), "reauthorization_required"),
        (TimeoutError(RAW), "temporary_provider_failure"),
    ],
)
@pytest.mark.parametrize("operation", ["metadata", "content", "sync"])
def test_construction_failures_detach_provider_context(
    error: Exception, category: str, operation: str
) -> None:
    client = drive_client()
    with (
        patch.object(client, "_ensure_credentials", return_value=MagicMock()),
        patch("app.connectors.google_drive.client.build", side_effect=error),
    ):
        with pytest.raises(DriveClientError) as caught:
            if operation == "metadata":
                client.get_file_metadata("synthetic-file")
            elif operation == "content":
                client.get_file_content("synthetic-file", "text/plain")
            else:
                client.get_start_page_token()
    assert failure_category(caught.value) == category
    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None
    clean(str(caught.value))
    clean("".join(traceback.format_exception(caught.value)))
    assert client._service is None


@pytest.mark.parametrize(
    "category,error",
    [
        ("temporary_provider_failure", TimeoutError(RAW)),
        ("unexpected_failure", RuntimeError(RAW)),
    ],
)
def test_oauth_profile_construction_is_safe(category: str, error: Exception) -> None:
    service = GoogleOAuthService(MagicMock())
    with patch("app.services.google_oauth_service.build", side_effect=error):
        with pytest.raises(ValueError) as caught:
            service._fetch_google_profile(MagicMock())
    assert failure_category(caught.value) == category
    assert caught.value.__context__ is None
    clean("".join(traceback.format_exception(caught.value)))


@pytest.mark.asyncio
async def test_sync_construction_failure_persists_failed_job(
    caplog: pytest.LogCaptureFixture,
) -> None:
    db = AsyncMock()
    db.add = MagicMock()
    service = DriveSyncService(db, settings=MagicMock(demo_mode=False))
    client = drive_client()
    with (
        patch.object(service, "_resolve_user", return_value=MagicMock(id=uuid4())),
        patch.object(service, "_load_oauth_token", return_value=MagicMock()),
        patch.object(service, "_get_sync_state", return_value=None),
        patch.object(service, "_build_drive_client", return_value=client),
        patch.object(client, "_ensure_credentials", return_value=MagicMock()),
        patch(
            "app.connectors.google_drive.client.build",
            side_effect=RefreshError(RAW, {"error": "invalid_grant"}),
        ),
    ):
        with pytest.raises(DriveClientError) as caught:
            await service.sync_metadata()
    job = db.add.call_args.args[0]
    assert job.status == IndexingJobStatus.FAILED
    assert job.completed_at is not None
    assert "reauthorization_required" in job.error
    assert db.commit.await_count == 2
    clean(job.error)
    clean("".join(traceback.format_exception(caught.value)))
    clean(caplog.text)


@pytest.mark.asyncio
async def test_content_api_under_uvicorn_cycle_has_no_secret_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Exercise the real ASGI app and Uvicorn error logger, without a listening socket."""
    db = AsyncMock()
    service = DriveContentService(db, settings=MagicMock(demo_mode=False))
    client = drive_client()
    app = create_app()
    app.dependency_overrides[get_drive_content_service] = lambda: service
    app.dependency_overrides[require_resource_user] = lambda: uuid4()
    path = f"/api/v1/files/{uuid4()}/content"
    conn = h11.Connection(h11.SERVER)
    conn.receive_data(f"GET {path} HTTP/1.1\r\nHost: testserver\r\n\r\n".encode())
    conn.next_event()
    conn.next_event()
    transport, flow = MagicMock(), MagicMock()
    flow.write_paused = False
    cycle = RequestResponseCycle(
        scope={
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [(b"host", b"testserver")],
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 12345),
        },
        conn=conn,
        transport=transport,
        flow=flow,
        logger=logging.getLogger("uvicorn.error"),
        access_logger=logging.getLogger("uvicorn.access"),
        access_log=False,
        default_headers=[],
        message_event=asyncio.Event(),
        on_response=lambda: None,
    )
    with (
        patch.object(service, "_resolve_user", return_value=MagicMock(id=uuid4())),
        patch.object(
            service,
            "_get_synced_file",
            return_value=MagicMock(drive_file_id="synthetic-file", mime_type="text/plain"),
        ),
        patch.object(service, "_load_oauth_token", return_value=MagicMock()),
        patch.object(service, "_build_drive_client", return_value=client),
        patch.object(client, "_ensure_credentials", return_value=MagicMock()),
        patch(
            "app.connectors.google_drive.client.build",
            side_effect=RefreshError(RAW, {"error": "invalid_grant"}),
        ),
        caplog.at_level(logging.ERROR),
    ):
        await cycle.run_asgi(cast(ASGI3Application, app))
    wire = b"".join(call.args[0] for call in transport.write.call_args_list).decode()
    assert "502 Bad Gateway" in wire
    assert PUBLIC_ERROR in wire
    assert cycle.response_complete
    assert "reauthorization_required" in caplog.text
    assert not any(record.name == "uvicorn.error" for record in caplog.records)
    clean(wire)
    clean(caplog.text)
    assert all(record.exc_info is None for record in caplog.records)
    db.commit.assert_not_awaited()
