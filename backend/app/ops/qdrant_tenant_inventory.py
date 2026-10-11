"""Read-only, bounded tenant inventory. No repair or storage mutation APIs."""

import argparse
import asyncio
from collections import Counter
from dataclasses import dataclass, field
import json
import math
import os
import re
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import VectorParams
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.sql import Select
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import Settings
from app.db.enums import DriveFileStatus
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.db.models.user import User
from app.demo.manifest import load_manifest
from app.embeddings.qdrant_connection import create_qdrant_client


class InventoryError(Exception):
    """Fixed messages only; never include provider exceptions or input values."""


@dataclass
class Report:
    complete: bool = False
    expected_points: int = 0
    scanned_points: int = 0
    sql_chunks: int = 0
    ineligible_sql_chunks: int = 0
    correct_points: int = 0
    defect_records: int = 0
    issues: Counter[str] = field(default_factory=Counter)
    samples: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    sample_limit: int = 100

    def record(self, issues: list[str], point_id: UUID | int | None) -> None:
        self.issues.update(issues)
        if issues:
            self.defect_records += 1
        if issues and len(self.samples) < self.sample_limit:
            self.samples.append(
                {
                    "point_id": str(point_id) if point_id is not None else None,
                    "issues": sorted(issues),
                    "owner_only_repairable": set(issues) <= {"missing_owner", "wrong_owner"},
                }
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "complete": self.complete,
            "clean": self.complete and not self.issues and self.error is None,
            "empty": self.complete and self.expected_points == self.scanned_points == 0,
            "expected_points": self.expected_points,
            "scanned_points": self.scanned_points,
            "sql_chunks": self.sql_chunks,
            "ineligible_sql_chunks": self.ineligible_sql_chunks,
            "correct_points": self.correct_points,
            "issue_counts": dict(sorted(self.issues.items())),
            "samples": self.samples,
            "samples_truncated": self.defect_records > len(self.samples),
            "error": self.error,
        }


def canonical_uuid(value: object) -> UUID | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = UUID(value)
    except ValueError:
        return None
    return parsed if str(parsed) == value else None


def classify(point_id: UUID, payload: dict[str, Any], row: Any | None) -> list[str]:
    """Only IDs, hash and index are provenance; display metadata is not authority."""
    if row is None:
        return ["orphan_point"]
    issues: list[str] = []
    if row.owner is None or row.file_id is None or row.document_id is None:
        issues.append("inconsistent_lineage")
    if row.status != DriveFileStatus.INDEXED:
        issues.append("ineligible_point")
    if not row.chunk_hash or row.chunk_hash != row.document_hash:
        issues.append("inconsistent_lineage")
    required = {"chunk_id", "drive_file_id", "extracted_text_hash", "chunk_index"}
    if any(k not in payload or payload[k] is None for k in required):
        issues.append("missing_provenance")
    if "chunk_id" in payload and payload["chunk_id"] != str(point_id):
        issues.append("wrong_chunk_link")
    if "drive_file_id" in payload and payload["drive_file_id"] != str(row.file_id):
        issues.append("wrong_file_id")
    if "extracted_text_hash" in payload and payload["extracted_text_hash"] != row.chunk_hash:
        issues.append("wrong_hash")
    if "chunk_index" in payload and (
        type(payload["chunk_index"]) is not int or payload["chunk_index"] != row.chunk_index
    ):
        issues.append("wrong_chunk_index")
    owner = payload.get("user_id")
    if owner is None:
        issues.append("missing_owner")
    elif canonical_uuid(owner) is None:
        issues.append("invalid_owner")
    elif owner != str(row.owner):
        issues.append("wrong_owner")
    return sorted(set(issues))


def lineage_query() -> Select[Any]:
    return (
        select(
            Chunk.id.label("id"),
            Chunk.document_id.label("document_id"),
            Chunk.chunk_index,
            Chunk.metadata_json["extracted_text_hash"].as_string().label("chunk_hash"),
            Document.extracted_text_hash.label("document_hash"),
            DriveFile.id.label("file_id"),
            User.id.label("owner"),
            DriveFile.status,
        )
        .select_from(Chunk)
        .outerjoin(Document, Document.id == Chunk.document_id)
        .outerjoin(DriveFile, DriveFile.id == Document.drive_file_id)
        .outerjoin(User, User.id == DriveFile.user_id)
    )


def refuse_demo(settings: Settings) -> None:
    if settings.demo_mode or re.search(
        r"(^|[_\-])(?:demo|harbordesk)([_\-]|$)", settings.qdrant_collection.lower()
    ):
        raise InventoryError("Demo targets are prohibited")


async def inventory(
    engine: AsyncEngine,
    client: AsyncQdrantClient,
    settings: Settings,
    batch_size: int = 100,
    sample_limit: int = 100,
) -> Report:
    report = Report(sample_limit=sample_limit)
    try:
        refuse_demo(settings)
        if not 1 <= batch_size <= 1000 or not 0 <= sample_limit <= 1000:
            raise InventoryError("Invalid scan bounds")
        collection = settings.qdrant_collection
        info = await client.get_collection(collection)
        vector_config = info.config.params.vectors
        if not isinstance(vector_config, VectorParams):
            raise InventoryError("Unsupported collection vector schema")
        start_count = (await client.count(collection, exact=True)).count
        demo_files = {str(f.id) for f in load_manifest().files}
        async with engine.connect() as base:
            conn = await base.execution_options(isolation_level="REPEATABLE READ")
            async with conn.begin():
                await conn.execute(text("SET TRANSACTION READ ONLY"))
                demo_user = await conn.scalar(
                    select(User.id).where(User.google_id.like("demo:%")).limit(1)
                )
                demo_file = await conn.scalar(
                    select(DriveFile.id)
                    .where(DriveFile.id.in_([UUID(i) for i in demo_files]))
                    .limit(1)
                )
                if demo_user is not None or demo_file is not None:
                    raise InventoryError("Demo targets are prohibited")
                # SQL keyset walk: establish missing points, never export text or embeddings.
                last: UUID | None = None
                while True:
                    query = lineage_query().order_by(Chunk.id).limit(batch_size)
                    if last is not None:
                        query = query.where(Chunk.id > last)
                    rows = (await conn.execute(query)).all()
                    if not rows:
                        break
                    report.sql_chunks += len(rows)
                    eligible = [r for r in rows if r.status == DriveFileStatus.INDEXED]
                    report.expected_points += len(eligible)
                    report.ineligible_sql_chunks += len(rows) - len(eligible)
                    for row in rows:
                        if (
                            row.owner is None
                            or row.file_id is None
                            or row.document_hash is None
                            or (
                                row.status == DriveFileStatus.INDEXED
                                and (not row.chunk_hash or row.chunk_hash != row.document_hash)
                            )
                        ):
                            report.record(["inconsistent_lineage"], row.id)
                    if eligible:
                        records = await client.retrieve(
                            collection,
                            [str(r.id) for r in eligible],
                            with_payload=False,
                            with_vectors=False,
                        )
                        found = {canonical_uuid(r.id) for r in records}
                        expected = {r.id for r in eligible}
                        if None in found or not found <= expected or len(found) != len(records):
                            raise InventoryError("Invalid point lookup response")
                        for row in eligible:
                            if row.id not in found:
                                report.record(["missing_point"], row.id)
                    last = rows[-1].id
                # Qdrant walk: classify every actual point against the same SQL snapshot.
                offset: Any = None
                previous_key: tuple[int, int] | None = None
                while True:
                    records, next_offset = await client.scroll(
                        collection,
                        limit=batch_size,
                        offset=offset,
                        with_payload=[
                            "chunk_id",
                            "drive_file_id",
                            "extracted_text_hash",
                            "chunk_index",
                            "user_id",
                        ],
                        with_vectors=True,
                    )
                    if not records and next_offset is not None:
                        raise InventoryError("Incomplete point pagination")
                    ids = [u for r in records if (u := canonical_uuid(r.id)) is not None]
                    rows = (
                        (await conn.execute(lineage_query().where(Chunk.id.in_(ids)))).all()
                        if ids
                        else []
                    )
                    by_id = {r.id: r for r in rows}
                    for record in records:
                        point_id = canonical_uuid(record.id)
                        if point_id is not None:
                            key = (1, point_id.int)
                        elif isinstance(record.id, int):
                            key = (0, record.id)
                        else:
                            raise InventoryError("Unsupported point identifier")
                        if previous_key is not None and key <= previous_key:
                            raise InventoryError("Non-progressing point pagination")
                        previous_key = key
                        report.scanned_points += 1
                        payload = record.payload or {}
                        if (
                            isinstance(payload.get("drive_file_id"), str)
                            and payload["drive_file_id"] in demo_files
                        ):
                            raise InventoryError("Demo targets are prohibited")
                        if point_id is None:
                            report.record(
                                ["invalid_point_id"],
                                record.id if isinstance(record.id, int) else None,
                            )
                        else:
                            issues = classify(point_id, payload, by_id.get(point_id))
                            vector = record.vector
                            if (
                                not isinstance(vector, list)
                                or len(vector) != vector_config.size
                                or not all(
                                    isinstance(v, (int, float)) and math.isfinite(v) for v in vector
                                )
                            ):
                                issues.append("invalid_vector")
                            if not issues:
                                report.correct_points += 1
                            report.record(issues, point_id)
                    if next_offset is None:
                        break
                    if next_offset == offset:
                        raise InventoryError("Non-progressing point pagination")
                    offset = next_offset
                end_count = (await client.count(collection, exact=True)).count
                if start_count != report.scanned_points or end_count != start_count:
                    raise InventoryError("Incomplete or changing collection inventory")
        report.complete = True
    except InventoryError as exc:
        report.error = str(exc)
    except Exception:
        report.error = "Storage inspection failed"
    return report


async def run_cli(args: argparse.Namespace) -> int:
    engine: AsyncEngine | None = None
    client: AsyncQdrantClient | None = None
    exit_code = 2
    result: dict[str, Any] = {
        "complete": False,
        "clean": False,
        "error": "Invalid or prohibited operator configuration",
    }
    try:
        database = os.environ.get(args.database_env, "")
        if not database or not args.qdrant_url.strip() or not args.collection.strip():
            raise InventoryError("Explicit database environment variable is required")
        settings = Settings(
            database_url=database, qdrant_url=args.qdrant_url, qdrant_collection=args.collection
        )
        refuse_demo(settings)
        url = make_url(database)
        if url.drivername != "postgresql+asyncpg":
            raise InventoryError("PostgreSQL asyncpg target is required")
        target = {
            "database_host": url.host,
            "database_port": url.port,
            "database_name": url.database,
            "qdrant_host": urlsplit(args.qdrant_url).hostname,
            "collection": args.collection,
        }
        engine = create_async_engine(database, hide_parameters=True, echo=False, pool_pre_ping=True)
        client = create_qdrant_client(settings)
        report = await inventory(engine, client, settings, args.batch_size, args.max_samples)
        result = report.as_dict()
        result["target"] = target
        result["command"] = args.command
        exit_code = 2 if report.error else 1 if report.issues else 0
    except Exception:
        pass  # Fixed configuration error above; never serialize raw exception text.
    finally:
        # Attempt both cleanups even if one fails, and never print provider exception text.
        for resource in (client, engine):
            try:
                if isinstance(resource, AsyncQdrantClient):
                    await resource.close()
                elif isinstance(resource, AsyncEngine):
                    await resource.dispose()
            except Exception:
                result.update(complete=False, clean=False, error="Operator resource cleanup failed")
                exit_code = 2
    print(json.dumps(result, sort_keys=True))
    return exit_code


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["audit", "verify"])
    parser.add_argument(
        "--database-env",
        required=True,
        help="Name of environment variable containing the PostgreSQL URL",
    )
    parser.add_argument("--qdrant-url", required=True)
    parser.add_argument("--collection", required=True)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--max-samples", type=int, default=100)
    asyncio.run(run_cli(parser.parse_args()))


if __name__ == "__main__":
    main()
