"""Read-only verification of the isolated, approved sample index."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.enums import DriveFileStatus
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.db.models.google_oauth_token import GoogleOAuthToken
from app.db.models.user import User
from app.demo.manifest import load_manifest
from app.embeddings.qdrant_connection import create_qdrant_client
from app.ingestion.chunking import chunk_text
from app.ingestion.hash_util import compute_extracted_text_hash
from app.services.user_resolution import resolve_active_user


class DemoCorpusError(ValueError):
    """The configured demo datastore cannot safely serve approved samples."""


class DemoCorpusService:
    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        if (
            settings.database_url == Settings.model_fields["database_url"].default
            or settings.qdrant_collection == Settings.model_fields["qdrant_collection"].default
            or not settings.qdrant_collection.strip()
        ):
            raise DemoCorpusError("Explicit dedicated demo database and collection are required")
        self.manifest = load_manifest()

    async def inspect_database(
        self, user_id: UUID
    ) -> tuple[list[DriveFile], list[Document], list[Chunk]]:
        """Reject owner/mixed data before serving or modifying a demo datastore."""
        users = list((await self.db.scalars(select(User))).all())
        if any(user.id != user_id for user in users):
            raise DemoCorpusError("Demo storage contains an unexpected user")
        if await self.db.scalar(select(GoogleOAuthToken.id).limit(1)) is not None:
            raise DemoCorpusError("Demo storage must not contain OAuth tokens")
        files = list((await self.db.scalars(select(DriveFile))).all())
        entries = {entry.id: entry for entry in self.manifest.files}
        for file in files:
            entry = entries.get(file.id)
            if entry is None or (
                file.user_id != user_id
                or file.name != entry.filename
                or file.drive_file_id != entry.external_id
                or file.mime_type != "text/plain"
                or file.folder_path != "/HarborDesk samples"
            ):
                raise DemoCorpusError("Demo storage contains an unapproved file")
        documents = list((await self.db.scalars(select(Document))).all())
        chunks = list((await self.db.scalars(select(Chunk))).all())
        documents_by_id = {document.id: document for document in documents}
        file_ids = {file.id for file in files}
        for document in documents:
            entry = entries.get(document.drive_file_id)
            if (
                entry is None
                or document.drive_file_id not in file_ids
                or (
                    document.id != entry.document_id
                    or document.extracted_text_hash != entry.sha256
                    or compute_extracted_text_hash(document.extracted_text) != entry.sha256
                )
            ):
                raise DemoCorpusError("Demo storage contains unapproved document content")
        for chunk in chunks:
            chunk_document = documents_by_id.get(chunk.document_id)
            if chunk_document is None:
                raise DemoCorpusError("Demo storage contains an unapproved chunk")
            expected = chunk_text(chunk_document.extracted_text)
            if not 0 <= chunk.chunk_index < len(expected) or (
                chunk.text != expected[chunk.chunk_index].text
                or chunk.metadata_json.get("extracted_text_hash")
                != chunk_document.extracted_text_hash
            ):
                raise DemoCorpusError("Demo storage contains unapproved chunk content")
        return files, documents, chunks

    async def inspect_vectors(self, *, chunks: list[Chunk]) -> bool:
        """Reject foreign points; return whether every PostgreSQL chunk has a vector."""
        client = create_qdrant_client(self.settings)
        expected = {str(chunk.id): chunk for chunk in chunks}
        documents = {str(entry.document_id): entry for entry in self.manifest.files}
        seen: set[str] = set()
        try:
            if not await client.collection_exists(self.settings.qdrant_collection):
                return False
            offset = None
            while True:
                records, offset = await client.scroll(
                    collection_name=self.settings.qdrant_collection,
                    limit=100,
                    offset=offset,
                    with_vectors=False,
                    with_payload=True,
                )
                for record in records:
                    chunk = expected.get(str(record.id))
                    entry = documents.get(str(chunk.document_id)) if chunk else None
                    payload = record.payload or {}
                    if entry is None or (
                        payload.get("chunk_id") != str(record.id)
                        or payload.get("drive_file_id") != str(entry.id)
                        or payload.get("extracted_text_hash") != entry.sha256
                    ):
                        raise DemoCorpusError("Demo vector storage contains an unapproved point")
                    seen.add(str(record.id))
                if offset is None:
                    break
            return bool(expected) and seen == set(expected)
        finally:
            await client.close()

    async def is_ready(self) -> bool:
        user = await resolve_active_user(self.db, self.settings)
        files, documents, chunks = await self.inspect_database(user.id)
        vectors_ready = await self.inspect_vectors(chunks=chunks)
        return (
            len(files) == len(self.manifest.files)
            and len(documents) == len(files)
            and all(file.status == DriveFileStatus.INDEXED for file in files)
            and all(
                {chunk.chunk_index for chunk in chunks if chunk.document_id == doc.id}
                == set(range(len(chunk_text(doc.extracted_text))))
                for doc in documents
            )
            and vectors_ready
        )
