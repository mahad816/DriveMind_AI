"""Direct retrieval for questions about a specific file by name.

When the user asks ``Tell me about "HI"``, hybrid vector search often returns
irrelevant chunks (many documents mention "hi").  This module resolves the
named file in PostgreSQL and returns **all** of its chunks for grounded answers.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.db.models.google_oauth_token import GoogleOAuthToken
from app.db.models.user import User
from app.retrieval.filename_targets import extract_filename_targets, filename_matches_target
from app.retrieval.types import RetrievedChunk


@dataclass(frozen=True)
class FileTargetResult:
    """Result of resolving and loading chunks for named file targets."""

    files: list[DriveFile]
    chunks: list[RetrievedChunk]
    targets: list[str]

    @property
    def found(self) -> bool:
        return bool(self.files and self.chunks)

    @property
    def not_indexed(self) -> bool:
        """True when the file exists but has no searchable chunks yet."""
        return bool(self.files) and not self.chunks


class FileTargetRetriever:
    """Load all chunks for files explicitly named in the user's question."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def search(self, question: str, user_id: uuid.UUID | None = None) -> FileTargetResult:
        """Resolve filename targets and hydrate all chunks for matching files."""
        targets = extract_filename_targets(question)
        if not targets:
            return FileTargetResult(files=[], chunks=[], targets=[])

        user = await self._resolve_user(user_id)
        files = await self._resolve_files(user.id, targets)
        if not files:
            return FileTargetResult(files=[], chunks=[], targets=targets)

        chunks = await self._load_chunks_for_files(files)
        return FileTargetResult(files=files, chunks=chunks, targets=targets)

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

    async def _resolve_files(
        self,
        user_id: uuid.UUID,
        targets: list[str],
    ) -> list[DriveFile]:
        """Resolve drive files for each target — exact name match first."""
        resolved: list[DriveFile] = []
        seen_ids: set[uuid.UUID] = set()

        for target in targets:
            file_row = await self._resolve_single_target(user_id, target)
            if file_row is not None and file_row.id not in seen_ids:
                seen_ids.add(file_row.id)
                resolved.append(file_row)

        return resolved

    async def _resolve_single_target(
        self,
        user_id: uuid.UUID,
        target: str,
    ) -> DriveFile | None:
        """Find one drive file for a target name."""
        normalized = target.strip()
        if not normalized:
            return None

        # 1. Exact case-insensitive name match (handles "HI", "Far611", etc.)
        exact = await self.db.scalar(
            select(DriveFile).where(
                DriveFile.user_id == user_id,
                func.lower(DriveFile.name) == normalized.lower(),
            )
        )
        if exact is not None:
            return exact

        # 2. Match base name without extension (Resume.pdf ↔ Resume)
        target_base = normalized.rsplit(".", 1)[0] if "." in normalized else normalized
        if target_base != normalized:
            by_base = await self.db.scalar(
                select(DriveFile).where(
                    DriveFile.user_id == user_id,
                    func.lower(DriveFile.name) == target_base.lower(),
                )
            )
            if by_base is not None:
                return by_base

        # 3. Substring match only when it yields a single unambiguous file
        candidates = list(
            (
                await self.db.scalars(
                    select(DriveFile)
                    .where(
                        DriveFile.user_id == user_id,
                        or_(
                            DriveFile.name.ilike(normalized),
                            DriveFile.name.ilike(f"%{normalized}%"),
                        ),
                    )
                    .order_by(DriveFile.modified_at.desc())
                    .limit(5)
                )
            ).all()
        )
        if len(candidates) == 1:
            return candidates[0]

        # 4. Pick best fuzzy match by filename_matches_target
        for candidate in candidates:
            if filename_matches_target(candidate.name, normalized):
                return candidate

        return None

    async def _load_chunks_for_files(self, files: list[DriveFile]) -> list[RetrievedChunk]:
        file_ids = [f.id for f in files]
        result = await self.db.scalars(
            select(Chunk)
            .join(Document, Chunk.document_id == Document.id)
            .where(Document.drive_file_id.in_(file_ids))
            .options(selectinload(Chunk.document).selectinload(Document.drive_file))
            .order_by(Document.drive_file_id, Chunk.chunk_index.asc())
        )
        chunks = list(result.all())

        retrieved: list[RetrievedChunk] = []
        for chunk in chunks:
            document = chunk.document
            drive_file = document.drive_file if document is not None else None
            if document is None or drive_file is None:
                continue
            retrieved.append(
                RetrievedChunk(
                    chunk_id=chunk.id,
                    document_id=document.id,
                    drive_file_id=drive_file.id,
                    filename=drive_file.name,
                    mime_type=drive_file.mime_type,
                    modified_at=drive_file.modified_at,
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    score=1.0,
                    primary_source="keyword",
                    source_scores={"keyword": 1.0},
                )
            )
        return retrieved
