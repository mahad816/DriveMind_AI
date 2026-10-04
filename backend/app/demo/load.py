"""Manual offline corpus loader: python -m app.demo.load --confirm-isolated-demo-storage."""

import argparse
import asyncio
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.enums import DriveFileStatus
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.db.models.user import User
from app.demo.service import DemoCorpusError, DemoCorpusService
from app.services.indexing_service import IndexBuildResult, IndexingService
from app.services.user_resolution import resolve_active_user


async def load_corpus(
    db: AsyncSession, settings: Settings, *, confirmed_isolated: bool = False
) -> IndexBuildResult:
    """Load only approved text, then use the existing chunk/FTS/embedding/index builder.

    Re-runs preserve document IDs and unchanged chunk/vector IDs. Never clear storage.
    Existing unapproved data causes refusal before any writes.
    """
    if not settings.demo_mode or not confirmed_isolated:
        raise DemoCorpusError("Loading requires demo mode and confirmed isolated demo storage")
    try:
        user_id = UUID(settings.demo_user_id.strip())
    except ValueError as exc:
        raise DemoCorpusError("Loading requires a valid DEMO_USER_ID") from exc
    service = DemoCorpusService(db, settings)
    samples = {
        entry.id: service.manifest.read_sample(entry.filename) for entry in service.manifest.files
    }
    files, documents, chunks = await service.inspect_database(user_id)
    await service.inspect_vectors(chunks=chunks)
    user = await db.get(User, user_id)
    email = f"demo-{user_id}@example.invalid"
    google_id = f"demo:{user_id}"
    if user is not None and (user.email != email or user.google_id != google_id):
        raise DemoCorpusError("Refusing to reuse a normal account as the demo identity")
    if user is None:
        db.add(User(id=user_id, email=email, google_id=google_id))
        await db.flush()
    user = await resolve_active_user(db, settings)
    files_by_id = {file.id: file for file in files}
    documents_by_id = {document.id: document for document in documents}
    for entry in service.manifest.files:
        file = files_by_id.get(entry.id)
        if file is None:
            file = DriveFile(
                id=entry.id,
                user_id=user.id,
                drive_file_id=entry.external_id,
                name=entry.filename,
                mime_type="text/plain",
                folder_path="/HarborDesk samples",
                modified_at=service.manifest.modified_at,
                status=DriveFileStatus.INDEXING,
            )
            db.add(file)
        else:
            file.status = DriveFileStatus.INDEXING
        if entry.document_id not in documents_by_id:
            db.add(
                Document(
                    id=entry.document_id,
                    drive_file_id=entry.id,
                    extracted_text=samples[entry.id],
                    extracted_text_hash=entry.sha256,
                )
            )
    await db.commit()
    result = await IndexingService(db, settings).build_index(user_id=user.id)
    if result.failed or result.skipped or not await service.is_ready():
        raise DemoCorpusError("Demo index is incomplete; inspect the index job and retry offline")
    return result


async def _run() -> None:
    # Import sessions only after CLI confirmation; --help does not initialize storage.
    from app.db.session import SessionLocal

    async with SessionLocal() as db:
        result = await load_corpus(db, get_settings(), confirmed_isolated=True)
    print(f"Demo index ready: {result.total} files, {result.embedded} new vectors")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-isolated-demo-storage", action="store_true")
    args = parser.parse_args()
    if not args.confirm_isolated_demo_storage:
        parser.error("Confirm dedicated demo PostgreSQL and Qdrant storage before loading")
    asyncio.run(_run())


if __name__ == "__main__":
    main()
