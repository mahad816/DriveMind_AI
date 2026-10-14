"""Explicit normal-mode activation. Validation never creates or repairs storage."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from collections.abc import Awaitable
from urllib.parse import urlsplit
import re

from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from qdrant_client.models import Distance, PayloadSchemaType, VectorParams

from app.core.config import Settings
from app.db.models.application_session import ApplicationSession
from app.db.models.google_oauth_token import GoogleOAuthToken
from app.db.models.indexing_job import IndexingJob
from app.db.models.drive_file import DriveFile
from app.db.models.document import Document
from app.db.models.chunk import Chunk
from app.embeddings.factory import get_embedding_service
from app.embeddings.openai_service import resolve_embedding_dimension
from app.embeddings.qdrant_connection import create_qdrant_client
from app.ops.qdrant_tenant_inventory import refuse_demo
from app.security.google_credential_crypto import GoogleCredentialCrypto
from app.services.google_session_auth_service import validate_session_login_configuration
from app.services.google_credential_service import GoogleRefreshLifecycle
from app.services.indexing_worker import IndexingWorker
from app.services.indexing_maintenance import writer_available


class IndexingActivationError(ValueError):
    """Only fixed, nonsecret diagnostic codes escape configuration/provider failures."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Normal indexing unavailable: {code}")


def activation_target(settings: Settings) -> str:
    """Offline operator binding to endpoints/principal/schema/model; excludes secrets.

    This confirms configured destinations, not DNS integrity or remote quiescence.
    Collection aliases are refused separately using the live collection inventory.
    """
    url = make_url(settings.database_url)
    qdrant = urlsplit(settings.qdrant_url)
    if (
        url.drivername != "postgresql+asyncpg"
        or not url.host
        or not url.database
        or not url.username
        or not qdrant.hostname
        or qdrant.scheme not in {"http", "https"}
        or qdrant.username
        or qdrant.password
        or qdrant.query
        or qdrant.fragment
    ):
        raise IndexingActivationError("INVALID_TARGET")
    target = {
        "database": [
            url.drivername,
            url.host,
            url.port or 5432,
            url.database,
            url.username,
            settings.indexing_database_schema,
        ],
        "qdrant": [
            qdrant.scheme,
            qdrant.hostname,
            qdrant.port or (443 if qdrant.scheme == "https" else 80),
            qdrant.path.rstrip("/"),
        ],
        "collection": settings.qdrant_collection,
        "model": settings.embedding_model,
        "dimension": resolve_embedding_dimension(settings.embedding_model),
        "distance": "Cosine",
    }
    return hashlib.sha256(
        json.dumps(target, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


async def _join_cleanup(operation: Awaitable[None]) -> None:
    """Cleanup remains strongly owned even after timeout/repeated cancellation."""

    async def finish() -> None:
        await operation

    task = asyncio.create_task(finish(), name="indexing-dependency-cleanup")
    interrupted = False
    while True:
        try:
            await asyncio.shield(task)
            break
        except asyncio.CancelledError:
            if task.cancelled():
                raise
            interrupted = True
    if interrupted:
        raise asyncio.CancelledError


async def check_database(
    sessions: async_sessionmaker[AsyncSession], settings: Settings, *, schema: bool
) -> None:
    db = sessions()
    try:
        async with asyncio.timeout(settings.indexing_dependency_timeout):
            await db.execute(text("SET TRANSACTION READ ONLY"))
            identity = (
                await db.execute(text("SELECT current_database(), current_schema(), current_user"))
            ).one()
            url = make_url(settings.database_url)
            if tuple(identity) != (url.database, settings.indexing_database_schema, url.username):
                raise IndexingActivationError("DATABASE_TARGET_MISMATCH")
            if not await writer_available(db):
                raise IndexingActivationError("MAINTENANCE_ACTIVE")
            if schema:
                for model in (
                    IndexingJob,
                    GoogleOAuthToken,
                    ApplicationSession,
                    DriveFile,
                    Document,
                    Chunk,
                ):
                    await db.execute(select(model).limit(0))
                # Capability checks permit additive conversation/future migrations.
                constraints = set(
                    (
                        await db.scalars(
                            text(
                                "SELECT c.conname FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid WHERE c.connamespace = "
                                "(SELECT oid FROM pg_namespace WHERE nspname=current_schema()) AND c.convalidated "
                                "AND ((t.relname='indexing_jobs' AND c.conname LIKE 'ck_indexing_jobs_%') "
                                "OR (t.relname='google_oauth_tokens' AND c.conname LIKE 'ck_google_%') "
                                "OR (t.relname='drive_files' AND c.conname='uq_drive_files_user_id_drive_file_id'))"
                            )
                        )
                    ).all()
                )
                required = {
                    "ck_indexing_jobs_operation",
                    "ck_indexing_jobs_sync_target",
                    "ck_indexing_jobs_full_sync",
                    "ck_indexing_jobs_recovery_operation",
                    "ck_indexing_jobs_progress",
                    "ck_indexing_jobs_manifest_size",
                    "ck_indexing_jobs_recovery_manifest_size",
                    "ck_google_grant_versions",
                    "ck_google_grant_status",
                    "ck_google_refresh_claim",
                    "ck_google_envelope_size",
                    "uq_drive_files_user_id_drive_file_id",
                }
                if not required <= constraints:
                    raise IndexingActivationError("SCHEMA_INCOMPATIBLE")
                # PostgreSQL 16 canonical form of the accepted migration predicate:
                # reject same-named indexes with weakened logical exclusion.
                predicate = (
                    "((operation IS NOT NULL) AND (((status)::text = ANY "
                    "((ARRAY['QUEUED'::character varying, 'RUNNING'::character varying])::text[])) "
                    "OR recovery_required))"
                )
                valid = await db.scalar(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid "
                        "WHERE i.indrelid='indexing_jobs'::regclass "
                        "AND c.relname='uq_indexing_jobs_unresolved_owner' "
                        "AND i.indisvalid AND i.indisunique AND i.indnatts=1 "
                        "AND i.indkey[0]=(SELECT attnum FROM pg_attribute WHERE attrelid=i.indrelid AND attname='user_id') "
                        "AND pg_get_expr(i.indpred,i.indrelid)=:predicate)"
                    ),
                    {"predicate": predicate},
                )
                if not valid:
                    raise IndexingActivationError("SCHEMA_INCOMPATIBLE")
                if not await db.scalar(text("SELECT version_num FROM alembic_version")):
                    raise IndexingActivationError("SCHEMA_INCOMPATIBLE")
            else:
                await db.execute(select(IndexingJob.id).limit(1))
    except IndexingActivationError:
        raise
    except Exception:
        raise IndexingActivationError(
            "SCHEMA_OR_DATABASE_UNAVAILABLE" if schema else "DATABASE_UNAVAILABLE"
        ) from None
    finally:
        await _join_cleanup(db.close())


async def check_collection(settings: Settings) -> None:
    try:
        client = create_qdrant_client(settings)
    except Exception:
        raise IndexingActivationError("QDRANT_CONFIGURATION_INVALID") from None
    try:
        async with asyncio.timeout(settings.indexing_dependency_timeout):
            names = {row.name for row in (await client.get_collections()).collections}
            if settings.qdrant_collection not in names:
                raise IndexingActivationError("CONCRETE_COLLECTION_REQUIRED")
            info = await client.get_collection(settings.qdrant_collection)
            vectors = info.config.params.vectors
            if (
                not isinstance(vectors, VectorParams)
                or vectors.size != resolve_embedding_dimension(settings.embedding_model)
                or vectors.distance != Distance.COSINE
            ):
                raise IndexingActivationError("VECTOR_CONFIGURATION_INCOMPATIBLE")
            if not all(
                field in info.payload_schema
                and info.payload_schema[field].data_type
                in {PayloadSchemaType.KEYWORD, PayloadSchemaType.UUID}
                for field in ("user_id", "drive_file_id")
            ):
                raise IndexingActivationError("PAYLOAD_INDEXES_REQUIRED")
    except IndexingActivationError:
        raise
    except Exception:
        raise IndexingActivationError("QDRANT_UNAVAILABLE") from None
    finally:
        await _join_cleanup(client.close())


@dataclass(frozen=True)
class NormalIndexingRuntime:
    worker: IndexingWorker
    refresh: GoogleRefreshLifecycle
    poll_seconds: float = 1.0
    classifier_seconds: float = 5.0
    database_timeout: float = 10.0
    startup_timeout: float = 30.0
    drain_seconds: float = 20.0
    cleanup_seconds: float = 5.0
    classification_batch: int = 50

    @property
    def engine(self) -> AsyncEngine:
        engine = self.worker.sessions.kw.get("bind")
        if not isinstance(engine, AsyncEngine):
            raise IndexingActivationError("ASYNC_ENGINE_REQUIRED")
        return engine

    async def check_dependencies(self) -> None:
        await check_database(self.worker.sessions, self.worker.settings, schema=True)
        await check_collection(self.worker.settings)


async def create_normal_runtime(
    sessions: async_sessionmaker[AsyncSession], refresh: GoogleRefreshLifecycle, settings: Settings
) -> NormalIndexingRuntime:
    try:
        if not settings.indexing_enabled or settings.demo_mode or settings.debug:
            raise IndexingActivationError("ACTIVATION_NOT_AUTHORIZED")
        refuse_demo(settings)
        if re.search(
            r"(^|[_\-])(?:demo|harbordesk)([_\-]|$)", make_url(settings.database_url).database or ""
        ):
            raise IndexingActivationError("DEMO_TARGET_PROHIBITED")
        if settings.indexing_activation_target != activation_target(settings):
            raise IndexingActivationError("ACTIVATION_TARGET_MISMATCH")
        GoogleCredentialCrypto(
            settings.google_credential_encryption_keyring,
            settings.google_credential_encryption_active_key_id,
        )
        validate_session_login_configuration(settings)
        if not settings.openai_api_key.strip():
            raise IndexingActivationError("EMBEDDING_CREDENTIAL_REQUIRED")
        if sessions.kw.get("info", {}).get("google_refresh_lifecycle") is not refresh:
            raise IndexingActivationError("CREDENTIAL_LIFECYCLE_MISMATCH")
        engine = sessions.kw.get("bind")
        if not isinstance(engine, AsyncEngine) or engine.url != make_url(settings.database_url):
            raise IndexingActivationError("DATABASE_TARGET_MISMATCH")
    except IndexingActivationError:
        raise
    except Exception:
        raise IndexingActivationError("SECURITY_OR_TARGET_CONFIGURATION_INVALID") from None
    await check_database(sessions, settings, schema=True)
    await check_collection(settings)
    embeddings = get_embedding_service(settings)
    if (
        embeddings.model_name != settings.embedding_model
        or embeddings.embedding_dimension != resolve_embedding_dimension(settings.embedding_model)
    ):
        raise IndexingActivationError("EMBEDDING_CONFIGURATION_INCOMPATIBLE")
    return NormalIndexingRuntime(
        IndexingWorker(sessions, settings, embedding_service=embeddings),
        refresh,
        poll_seconds=settings.indexing_poll_seconds,
        classifier_seconds=settings.indexing_classifier_seconds,
        database_timeout=settings.indexing_dependency_timeout,
        startup_timeout=settings.indexing_startup_timeout,
        drain_seconds=settings.indexing_drain_seconds,
        cleanup_seconds=settings.indexing_cleanup_seconds,
    )
