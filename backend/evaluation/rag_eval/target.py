"""An isolated, throwaway evaluation target: its own PostgreSQL database and Qdrant collection.

Everything here refuses to touch anything that is not clearly an evaluation store on loopback.
It never deletes or alters existing data; ``setup`` only creates what is missing.
"""

import os
import re
import subprocess
import sys
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.db.enums import DriveFileStatus
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.db.models.user import User
from app.ingestion.hash_util import compute_extracted_text_hash
from app.ingestion.pipeline_version import EXTRACTION_PIPELINE_VERSION
from app.services.indexing_service import IndexingService

from .corpus import CorpusFile, extract_text

STORE_NAME = re.compile(r"v\d{1,3}")
STORE_PREFIX = "drivemind_eval_"


@dataclass(frozen=True)
class EvalStore:
    """One evaluation namespace: a PostgreSQL database and a Qdrant collection that carry the same name.

    The name is a strict version tag (``v2``, ``v3``, ...), so it can be placed in SQL and URLs safely and a
    database can never be paired with another version's collection.
    """

    name: str

    @classmethod
    def named(cls, name: str) -> "EvalStore":
        if not STORE_NAME.fullmatch(name):
            raise ValueError(
                f"store name {name!r} must look like 'v3' (the letter v and 1 to 3 digits)"
            )
        return cls(name)

    @property
    def database(self) -> str:
        return STORE_PREFIX + self.name

    @property
    def collection(self) -> str:
        return STORE_PREFIX + self.name


# v2 is the earlier evaluation store: it is only ever read or extended by the legacy commands and is never
# rebuilt. The frozen M1 corpus goes into its own store, v3 by default.
LEGACY_STORE = EvalStore.named("v2")
FROZEN_STORE = EvalStore.named("v3")
EVAL_DB = LEGACY_STORE.database
EVAL_COLLECTION = LEGACY_STORE.collection
EVAL_USER_ID = uuid.uuid5(uuid.NAMESPACE_URL, "drivemind-eval-v2/user")
LOOPBACK = {"localhost", "127.0.0.1", "::1"}
BACKEND = Path(__file__).resolve().parents[2]


def admin_url() -> str:
    return os.environ.get(
        "EVAL_ADMIN_DATABASE_URL", "postgresql+asyncpg://postgres:testonly@127.0.0.1:55432/postgres"
    )


# Every setting that can change an answer. The evaluation measures the application's code defaults for
# these (what a rebuilt deployment runs), never whatever the local environment or .env happens to say.
ANSWER_FIELDS = (
    "tool_rag_agent_enabled",
    "agent_graph_enabled",
    "hybrid_retrieval_enabled",
    "claim_check_enabled",
    "claim_check_model",
    "chat_model",
    "embedding_model",
    "retrieval_candidate_k",
    "retrieval_top_k",
    "retrieval_score_threshold",
    "retrieval_relative_threshold",
    "retrieval_name_term_max_files",
    "retrieval_max_chunks_per_file",
    "retrieval_dual_query_enabled",
    "hybrid_rrf_k",
    "hybrid_weight_vector",
    "hybrid_weight_keyword",
    "hybrid_weight_metadata",
    "evidence_min_fusion_score",
    "fts_language",
    "rag_max_context_chars",
    "agent_max_rewrite_attempts",
)


def application_defaults() -> dict[str, Any]:
    """The code default of every answer-relevant setting."""
    return {name: Settings.model_fields[name].get_default() for name in ANSWER_FIELDS}


def store_for(*, frozen: bool, name: str | None = None) -> EvalStore:
    """The store a command works on. Legacy commands use v2; frozen commands use v3 or the store they name,
    and can never select v2."""
    if not frozen:
        if name is not None:
            raise SystemExit(
                "--store only applies together with --frozen; the legacy store is fixed."
            )
        return LEGACY_STORE
    try:
        store = EvalStore.named(name) if name else FROZEN_STORE
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if store == LEGACY_STORE:
        raise SystemExit(
            f"{LEGACY_STORE.database} (v2) is the earlier evaluation store and is never rebuilt; "
            "name a new store, for example --store v3."
        )
    return store


def store_of(settings: Settings) -> EvalStore:
    """The store these settings point at. Refuses a database and a collection from different versions."""
    database = make_url(settings.database_url).database or ""
    if database != settings.qdrant_collection:
        raise RuntimeError(
            f"the PostgreSQL database ({database!r}) and the Qdrant collection "
            f"({settings.qdrant_collection!r}) must be the same evaluation store"
        )
    return EvalStore.named(database.removeprefix(STORE_PREFIX))


def eval_settings(
    *,
    chat_model: str | None = None,
    tool_agent: bool = True,
    store: EvalStore = LEGACY_STORE,
) -> Settings:
    base = get_settings()
    url = make_url(admin_url()).set(database=store.database).render_as_string(hide_password=False)
    settings = base.model_copy(
        update={
            **application_defaults(),
            "database_url": url,
            "qdrant_url": "",
            "qdrant_api_key": "",
            "qdrant_host": "127.0.0.1",
            "qdrant_port": int(os.environ.get("EVAL_QDRANT_PORT", "56333")),
            "qdrant_collection": store.collection,
            "demo_mode": False,
            "debug": False,
            "tool_rag_agent_enabled": tool_agent,
            **({"chat_model": chat_model} if chat_model else {}),
        }
    )
    assert_safe(settings)
    return settings


def assert_safe(settings: Settings) -> None:
    url = make_url(settings.database_url)
    if (url.database or "") != settings.qdrant_collection:
        raise RuntimeError(
            "Evaluation refuses to run unless the PostgreSQL database and the Qdrant collection are "
            "the same evaluation store"
        )
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


async def ensure_database(store: EvalStore = LEGACY_STORE) -> None:
    """Create the store's database if it is missing. Never alters or removes an existing one."""
    engine = create_async_engine(admin_url(), isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": store.database}
            )
            if not exists:
                await conn.execute(
                    text(f'CREATE DATABASE "{store.database}"')
                )  # the name is validated by EvalStore.named: "drivemind_eval_v" and digits only
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


def document_id(path: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"drivemind-eval-v2/doc/{path}")


def refresh_stored(drive_file: DriveFile, document: Document, body: str) -> str:
    """Bring one stored file up to date with the text the current pipeline extracts.

    Returns what happened: ``"replaced"`` (text differs: the file is queued for chunking and embedding
    again), ``"version"`` (same text, only the pipeline version moves), ``"queued"`` (up to date but never
    finished: queued again) or ``"kept"``. The same rule the product applies when it re-reads a file.
    """
    if document.extracted_text != body:
        document.extracted_text = body
        document.extracted_text_hash = compute_extracted_text_hash(body)
        document.pipeline_version = EXTRACTION_PIPELINE_VERSION
        drive_file.status = DriveFileStatus.INDEXING
        return "replaced"
    outcome = "kept"
    if document.pipeline_version != EXTRACTION_PIPELINE_VERSION:
        document.pipeline_version = EXTRACTION_PIPELINE_VERSION
        outcome = "version"
    if drive_file.status != DriveFileStatus.INDEXED:
        drive_file.status = DriveFileStatus.INDEXING
        outcome = "queued"
    return outcome


async def ingest(
    settings: Settings,
    files: list[CorpusFile],
    *,
    texts: Mapping[str, str] | None = None,
    refresh_stale: bool = False,
) -> dict[str, int]:
    """Create the eval user, one DriveFile + Document per corpus file, then run the real index build.

    ``texts`` are text already extracted from the original files (path -> text), so nothing is read twice.
    A file that is already stored is skipped, as it always was, unless ``refresh_stale`` is set: then its
    document is compared with the text the current pipeline extracts and refreshed where it differs or was
    made by an older pipeline. Refreshing is refused on the legacy store, which is never rewritten.
    """
    if refresh_stale and store_of(settings) == LEGACY_STORE:
        raise RuntimeError(
            f"refusing to refresh the legacy evaluation store {LEGACY_STORE.database}: it is never rewritten"
        )
    sessions = session_factory(settings)
    modified = datetime(2026, 6, 1, tzinfo=UTC)
    refreshed = 0
    async with sessions() as db:
        if await db.get(User, EVAL_USER_ID) is None:
            db.add(User(id=EVAL_USER_ID, email="eval-v2@example.invalid", google_id="eval:v2"))
            await db.flush()
        known = set(await db.scalars(select(DriveFile.id).where(DriveFile.user_id == EVAL_USER_ID)))
        for file in files:
            fid = file_id(file.path)
            if fid in known and not refresh_stale:
                continue
            body = texts[file.path] if texts is not None else extract_text(file)
            if fid in known:
                drive_file = await db.get(DriveFile, fid)
                document = await db.get(Document, document_id(file.path))
                if drive_file is None or document is None:
                    raise RuntimeError(f"{file.path}: stored file has no document; use a new store")
                refreshed += refresh_stored(drive_file, document, body) != "kept"
                continue
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
                    id=document_id(file.path),
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
            "refreshed": refreshed,
        }
    return counts
