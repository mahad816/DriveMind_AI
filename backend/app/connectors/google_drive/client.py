"""Read-only Google Drive API client built from stored OAuth tokens.

This connector only reads Drive metadata. It never mutates, exports, or deletes
files. Higher-level sync and download logic lives in later milestones/services.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, cast

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.connectors.google_drive.constants import (
    DEFAULT_LIST_QUERY,
    DEFAULT_PAGE_SIZE,
    FILE_FIELDS,
    LIST_FILES_FIELDS,
    MAX_PAGE_SIZE,
    is_supported_mime_type,
)
from app.core.config import Settings, get_settings

GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"


class DriveClientError(RuntimeError):
    """Raised when the Drive API client cannot complete an operation."""


@dataclass
class DriveTokens:
    """Minimal OAuth token snapshot needed to build Drive credentials."""

    access_token: str
    refresh_token: str | None
    token_expiry: datetime | None
    scopes: str


@dataclass
class DriveFileMetadata:
    """Normalized subset of Google Drive file metadata used by DriveMind."""

    id: str
    name: str
    mime_type: str
    modified_time: str | None = None
    created_time: str | None = None
    size: int | None = None
    parents: list[str] = field(default_factory=list)
    web_view_link: str | None = None
    md5_checksum: str | None = None

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> "DriveFileMetadata":
        """Build metadata from a raw Drive API file resource."""
        raw_size = payload.get("size")
        size = int(raw_size) if raw_size is not None else None
        return cls(
            id=cast(str, payload["id"]),
            name=cast(str, payload.get("name", "")),
            mime_type=cast(str, payload.get("mimeType", "")),
            modified_time=payload.get("modifiedTime"),
            created_time=payload.get("createdTime"),
            size=size,
            parents=list(payload.get("parents", [])),
            web_view_link=payload.get("webViewLink"),
            md5_checksum=payload.get("md5Checksum"),
        )


class TokenPersister(Protocol):
    """Callback invoked when credentials are refreshed to a new access token."""

    def __call__(self, tokens: DriveTokens) -> None: ...


class GoogleDriveClient:
    """Authenticated, read-only wrapper around the Google Drive v3 API.

    Credentials are constructed from stored OAuth tokens. When the access token
    is expired and a refresh token is available, the client refreshes it and
    invokes an optional ``on_token_refresh`` callback so callers can persist the
    new access token/expiry.
    """

    def __init__(
        self,
        tokens: DriveTokens,
        settings: Settings | None = None,
        on_token_refresh: TokenPersister | None = None,
        service: Any | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._tokens = tokens
        self._on_token_refresh = on_token_refresh
        self._service = service
        self._credentials: Credentials | None = None

    def _build_credentials(self) -> Credentials:
        if not self._tokens.access_token and not self._tokens.refresh_token:
            raise DriveClientError("No stored Google OAuth token available")
        return Credentials(  # type: ignore[no-untyped-call]
            token=self._tokens.access_token or None,
            refresh_token=self._tokens.refresh_token,
            token_uri=GOOGLE_TOKEN_URI,
            client_id=self._settings.google_client_id or None,
            client_secret=self._settings.google_client_secret or None,
            scopes=self._tokens.scopes.split() if self._tokens.scopes else None,
            expiry=self._strip_tzinfo(self._tokens.token_expiry),
        )

    @staticmethod
    def _strip_tzinfo(expiry: datetime | None) -> datetime | None:
        # google-auth stores/compares expiry as naive UTC.
        if expiry is not None and expiry.tzinfo is not None:
            return expiry.replace(tzinfo=None)
        return expiry

    def _ensure_credentials(self) -> Credentials:
        if self._credentials is None:
            self._credentials = self._build_credentials()
        credentials = self._credentials
        if not credentials.valid and credentials.expired and credentials.refresh_token:
            self._refresh(credentials)
        return credentials

    def _refresh(self, credentials: Credentials) -> None:
        try:
            credentials.refresh(Request())  # type: ignore[no-untyped-call]
        except Exception as exc:  # google-auth raises RefreshError subclasses
            raise DriveClientError(f"Failed to refresh Google OAuth token: {exc}") from exc
        self._tokens = DriveTokens(
            access_token=cast(str, credentials.token),
            refresh_token=credentials.refresh_token or self._tokens.refresh_token,
            token_expiry=credentials.expiry,
            scopes=" ".join(credentials.scopes) if credentials.scopes else self._tokens.scopes,
        )
        if self._on_token_refresh is not None:
            self._on_token_refresh(self._tokens)

    def _get_service(self) -> Any:
        if self._service is None:
            credentials = self._ensure_credentials()
            self._service = build(
                "drive",
                "v3",
                credentials=credentials,
                cache_discovery=False,
            )
        return self._service

    @staticmethod
    def _clamp_page_size(page_size: int) -> int:
        if page_size < 1:
            return DEFAULT_PAGE_SIZE
        return min(page_size, MAX_PAGE_SIZE)

    def iter_files(
        self,
        query: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        supported_only: bool = True,
    ) -> Iterator[DriveFileMetadata]:
        """Yield Drive files across all pages, filtering unsupported MIME types.

        Args:
            query: Optional Drive query string; defaults to non-folder, non-trashed.
            page_size: Files per API page (clamped to Drive limits).
            supported_only: When True, skip files whose MIME type is not supported.
        """
        service = self._get_service()
        page_token: str | None = None
        effective_query = query or DEFAULT_LIST_QUERY
        clamped_size = self._clamp_page_size(page_size)

        while True:
            try:
                response = (
                    service.files()
                    .list(
                        q=effective_query,
                        pageSize=clamped_size,
                        fields=LIST_FILES_FIELDS,
                        pageToken=page_token,
                        spaces="drive",
                    )
                    .execute()
                )
            except HttpError as exc:
                raise DriveClientError(f"Drive list_files request failed: {exc}") from exc

            for payload in response.get("files", []):
                if supported_only and not is_supported_mime_type(payload.get("mimeType")):
                    continue
                yield DriveFileMetadata.from_api(payload)

            page_token = response.get("nextPageToken")
            if not page_token:
                break

    def list_files(
        self,
        query: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        supported_only: bool = True,
    ) -> list[DriveFileMetadata]:
        """Return all matching Drive files as a list (pagination handled internally)."""
        return list(
            self.iter_files(
                query=query,
                page_size=page_size,
                supported_only=supported_only,
            )
        )

    def get_file_metadata(self, file_id: str) -> DriveFileMetadata:
        """Fetch metadata for a single Drive file by ID."""
        if not file_id:
            raise DriveClientError("file_id is required")
        service = self._get_service()
        try:
            payload = (
                service.files()
                .get(fileId=file_id, fields=FILE_FIELDS)
                .execute()
            )
        except HttpError as exc:
            raise DriveClientError(f"Drive get_file_metadata request failed: {exc}") from exc
        return DriveFileMetadata.from_api(payload)
