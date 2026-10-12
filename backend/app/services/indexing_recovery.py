"""Operator-only reconciliation under externally enforced, collection-wide maintenance.

The cooperative PostgreSQL barrier cannot stop old binaries or retract Qdrant
requests. Apply requires a NEW external attestation for each invocation, including
resumption after interruption. No lifecycle or HTTP caller invokes this service.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4
from typing import Any, cast

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, PayloadSchemaType, VectorParams
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.enums import DriveFileStatus, IndexingJobStatus
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.db.models.indexing_job import IndexingJob
from app.db.models.user import User
from app.demo.manifest import load_manifest
from app.embeddings.base import EmbeddingService
from app.embeddings.vector_store import (
    QdrantVectorStore,
    VectorMutation,
    VectorPoint,
    VectorStoreError,
    _validate_vector,
)
from app.ops.qdrant_tenant_inventory import canonical_uuid, inventory, refuse_demo
from app.services.indexing_attempt import (
    MAX_BYTES,
    BuildAttempt,
    digest,
    read_attempt,
    file_metadata_digest,
    chunk_lineage_digest,
)
from app.services.indexing_maintenance import LOCK_KEY


async def timestamp(db: AsyncSession) -> str:
    value = await db.scalar(select(func.clock_timestamp()))
    if not isinstance(value, datetime):
        raise RecoveryBlocked("Database clock unavailable")
    return value.isoformat()


class RecoveryBlocked(Exception):
    """Safe operational reason; never include storage exception bodies."""


@dataclass(frozen=True)
class MaintenanceAttestation:
    # Reference/digest only; no free-form provider bodies, credentials or secrets.
    reference: str
    admission_closed: bool = False
    writers_terminated: bool = False
    outstanding_requests_settled: bool = False
    collection_frozen: bool = False

    def validate(self) -> None:
        if not (
            self.reference
            and len(self.reference) <= 128
            and all(c.isalnum() or c in "-_.:/" for c in self.reference)
            and self.admission_closed is True
            and self.writers_terminated is True
            and self.outstanding_requests_settled is True
            and self.collection_frozen is True
        ):
            raise RecoveryBlocked("Collection-wide externally enforced maintenance is required")


@dataclass
class RecoveryFile:
    file: DriveFile
    document: Document | None
    chunks: list[Chunk]
    skipped: bool


class IndexingRecovery:
    def __init__(
        self,
        engine: AsyncEngine,
        client: AsyncQdrantClient,
        settings: Settings,
        embeddings: EmbeddingService,
    ) -> None:
        refuse_demo(settings)
        self.engine, self.client, self.settings, self.embeddings = (
            engine,
            client,
            settings.model_copy(deep=True),
            embeddings,
        )
        self.sessions = async_sessionmaker(engine, expire_on_commit=False)

    def _journal(self, data: object, attempt: BuildAttempt) -> dict[str, Any]:
        if not isinstance(data, dict) or len(json.dumps(data).encode()) > MAX_BYTES:
            raise RecoveryBlocked("Recovery journal is invalid or oversized")
        expected = {
            "version": 1,
            "job_id": str(attempt.job_id),
            "claim_id": str(attempt.claim_id),
            "owner": str(attempt.user_id),
            "collection": attempt.collection,
            "model": self.embeddings.model_name,
            "dimension": self.embeddings.embedding_dimension,
            "files": [str(f.file_id) for f in attempt.files],
        }
        if (
            any(data.get(k) != v for k, v in expected.items())
            or type(data.get("version")) is not int
        ):
            raise RecoveryBlocked("Recovery journal identity or vector configuration differs")
        if canonical_uuid(data.get("id")) is None or data.get("state") not in {
            "REPAIRING",
            "VERIFYING",
            "VERIFIED",
        }:
            raise RecoveryBlocked("Recovery journal state is invalid")
        operations = data.get("operations")
        if not isinstance(operations, list) or len(operations) > 4096:
            raise RecoveryBlocked("Recovery journal operations are invalid")
        for sequence, operation in enumerate(operations):
            if (
                not isinstance(operation, dict)
                or type(operation.get("sequence")) is not int
                or operation.get("sequence") != sequence
                or operation.get("operation") not in {"upsert", "delete"}
                or operation.get("outcome") not in {"UNKNOWN", "ACKNOWLEDGED", "RECONCILED"}
                or not isinstance(operation.get("point_ids"), list)
                or len(operation["point_ids"]) > 100
                or any(canonical_uuid(i) is None for i in operation["point_ids"])
                or not isinstance(operation.get("request_digest"), str)
                or len(operation["request_digest"]) != 64
                or any(c not in "0123456789abcdef" for c in operation["request_digest"])
                or (
                    operation.get("outcome") == "ACKNOWLEDGED"
                    and not isinstance(operation.get("acknowledged_at"), str)
                )
            ):
                raise RecoveryBlocked("Recovery journal operation is invalid")
        result: dict[str, Any] = json.loads(json.dumps(data))
        return result

    async def _job(self, db: AsyncSession, owner: UUID, job_id: UUID) -> IndexingJob:
        await db.execute(text("SET LOCAL lock_timeout = '2s'"))
        await db.execute(text("SET LOCAL statement_timeout = '15s'"))
        job = await db.scalar(
            select(IndexingJob)
            .join(User, User.id == IndexingJob.user_id)
            .where(
                IndexingJob.id == job_id,
                IndexingJob.user_id == owner,
                ~User.google_id.startswith("demo:"),
            )
            .with_for_update(of=IndexingJob)
        )
        if job is None or job.status != IndexingJobStatus.FAILED or not job.recovery_required:
            raise RecoveryBlocked("Exact failed recovery-required owner attempt is required")
        if self.settings.demo_user_id and owner == UUID(self.settings.demo_user_id):
            raise RecoveryBlocked("Demo owners are prohibited")
        return job

    async def _quiet(self, db: AsyncSession) -> None:
        if (
            await db.scalar(
                select(IndexingJob.id)
                .where(
                    IndexingJob.status.in_([IndexingJobStatus.QUEUED, IndexingJobStatus.RUNNING])
                )
                .limit(1)
            )
            is not None
        ):
            raise RecoveryBlocked(
                "Queued/running work must be drained or explicitly classified first"
            )

    async def _configuration(self) -> None:
        names = {c.name for c in (await self.client.get_collections()).collections}
        if self.settings.qdrant_collection not in names:
            raise RecoveryBlocked("Recovery requires an existing concrete collection, not an alias")
        info = await self.client.get_collection(self.settings.qdrant_collection)
        vectors = info.config.params.vectors
        if not isinstance(vectors, VectorParams) or (
            vectors.size != self.embeddings.embedding_dimension
            or vectors.distance != Distance.COSINE
            or vectors.multivector_config is not None
        ):
            raise RecoveryBlocked(
                "Existing collection must match unnamed COSINE embedding configuration"
            )
        if any(
            key not in info.payload_schema
            or info.payload_schema[key].data_type
            not in {PayloadSchemaType.KEYWORD, PayloadSchemaType.UUID}
            for key in ("user_id", "drive_file_id")
        ):
            raise RecoveryBlocked("Required tenant payload indexes are missing or incompatible")

    async def _scope(
        self, db: AsyncSession, attempt: BuildAttempt, *, lock: bool = False
    ) -> list[RecoveryFile]:
        result = []
        demo_files = {f.id for f in load_manifest().files}
        if (
            attempt.embedding_model != self.embeddings.model_name
            or attempt.vector_dimension != self.embeddings.embedding_dimension
        ):
            raise RecoveryBlocked(
                "Original embedding configuration is unknown or differs from recovery"
            )
        for evidence in attempt.files:
            if evidence.file_id in demo_files:
                raise RecoveryBlocked("Demo files are prohibited")
            file_query = select(DriveFile).where(
                DriveFile.id == evidence.file_id, DriveFile.user_id == attempt.user_id
            )
            file = await db.scalar(file_query.with_for_update() if lock else file_query)
            if file is None:
                raise RecoveryBlocked("Selected file is missing or no longer belongs to the owner")
            if evidence.metadata_digest is None or evidence.metadata_digest != file_metadata_digest(
                file
            ):
                raise RecoveryBlocked(
                    "Selected file metadata changed or historical snapshot is unknown"
                )
            if file.status not in {
                DriveFileStatus.FAILED,
                DriveFileStatus.INDEXING,
                DriveFileStatus.INDEXED,
                DriveFileStatus.SKIPPED,
            }:
                raise RecoveryBlocked("Selected file needs fresh ingestion before recovery")
            skipped = (
                evidence.selected_status == DriveFileStatus.SKIPPED or evidence.phase == "SKIPPED"
            )
            if file.status == DriveFileStatus.SKIPPED and not skipped:
                # Empty ingestion may preserve the old document/chunks. Matching
                # hashes do not authorize republishing that deliberately excluded content.
                # Authority repeats this check under file locks before writes and release.
                raise RecoveryBlocked("Current SKIPPED file contradicts the BUILD recovery outcome")
            doc_query = (
                select(Document)
                .where(Document.drive_file_id == file.id)
                .order_by(Document.updated_at.desc(), Document.id)
                .limit(1)
            )
            doc = await db.scalar(doc_query.with_for_update() if lock else doc_query)
            if skipped and evidence.document_id is None:
                result.append(RecoveryFile(file, None, [], True))
                continue
            if (
                doc is None
                or doc.id != evidence.document_id
                or doc.extracted_text_hash != evidence.content_hash
            ):
                raise RecoveryBlocked("Selected document snapshot changed or is unavailable")
            chunk_query = (
                select(Chunk).where(Chunk.document_id == doc.id).order_by(Chunk.chunk_index)
            )
            chunks = list(
                (await db.scalars(chunk_query.with_for_update() if lock else chunk_query)).all()
            )
            if evidence.chunk_count != len(chunks) or evidence.chunk_digest != digest(
                sorted(str(c.id) for c in chunks)
            ):
                raise RecoveryBlocked("Prepared chunk snapshot is absent or changed")
            if evidence.document_text_digest != digest(
                doc.extracted_text
            ) or evidence.chunk_lineage_digest != chunk_lineage_digest(chunks):
                raise RecoveryBlocked(
                    "Prepared content lineage changed or historical evidence is unknown"
                )
            if any(
                c.metadata_json.get("extracted_text_hash") != doc.extracted_text_hash
                for c in chunks
            ):
                raise RecoveryBlocked("Chunk hash lineage is inconsistent")
            result.append(RecoveryFile(file, doc, chunks, skipped or not chunks))
        return result

    @asynccontextmanager
    async def _maintenance(
        self, attestation: MaintenanceAttestation
    ) -> AsyncIterator[AsyncConnection]:
        attestation.validate()
        async with self.engine.connect() as connection:
            acquired = bool(
                await connection.scalar(
                    text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_KEY}
                )
            )
            await connection.commit()
            if not acquired:
                raise RecoveryBlocked("Another writer transaction or recovery operator is active")
            try:
                yield connection
            finally:
                await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
                await connection.commit()

    async def audit(self, owner: UUID, job_id: UUID) -> dict[str, object]:
        # No writes, including evidence/index creation. This is not quiescence proof.
        await self._configuration()
        async with self.sessions() as db:
            row = await db.scalar(
                select(IndexingJob).where(IndexingJob.id == job_id, IndexingJob.user_id == owner)
            )
            if row is None:
                raise RecoveryBlocked("Owner attempt not found")
            attempt = read_attempt(row, self.settings.qdrant_collection)
            scope = await self._scope(db, attempt)
        journal = row.recovery_manifest if isinstance(row.recovery_manifest, dict) else {}
        recovery_id = canonical_uuid(journal.get("id"))
        state = journal.get("state")
        return {
            "job_id": str(job_id),
            "owner": str(owner),
            "files": [str(f.file.id) for f in scope],
            "mutation": False,
            "quiescence_verified": False,
            "ready_to_release": False,
            "recovery_required": row.recovery_required,
            "recovery_id": str(recovery_id) if recovery_id is not None else None,
            "recovery_state": state
            if isinstance(state, str) and state in {"REPAIRING", "VERIFYING", "VERIFIED"}
            else "UNKNOWN"
            if journal
            else "NOT_STARTED",
        }

    async def apply(
        self,
        owner: UUID,
        job_id: UUID,
        attestation: MaintenanceAttestation,
        *,
        resume_id: UUID | None = None,
    ) -> dict[str, object]:
        attestation.validate()
        async with self.sessions() as db:
            await self._quiet(db)
        async with self._maintenance(attestation) as maintenance:
            # Recheck after the barrier, BEFORE Qdrant I/O. A claim that won
            # the preceding race must not lose its heartbeat to a slow preflight.
            async with self.sessions() as db:
                await self._quiet(db)
            await self._configuration()  # Before any mutation or SQL publication.
            async with self.sessions() as db, db.begin():
                await self._quiet(db)
                job = await self._job(db, owner, job_id)
                attempt = read_attempt(job, self.settings.qdrant_collection)
                if attempt.prior_recovery_required:
                    raise RecoveryBlocked(
                        "Prior uncertainty has no complete scoped recovery evidence"
                    )
                scope = await self._scope(db, attempt, lock=True)
                original_digest = digest(job.attempt_manifest)
                previous = job.recovery_manifest
                evidence: dict[str, Any]
                if previous is not None:
                    if (
                        previous.get("version") != 1
                        or previous.get("id") != str(resume_id)
                        or previous.get("original_digest") != original_digest
                        or previous.get("state") not in {"REPAIRING", "VERIFYING"}
                    ):
                        raise RecoveryBlocked(
                            "Interrupted recovery requires its exact identity and renewed quiescence"
                        )
                    evidence = self._journal(previous, attempt)
                    recovery_id = UUID(str(evidence["id"]))
                    evidence["attestation_digest"] = digest(attestation.reference)
                else:
                    if resume_id is not None:
                        raise RecoveryBlocked("Recovery identity not found")
                    recovery_id = uuid4()
                    evidence = {
                        "version": 1,
                        "id": str(recovery_id),
                        "job_id": str(job_id),
                        "claim_id": str(job.claim_id),
                        "owner": str(owner),
                        "original_digest": original_digest,
                        "collection": attempt.collection,
                        "model": self.embeddings.model_name,
                        "dimension": self.embeddings.embedding_dimension,
                        "files": [str(f.file.id) for f in scope],
                        "state": "REPAIRING",
                        "attestation_digest": digest(attestation.reference),
                        "operations": [],
                        "started_at": await timestamp(db),
                    }
                history = evidence.setdefault("maintenance_evidence", [])
                if not isinstance(history, list) or len(history) >= 100:
                    raise RecoveryBlocked("Maintenance evidence history is invalid or exhausted")
                history.append(
                    {"reference_digest": digest(attestation.reference), "at": await timestamp(db)}
                )
                job.recovery_manifest = evidence
                prior_operation_count = len(evidence["operations"])
            # Snapshot every point before planning mutations; full scan detects foreign
            # SQL lineage even when an orphan payload pretends to own it.
            expected = {c.id: (f, c) for f in scope if not f.skipped for c in f.chunks}
            selected = {f.file.id for f in scope}
            records = {}
            stale: list[UUID] = []
            offset = None
            previous_id: UUID | None = None
            scanned = 0
            start_count = (await self.client.count(attempt.collection, exact=True)).count
            while True:
                batch, next_offset = await self.client.scroll(
                    attempt.collection,
                    limit=100,
                    offset=offset,
                    with_payload=True,
                    with_vectors=True,
                )
                for record in batch:
                    point_id = canonical_uuid(record.id)
                    if point_id is None or (previous_id is not None and point_id <= previous_id):
                        raise RecoveryBlocked("Collection has invalid or repeated point identities")
                    previous_id = point_id
                    scanned += 1
                    payload = record.payload or {}
                    if point_id in expected:
                        records[point_id] = record
                    elif payload.get("user_id") == str(owner) and payload.get("drive_file_id") in {
                        str(i) for i in selected
                    }:
                        if payload.get("chunk_id") != str(point_id):
                            raise RecoveryBlocked("Stale point provenance is contradictory")
                        async with self.sessions() as db:
                            if await db.get(Chunk, point_id) is not None:
                                raise RecoveryBlocked(
                                    "Stale point has surviving unrelated SQL lineage"
                                )
                        stale.append(point_id)
                if next_offset is None:
                    break
                if next_offset == offset or not batch:
                    raise RecoveryBlocked("Collection pagination did not progress")
                offset = next_offset
            if (
                scanned != start_count
                or (await self.client.count(attempt.collection, exact=True)).count != start_count
            ):
                raise RecoveryBlocked("Collection changed or scan is incomplete")

            async def authority(db: AsyncSession) -> IndexingJob:
                if maintenance.closed or maintenance.invalidated:
                    raise RecoveryBlocked("Maintenance database authority was lost")
                held = await maintenance.scalar(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory' "
                        "AND pid = pg_backend_pid() AND classid = :high AND objid = :low "
                        "AND objsubid = 1 AND mode = 'ExclusiveLock' AND granted)"
                    ),
                    {"high": LOCK_KEY >> 32, "low": LOCK_KEY & 0xFFFFFFFF},
                )
                await maintenance.commit()
                if not held:
                    raise RecoveryBlocked("Maintenance database authority was lost")
                await self._quiet(db)
                current = await self._job(db, owner, job_id)
                if (
                    digest(current.attempt_manifest) != original_digest
                    or not isinstance(current.recovery_manifest, dict)
                    or current.recovery_manifest.get("id") != str(recovery_id)
                ):
                    raise RecoveryBlocked("Recovery authority changed")
                await self._scope(db, read_attempt(current, attempt.collection), lock=True)
                self._journal(current.recovery_manifest, attempt)
                return current

            async def intent(mutation: VectorMutation) -> int:
                if (
                    mutation.collection != attempt.collection
                    or mutation.operation not in {"upsert", "delete"}
                    or not set(mutation.point_ids)
                    <= (set(stale) if mutation.operation == "delete" else set(expected))
                ):
                    raise RecoveryBlocked("Mutation differs from the authorized recovery plan")
                async with self.sessions() as db, db.begin():
                    current = await authority(db)
                    data = json.loads(json.dumps(current.recovery_manifest))
                    operations = data["operations"]
                    if len(operations) >= 4096 or len(mutation.point_ids) > 100:
                        raise RecoveryBlocked("Recovery evidence capacity exceeded")
                    token = len(operations)
                    operations.append(
                        {
                            "sequence": token,
                            "operation": mutation.operation,
                            "point_ids": [str(i) for i in mutation.point_ids],
                            "request_digest": mutation.request_digest,
                            "outcome": "UNKNOWN",
                            "intended_at": await timestamp(db),
                        }
                    )
                    if len(json.dumps(data).encode()) > MAX_BYTES:
                        raise RecoveryBlocked("Recovery evidence capacity exceeded")
                    current.recovery_manifest = data
                    return token

            async def receipt(token: int, outcome: str, operation_id: int | None) -> None:
                async with self.sessions() as db, db.begin():
                    current = await authority(db)
                    data = json.loads(json.dumps(current.recovery_manifest))
                    entry = data["operations"][token]
                    if (
                        entry["sequence"] != token
                        or entry["outcome"] != "UNKNOWN"
                        or outcome != "ACKNOWLEDGED"
                    ):
                        raise RecoveryBlocked("Recovery receipt is inconsistent")
                    entry.update(
                        outcome=outcome,
                        operation_id=operation_id,
                        acknowledged_at=await timestamp(db),
                    )
                    current.recovery_manifest = data

            store = QdrantVectorStore(
                self.settings,
                client=self.client,
                verify_writes=True,
                upsert_batch_size=100,
                before_write=intent,
                after_write=receipt,
            )
            # Re-embed only missing/invalid points; healthy unchanged vectors are retained.
            from app.services.indexing_service import IndexingService

            async with self.sessions() as db:
                indexer = IndexingService(
                    db, self.settings, embedding_service=self.embeddings, vector_store=store
                )
                pending = []
                for point_id, (file, chunk) in expected.items():
                    existing = records.get(point_id)
                    payload = indexer._chunk_payload(chunk, file.file)
                    reusable: list[float] | None = None
                    if (
                        existing is not None
                        and isinstance(existing.vector, list)
                        and all(
                            (existing.payload or {}).get(k) == payload[k]
                            for k in ("chunk_id", "drive_file_id", "extracted_text_hash")
                        )
                    ):
                        try:
                            _validate_vector(
                                cast(list[float], existing.vector),
                                expected_size=self.embeddings.embedding_dimension,
                            )
                            reusable = cast(list[float], existing.vector)
                        except (VectorStoreError, ValueError, TypeError):
                            pass
                    serialized = {
                        k: v.isoformat() if isinstance(v, datetime) else v
                        for k, v in payload.items()
                    }
                    if (
                        reusable is None
                        or existing is None
                        or any((existing.payload or {}).get(k) != v for k, v in serialized.items())
                    ):
                        pending.append((file, chunk, payload, reusable))
                # Reserve a conservative upper bound for all planned bounded
                # requests before the first remote mutation, including receipts.
                needed = (len(stale) + 99) // 100 + (len(pending) + 99) // 100
                if (
                    prior_operation_count + needed > 4096
                    or len(json.dumps(evidence).encode()) + needed * 10000 > MAX_BYTES
                ):
                    raise RecoveryBlocked("Complete recovery plan exceeds evidence capacity")
                for start in range(0, len(stale), 100):
                    await store.delete_points(stale[start : start + 100])
                for start in range(0, len(pending), 100):
                    pending_batch = pending[start : start + 100]
                    texts = [c.text for _, c, _, vector in pending_batch if vector is None]
                    vectors = await self.embeddings.embed_texts(texts) if texts else []
                    fresh = iter(vectors)
                    if len(vectors) != sum(vector is None for _, _, _, vector in pending_batch):
                        raise RecoveryBlocked("Embedding batch is incomplete")
                    await store.upsert_points(
                        [
                            VectorPoint(c.id, next(fresh) if vector is None else vector, p)
                            for _, c, p, vector in pending_batch
                        ],
                        user_id=owner,
                        expected_vector_size=self.embeddings.embedding_dimension,
                    )
            async with self.sessions() as db, db.begin():
                current = await authority(db)
                data = json.loads(json.dumps(current.recovery_manifest))
                # Original uncertain intents are resolved only by renewed operational
                # quiescence + fresh inventory. New UNKNOWN intents require another
                # invocation with renewed attestation; never cleared in this run.
                if any(
                    m["outcome"] != "ACKNOWLEDGED"
                    for m in data["operations"][prior_operation_count:]
                ):
                    raise RecoveryBlocked(
                        "Interrupted recovery needs renewed quiescence and reconciliation"
                    )
                for f in scope:
                    await db.execute(
                        update(DriveFile)
                        .where(DriveFile.id == f.file.id, DriveFile.user_id == owner)
                        .values(
                            status=DriveFileStatus.SKIPPED
                            if f.skipped
                            else DriveFileStatus.INDEXED,
                            indexed_at=datetime.now(UTC),
                        )
                    )
                data["state"] = "VERIFYING"
                current.recovery_manifest = data
            report = await inventory(self.engine, self.client, self.settings)
            if not report.as_dict()["clean"]:
                raise RecoveryBlocked(
                    "Fresh exhaustive SQL/Qdrant inventory is not clean; owner remains blocked"
                )
            await self._configuration()
            async with self.sessions() as db, db.begin():
                current = await authority(db)
                data = json.loads(json.dumps(current.recovery_manifest))
                if data["state"] != "VERIFYING" or any(
                    m["outcome"] != "ACKNOWLEDGED"
                    for m in data["operations"][prior_operation_count:]
                ):
                    raise RecoveryBlocked("Recovery evidence is unresolved")
                for operation in data["operations"][:prior_operation_count]:
                    if operation["outcome"] == "UNKNOWN":
                        operation.update(
                            outcome="RECONCILED",
                            reconciled_at=await timestamp(db),
                            quiescence_attestation_digest=data["attestation_digest"],
                        )
                data.update(state="VERIFIED", verified_at=await timestamp(db))
                current.recovery_manifest = data
                current.recovery_required = False
            return {
                "recovery_id": str(recovery_id),
                "released": True,
                "original_job_status": "FAILED",
                "inventory": report.as_dict(),
                "quiescence": "EXTERNAL_ATTESTATION",
            }
