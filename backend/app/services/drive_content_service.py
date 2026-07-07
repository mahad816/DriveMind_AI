"""Drive file content service — export/download supported files for ingestion."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.google_drive.client import (
    DriveClientError,
    DriveTokens,
    GoogleDriveClient,
    TokenPersister,
)
from app.connectors.google_drive.constants import is_supported_mime_type, output_content_mime_type
from app.core.config import Settings, get_settings
from app.db.models.drive_file import DriveFile
from app.db.models.google_oauth_token import GoogleOAuthToken
from app.db.models.user import User


@dataclass
class DriveFileContent:
    """Downloaded or exported file bytes plus response metadata."""

    data: bytes
    mime_type: str
    filename: str
    drive_file_id: str


class DriveContentService:
    """Fetches supported Drive file content using stored OAuth credentials."""

    def __init__(self, db: AsyncSession, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    async def _resolve_user(self, user_id: uuid.UUID | None) -> User:
        if user_id is not None:
            user = await self.db.get(User, user_id)
            if user is None:
                raise ValueError("User not found")
            return user

        token_row = await self.db.scalar(select(GoogleOAuthToken).limit(1))
        if token_row is None:
            raise ValueError("No Google Drive connection found. Complete OAuth first.")
        user = await self.db.get(User, token_row.user_id)
        if user is None:
            raise ValueError("Connected Google account has no user record")
        return user

    async def _load_oauth_token(self, user_id: uuid.UUID) -> GoogleOAuthToken:
        token_row = await self.db.scalar(
            select(GoogleOAuthToken).where(GoogleOAuthToken.user_id == user_id)
        )
        if token_row is None:
            raise ValueError("No Google Drive connection found. Complete OAuth first.")
        return token_row

    def _build_drive_client(
        self,
        token_row: GoogleOAuthToken,
        on_token_refresh: list[DriveTokens],
    ) -> GoogleDriveClient:
        tokens = DriveTokens(
            access_token=token_row.access_token,
            refresh_token=token_row.refresh_token,
            token_expiry=token_row.token_expiry,
            scopes=token_row.scopes,
        )

        def capture_refresh(updated: DriveTokens) -> None:
            on_token_refresh.append(updated)

        return GoogleDriveClient(
            tokens=tokens,
            settings=self.settings,
            on_token_refresh=cast(TokenPersister, capture_refresh),
        )

    async def _persist_refreshed_tokens(
        self,
        token_row: GoogleOAuthToken,
        refreshed: list[DriveTokens],
    ) -> None:
        if not refreshed:
            return
        latest = refreshed[-1]
        token_row.access_token = latest.access_token
        if latest.refresh_token:
            token_row.refresh_token = latest.refresh_token
        token_row.token_expiry = latest.token_expiry
        token_row.scopes = latest.scopes

    async def _get_synced_file(self, user_id: uuid.UUID, file_id: uuid.UUID) -> DriveFile:
        drive_file = await self.db.scalar(
            select(DriveFile).where(DriveFile.id == file_id, DriveFile.user_id == user_id)
        )
        if drive_file is None:
            raise ValueError("Synced file not found")
        if not is_supported_mime_type(drive_file.mime_type):
            raise ValueError(f"Unsupported file type: {drive_file.mime_type}")
        return drive_file

    async def fetch_file_content(
        self,
        file_id: uuid.UUID,
        user_id: uuid.UUID | None = None,
    ) -> DriveFileContent:
        """Export or download content for a synced Drive file."""
        user = await self._resolve_user(user_id)
        drive_file = await self._get_synced_file(user.id, file_id)
        token_row = await self._load_oauth_token(user.id)

        refreshed_tokens: list[DriveTokens] = []
        client = self._build_drive_client(token_row, refreshed_tokens)

        try:
            data = await asyncio.to_thread(
                client.get_file_content,
                drive_file.drive_file_id,
                drive_file.mime_type,
            )
        except DriveClientError:
            raise

        await self._persist_refreshed_tokens(token_row, refreshed_tokens)
        await self.db.commit()

        return DriveFileContent(
            data=data,
            mime_type=output_content_mime_type(drive_file.mime_type),
            filename=drive_file.name,
            drive_file_id=drive_file.drive_file_id,
        )
