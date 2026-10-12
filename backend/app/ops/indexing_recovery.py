"""Operator recovery and read-only cutover inspection. Never activates indexing."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from uuid import UUID
from urllib.parse import urlsplit

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, PayloadSchemaType, VectorParams

from app.core.config import Settings
from app.db.models.indexing_job import IndexingJob
from app.db.models.user import User
from app.db.models.google_oauth_token import GoogleOAuthToken
from app.embeddings.factory import get_embedding_service
from app.embeddings.qdrant_connection import create_qdrant_client
from app.ops.qdrant_tenant_inventory import inventory, refuse_demo
from app.ops.qdrant_tenant_repair import confirmation_target, validate_apply_database_url
from app.services.indexing_recovery import IndexingRecovery, MaintenanceAttestation, RecoveryBlocked
from app.services.indexing_attempt import AttemptEvidenceError


async def cutover_report(
    engine: AsyncEngine,
    client: AsyncQdrantClient,
    settings: Settings,
    dimension: int,
) -> dict[str, object]:
    refuse_demo(settings)
    checks: dict[str, object] = {}
    async with engine.connect() as db, db.begin():
        await db.execute(text("SET TRANSACTION READ ONLY"))
        checks["schema_revision"] = await db.scalar(text("SELECT version_num FROM alembic_version"))
        checks["schema_current"] = checks["schema_revision"] == "20261014_1200"
        index = await db.scalar(
            text(
                "SELECT indexdef FROM pg_indexes WHERE schemaname = current_schema() AND indexname = 'uq_indexing_jobs_unresolved_owner'"
            )
        )
        checks["owner_exclusion_constraint"] = isinstance(index, str) and all(
            part in index for part in ("UNIQUE", "recovery_required", "QUEUED", "RUNNING")
        )
        checks["recovery_evidence_bound"] = bool(
            await db.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'indexing_jobs'::regclass AND conname = 'ck_indexing_jobs_recovery_manifest_size' AND convalidated)"
                )
            )
        )
        checks["unresolved_jobs"] = await db.scalar(
            select(func.count())
            .select_from(IndexingJob)
            .where(IndexingJob.status.in_(["QUEUED", "RUNNING"]) | IndexingJob.recovery_required)
        )
        checks["historical_unknown_jobs"] = await db.scalar(
            select(func.count())
            .select_from(IndexingJob)
            .where(IndexingJob.operation.is_(None), IndexingJob.status.in_(["QUEUED", "RUNNING"]))
        )
        checks["owners_without_provider_identity"] = await db.scalar(
            select(func.count())
            .select_from(User)
            .where((User.google_id == "") | User.google_id.startswith("demo:"))
        )
        checks["owners_without_grants"] = await db.scalar(
            select(func.count())
            .select_from(User)
            .where(
                ~select(GoogleOAuthToken.id)
                .where(
                    GoogleOAuthToken.user_id == User.id, GoogleOAuthToken.grant_status == "ACTIVE"
                )
                .exists()
            )
        )
    info = await client.get_collection(settings.qdrant_collection)
    checks["concrete_collection"] = settings.qdrant_collection in {
        c.name for c in (await client.get_collections()).collections
    }
    vectors = info.config.params.vectors
    checks["compatible_vectors"] = (
        isinstance(vectors, VectorParams)
        and vectors.size == dimension
        and vectors.distance == Distance.COSINE
    )
    checks["payload_indexes"] = all(
        key in info.payload_schema
        and info.payload_schema[key].data_type
        in {PayloadSchemaType.KEYWORD, PayloadSchemaType.UUID}
        for key in ("user_id", "drive_file_id")
    )
    report = await inventory(engine, client, settings)
    checks["inventory_clean"] = report.as_dict()["clean"]
    from app.main import create_app

    app = create_app()
    checks["default_admission_closed"] = (
        app.state.indexing_admission_ready is False and app.state.indexing_supervisor is None
    )
    return {
        "ready": False,
        "activation_authorized": False,
        "mutation": False,
        "checks": checks,
        "inventory": report.as_dict(),
        "external_prerequisites": {
            "old_writers_drained": "UNKNOWN",
            "maintenance_enforced": "UNKNOWN",
            "storage_isolation_verified": "UNKNOWN",
            "independent_acceptance": "REQUIRED",
            "executor_runtime_health": "NOT_VERIFIED_BY_OFFLINE_INSPECTION",
            "classifier_runtime_health": "NOT_VERIFIED_BY_OFFLINE_INSPECTION",
            "cutover_authorization": "REQUIRED",
        },
        "reason": "Software inspection cannot establish remote quiescence or authorize production cutover",
    }


async def run_cli(args: argparse.Namespace) -> int:
    engine: AsyncEngine | None = None
    client: AsyncQdrantClient | None = None
    result: dict[str, object] = {
        "complete": False,
        "released": False,
        "ready": False,
        "error": "Invalid operator target, evidence or storage operation",
    }
    code = 2
    try:
        url = validate_apply_database_url(os.environ.get(args.database_env, ""))
        parsed = urlsplit(args.qdrant_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("Explicit Qdrant target required")
        settings = Settings(
            database_url=url.render_as_string(hide_password=False),
            qdrant_url=args.qdrant_url,
            qdrant_collection=args.collection,
            embedding_model=args.embedding_model,
        )
        refuse_demo(settings)
        if args.command == "apply" and args.confirm_target != confirmation_target(
            settings, database_target=url
        ):
            raise ValueError("Exact target required")
        engine = create_async_engine(url, hide_parameters=True)
        async with engine.connect() as db:
            if await db.scalar(text("SELECT current_database()")) != url.database:
                raise RecoveryBlocked(
                    "Connected database differs from the explicit operator target"
                )
        client = create_qdrant_client(settings)
        embeddings = get_embedding_service(settings)
        if args.command == "readiness":
            result = await cutover_report(engine, client, settings, embeddings.embedding_dimension)
            code = 1  # No production authorization is issued by this command.
        else:
            if args.owner is None or args.job is None:
                raise ValueError("Explicit owner and failed attempt required")
            recovery = IndexingRecovery(engine, client, settings, embeddings)
            if args.command == "audit":
                result = await recovery.audit(args.owner, args.job)
            else:
                result = await recovery.apply(
                    args.owner,
                    args.job,
                    MaintenanceAttestation(
                        args.maintenance_reference or "",
                        args.admission_closed,
                        args.writers_terminated,
                        args.outstanding_requests_settled,
                        args.collection_frozen,
                    ),
                    resume_id=args.resume,
                )
            code = 0
        result["complete"] = True
        result["target"] = {
            "database_host": url.host,
            "database_port": url.port,
            "database_name": url.database,
            "qdrant_host": parsed.hostname,
            "collection": args.collection,
        }
    except (RecoveryBlocked, AttemptEvidenceError) as exc:
        result["error"] = str(exc)
    except Exception:
        # Fixed text only, including failures after remote mutation. Evidence is
        # retained in SQL; operator may inspect the exact job through audit.
        pass
    finally:
        for resource in (client, engine):
            try:
                if isinstance(resource, AsyncQdrantClient):
                    await resource.close()
                elif isinstance(resource, AsyncEngine):
                    await resource.dispose()
            except Exception:
                result.update(complete=False, error="Operator cleanup failed")
                code = 2
    print(json.dumps(result, sort_keys=True))
    return code


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["audit", "apply", "readiness"])
    parser.add_argument("--database-env", required=True)
    parser.add_argument("--qdrant-url", required=True)
    parser.add_argument("--collection", required=True)
    parser.add_argument("--embedding-model", required=True)
    parser.add_argument("--owner", type=UUID)
    parser.add_argument("--job", type=UUID)
    parser.add_argument("--resume", type=UUID)
    parser.add_argument("--confirm-target")
    parser.add_argument("--maintenance-reference")
    for name in (
        "admission-closed",
        "writers-terminated",
        "outstanding-requests-settled",
        "collection-frozen",
    ):
        parser.add_argument("--" + name, action="store_true")
    raise SystemExit(asyncio.run(run_cli(parser.parse_args())))


if __name__ == "__main__":
    main()
