"""An isolated, throwaway evaluation target: its own PostgreSQL database and Qdrant collection.

Everything here refuses to touch anything that is not clearly an evaluation store on loopback.
It never deletes or alters existing data; ``setup`` only creates what is missing.
"""

import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.db.enums import DriveFileStatus
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.db.models.user import User
from app.ingestion.hash_util import compute_extracted_text_hash
from app.services.indexing_service import IndexingService

from .corpus import CorpusFile, extract_text

EVAL_DB = "drivemind_eval_v2"
EVAL_COLLECTION = "drivemind_eval_v2"
EVAL_USER_ID = uuid.uuid5(uuid.NAMESPACE_URL, "drivemind-eval-v2/user")
LOOPBACK = {"localhost", "127.0.0.1", "::1"}
BACKEND = Path(__file__).resolve().parents[2]


def admin_url() -> str:
    return os.environ.get(
        "EVAL_ADMIN_DATABASE_URL", "postgresql+asyncpg://postgres:testonly@127.0.0.1:55432/postgres"
    )


def eval_settings(*, chat_model: str | None = None, tool_agent: bool = True) -> Settings:
    base = get_settings()
    url = make_url(admin_url()).set(database=EVAL_DB).render_as_string(hide_password=False)
    settings = base.model_copy(
        update={
            "database_url": url,
            "qdrant_url": "",
            "qdrant_api_key": "",
            "qdrant_host": "127.0.0.1",
            "qdrant_port": int(os.environ.get("EVAL_QDRANT_PORT", "56333")),
            "qdrant_collection": EVAL_COLLECTION,
            "demo_mode": False,
            "debug": False,
            "tool_rag_agent_enabled": tool_agent,
            "agent_graph_enabled": False,
            "hybrid_retrieval_enabled": True,
            **({"chat_model": chat_model} if chat_model else {}),
        }
    )
    assert_safe(settings)
    return settings


def assert_safe(settings: Settings) -> None:
    url = make_url(settings.database_url)
    if (
        url.host not in LOOPBACK
        or not (url.database or "").startswith("drivemind_eval")
        or settings.qdrant_host not in LOOPBACK
        or not settings.qdrant_collection.startswith("drivemind_eval")
        or settings.qdrant_api_key
        or settings.qdrant_url
        or settings.demo_mode
    ):
        raise RuntimeError(
            "Evaluation refuses to run against anything but a loopback drivemind_eval store"
        )


async def ensure_database() -> None:
    engine = create_async_engine(admin_url(), isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": EVAL_DB}
            )
            if not exists:
                await conn.execute(
                    text(f'CREATE DATABASE "{EVAL_DB}"')
                )  # fixed constant, not user input
    finally:
        await engine.dispose()


def migrate(settings: Settings) -> None:
    env = {**os.environ, "DATABASE_URL": settings.database_url}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True
    )


def session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    assert_safe(settings)
    return async_sessionmaker(create_async_engine(settings.database_url), expire_on_commit=False)


def file_id(path: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"drivemind-eval-v2/file/{path}")


async def ingest(settings: Settings, files: list[CorpusFile]) -> dict[str, int]:
    """Create the eval user, one DriveFile + Document per corpus file, then run the real index build."""
    sessions = session_factory(settings)
    modified = datetime(2026, 6, 1, tzinfo=UTC)
    async with sessions() as db:
        if await db.get(User, EVAL_USER_ID) is None:
            db.add(User(id=EVAL_USER_ID, email="eval-v2@example.invalid", google_id="eval:v2"))
            await db.flush()
        known = set(await db.scalars(select(DriveFile.id).where(DriveFile.user_id == EVAL_USER_ID)))
        for file in files:
            fid = file_id(file.path)
            if fid in known:
                continue
            body = extract_text(file)
            db.add(
                DriveFile(
                    id=fid,
                    user_id=EVAL_USER_ID,
                    drive_file_id=f"eval:{file.path}",
                    name=file.name,
                    mime_type=file.mime_type,
                    folder_path=f"/eval/{file.kind}",
                    modified_at=modified,
                    status=DriveFileStatus.INDEXING,
                )
            )
            db.add(
                Document(
                    id=uuid.uuid5(uuid.NAMESPACE_URL, f"drivemind-eval-v2/doc/{file.path}"),
                    drive_file_id=fid,
                    extracted_text=body,
                    extracted_text_hash=compute_extracted_text_hash(body),
                )
            )
        await db.commit()
    async with sessions() as db:
        result = await IndexingService(db, settings).build_index(user_id=EVAL_USER_ID)
    if result.failed or result.skipped:
        raise RuntimeError(
            f"index build incomplete: failed={result.failed} skipped={result.skipped}"
        )
    async with sessions() as db:
        counts = {
            "files": len(
                list(
                    await db.scalars(select(DriveFile.id).where(DriveFile.user_id == EVAL_USER_ID))
                )
            ),
            "embedded_now": result.embedded,
        }
    return counts
