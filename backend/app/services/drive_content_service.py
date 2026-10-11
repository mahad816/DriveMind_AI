"""Drive file content service — export/download supported files for ingestion."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.google_drive.client import (
    DriveClientError,
    GoogleDriveClient,
)
from app.connectors.google_drive.constants import is_supported_mime_type, output_content_mime_type
from app.services.google_credential_service import GoogleCredentialService
from app.services.google_credential_repository import CredentialSnapshot
from app.core.config import Settings, get_settings
from app.db.models.drive_file import DriveFile
from app.db.models.google_oauth_token import GoogleOAuthToken
from app.db.models.user import User
from app.demo.service import DemoCorpusService
from app.services.user_resolution import resolve_active_user


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

    async def _load_oauth_token(self, user_id: uuid.UUID) -> CredentialSnapshot:
        self._credential_service = GoogleCredentialService(self.db, self.settings)
        return await self._credential_service.load(user_id)

    def _build_drive_client(self, snapshot: CredentialSnapshot) -> GoogleDriveClient:
        return self._credential_service.client(snapshot)

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
        if self.settings.demo_mode:
            user = await resolve_active_user(self.db, self.settings, user_id)
            files, documents, _ = await DemoCorpusService(self.db, self.settings).inspect_database(
                user.id
            )
            file = next((file for file in files if file.id == file_id), None)
            document = next((doc for doc in documents if doc.drive_file_id == file_id), None)
            if file is None or document is None:
                raise ValueError("Synced file not found")
            return DriveFileContent(
                data=document.extracted_text.encode("utf-8"),
                mime_type="text/plain",
                filename=file.name,
                drive_file_id=file.drive_file_id,
            )
        user = await self._resolve_user(user_id)
        drive_file = await self._get_synced_file(user.id, file_id)
        token_row = await self._load_oauth_token(user.id)

        client = self._build_drive_client(token_row)
        # Credential refresh owns independent sessions. A content read must
        # never commit unrelated writes accumulated by its caller.

        try:
            data = await asyncio.to_thread(
                client.get_file_content,
                drive_file.drive_file_id,
                drive_file.mime_type,
            )
        except DriveClientError:
            raise

        return DriveFileContent(
            data=data,
            mime_type=output_content_mime_type(drive_file.mime_type),
            filename=drive_file.name,
            drive_file_id=drive_file.drive_file_id,
        )
