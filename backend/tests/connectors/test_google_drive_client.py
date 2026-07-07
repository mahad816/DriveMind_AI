"""Mocked tests for the read-only Google Drive client (Phase 3 Milestone 3).

No live Google API calls are made: a fake Drive service is injected and token
refresh is exercised by patching credential validity.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from googleapiclient.errors import HttpError

from app.connectors.google_drive.client import (
    DriveClientError,
    DriveFileMetadata,
    DriveTokens,
    GoogleDriveClient,
)
from app.connectors.google_drive.constants import (
    GOOGLE_FOLDER_MIME,
    PDF_MIME,
    TXT_MIME,
    is_supported_mime_type,
)

FAKE_SETTINGS = MagicMock(
    google_client_id="client-id",
    google_client_secret="client-secret",
)


def _tokens(expiry: datetime | None = None) -> DriveTokens:
    return DriveTokens(
        access_token="access-token",
        refresh_token="refresh-token",
        token_expiry=expiry or datetime.now(UTC) + timedelta(hours=1),
        scopes="https://www.googleapis.com/auth/drive.readonly",
    )


class FakeFilesResource:
    """Fake Drive ``files()`` resource returning queued list/get responses."""

    def __init__(
        self,
        list_pages: list[dict[str, Any]] | None = None,
        get_payload: dict[str, Any] | None = None,
    ) -> None:
        self._list_pages = list_pages or []
        self._get_payload = get_payload
        self.list_calls: list[dict[str, Any]] = []

    def list(self, **kwargs: Any) -> "FakeRequest":
        self.list_calls.append(kwargs)
        index = len(self.list_calls) - 1
        page = self._list_pages[index] if index < len(self._list_pages) else {"files": []}
        return FakeRequest(page)

    def get(self, **kwargs: Any) -> "FakeRequest":
        return FakeRequest(self._get_payload or {})


class FakeRequest:
    def __init__(self, result: dict[str, Any]) -> None:
        self._result = result

    def execute(self) -> dict[str, Any]:
        return self._result


class FakeService:
    def __init__(self, files_resource: FakeFilesResource) -> None:
        self._files_resource = files_resource

    def files(self) -> FakeFilesResource:
        return self._files_resource


def _client(files_resource: FakeFilesResource, **kwargs: Any) -> GoogleDriveClient:
    return GoogleDriveClient(
        tokens=_tokens(),
        settings=FAKE_SETTINGS,
        service=FakeService(files_resource),
        **kwargs,
    )


def test_is_supported_mime_type() -> None:
    assert is_supported_mime_type(PDF_MIME) is True
    assert is_supported_mime_type(TXT_MIME) is True
    assert is_supported_mime_type(GOOGLE_FOLDER_MIME) is False
    assert is_supported_mime_type(None) is False


def test_list_files_filters_unsupported_mime_types() -> None:
    files_resource = FakeFilesResource(
        list_pages=[
            {
                "files": [
                    {"id": "1", "name": "doc.pdf", "mimeType": PDF_MIME},
                    {"id": "2", "name": "folder", "mimeType": GOOGLE_FOLDER_MIME},
                    {"id": "3", "name": "notes.txt", "mimeType": TXT_MIME},
                ]
            }
        ]
    )
    client = _client(files_resource)

    results = client.list_files()

    assert [f.id for f in results] == ["1", "3"]
    assert all(isinstance(f, DriveFileMetadata) for f in results)


def test_list_files_can_include_unsupported_when_requested() -> None:
    files_resource = FakeFilesResource(
        list_pages=[
            {
                "files": [
                    {"id": "1", "name": "doc.pdf", "mimeType": PDF_MIME},
                    {"id": "2", "name": "folder", "mimeType": GOOGLE_FOLDER_MIME},
                ]
            }
        ]
    )
    client = _client(files_resource)

    results = client.list_files(supported_only=False)

    assert [f.id for f in results] == ["1", "2"]


def test_list_files_follows_pagination() -> None:
    files_resource = FakeFilesResource(
        list_pages=[
            {
                "files": [{"id": "1", "name": "a.pdf", "mimeType": PDF_MIME}],
                "nextPageToken": "page-2",
            },
            {"files": [{"id": "2", "name": "b.txt", "mimeType": TXT_MIME}]},
        ]
    )
    client = _client(files_resource)

    results = client.list_files()

    assert [f.id for f in results] == ["1", "2"]
    assert len(files_resource.list_calls) == 2
    assert files_resource.list_calls[0]["pageToken"] is None
    assert files_resource.list_calls[1]["pageToken"] == "page-2"


def test_list_files_clamps_page_size() -> None:
    files_resource = FakeFilesResource(list_pages=[{"files": []}])
    client = _client(files_resource)

    client.list_files(page_size=999999)

    assert files_resource.list_calls[0]["pageSize"] == 1000


def test_get_file_metadata_parses_payload() -> None:
    files_resource = FakeFilesResource(
        get_payload={
            "id": "abc",
            "name": "resume.pdf",
            "mimeType": PDF_MIME,
            "modifiedTime": "2026-07-07T10:00:00.000Z",
            "size": "2048",
            "parents": ["root"],
            "webViewLink": "https://drive.example/abc",
            "md5Checksum": "hash",
        }
    )
    client = _client(files_resource)

    meta = client.get_file_metadata("abc")

    assert meta.id == "abc"
    assert meta.name == "resume.pdf"
    assert meta.size == 2048
    assert meta.parents == ["root"]
    assert meta.web_view_link == "https://drive.example/abc"


def test_get_file_metadata_requires_file_id() -> None:
    client = _client(FakeFilesResource())
    with pytest.raises(DriveClientError, match="file_id is required"):
        client.get_file_metadata("")


def test_list_files_wraps_http_error() -> None:
    files_resource = MagicMock()
    resp = MagicMock(status=403, reason="Forbidden")
    files_resource.files.return_value.list.side_effect = HttpError(resp, b"denied")
    client = GoogleDriveClient(
        tokens=_tokens(),
        settings=FAKE_SETTINGS,
        service=files_resource,
    )
    with pytest.raises(DriveClientError, match="list_files request failed"):
        client.list_files()


def test_build_credentials_requires_a_token() -> None:
    tokens = DriveTokens(access_token="", refresh_token=None, token_expiry=None, scopes="")
    client = GoogleDriveClient(tokens=tokens, settings=FAKE_SETTINGS)
    with pytest.raises(DriveClientError, match="No stored Google OAuth token"):
        client._build_credentials()


def test_refresh_invoked_and_persists_new_token() -> None:
    expired = datetime.now(UTC) - timedelta(hours=1)
    persisted: list[DriveTokens] = []

    client = GoogleDriveClient(
        tokens=_tokens(expiry=expired),
        settings=FAKE_SETTINGS,
        on_token_refresh=persisted.append,
        service=FakeService(FakeFilesResource(list_pages=[{"files": []}])),
    )

    def fake_refresh(self: Any, request: Any) -> None:
        self.token = "new-access-token"
        self.expiry = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)

    with patch(
        "app.connectors.google_drive.client.Credentials.refresh",
        new=fake_refresh,
    ):
        client._ensure_credentials()

    assert len(persisted) == 1
    assert persisted[0].access_token == "new-access-token"


def test_refresh_error_is_wrapped() -> None:
    expired = datetime.now(UTC) - timedelta(hours=1)
    client = GoogleDriveClient(
        tokens=_tokens(expiry=expired),
        settings=FAKE_SETTINGS,
    )

    def boom(self: Any, request: Any) -> None:
        raise RuntimeError("network down")

    with patch(
        "app.connectors.google_drive.client.Credentials.refresh",
        new=boom,
    ):
        with pytest.raises(DriveClientError, match="Failed to refresh"):
            client._ensure_credentials()
