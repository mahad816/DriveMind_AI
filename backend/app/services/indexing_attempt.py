"""Bounded BUILD write-ahead evidence. No document bodies or vector values."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.db.enums import DriveFileStatus, IndexingOperation
from app.db.models.indexing_job import IndexingJob

MAX_FILES = 2000
MAX_BYTES = 2 * 1024 * 1024
MAX_MUTATIONS = 4096


class AttemptEvidenceError(Exception):
    """Evidence cannot authorize execution or a safe recovery decision."""


class MutationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    sequence: int = Field(ge=0)
    operation: Literal[
        "create_collection", "create_payload_index", "delete", "set_payload", "upsert"
    ]
    collection: str = Field(min_length=1, max_length=255)
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    point_count: int = Field(ge=0)
    point_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    point_ids: list[UUID] = Field(max_length=100)
    intended_at: datetime
    acknowledged_at: datetime | None = None
    operation_id: int | None = None
    outcome: Literal["UNKNOWN", "ACKNOWLEDGED", "REJECTED"] = "UNKNOWN"


class FileEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    file_id: UUID
    selected_status: DriveFileStatus
    document_id: UUID | None = None
    content_hash: str | None = Field(default=None, min_length=1)
    chunk_count: int | None = Field(default=None, ge=0)
    chunk_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    phase: Literal["SELECTED", "PREPARED", "INDEXED", "SKIPPED", "FAILED"] = "SELECTED"
    sql_published: bool = False
    published_status: DriveFileStatus | None = None
    mutations: list[MutationEvidence] = Field(default_factory=list, max_length=MAX_MUTATIONS)


class BuildAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1] = 1
    job_id: UUID
    claim_id: UUID
    worker_id: UUID
    user_id: UUID
    target_file_id: UUID | None
    collection: str = Field(min_length=1, max_length=255)
    selected_at: datetime
    prior_recovery_required: bool
    selection_complete: Literal[True] = True
    files: list[FileEvidence] = Field(max_length=MAX_FILES)

    def file(self, file_id: UUID) -> FileEvidence:
        matches = [f for f in self.files if f.file_id == file_id]
        if len(matches) != 1:
            raise AttemptEvidenceError("BUILD target is absent or ambiguous in attempt evidence")
        return matches[0]

    def dump(self) -> dict[str, object]:
        encoded = self.model_dump_json()
        if (
            len(encoded.encode()) > MAX_BYTES
            or sum(len(f.mutations) for f in self.files) > MAX_MUTATIONS
        ):
            raise AttemptEvidenceError("BUILD attempt evidence exceeds its bounded capacity")
        result: dict[str, object] = json.loads(encoded)
        return result

    def completed(self) -> bool:
        return all(
            f.sql_published
            and f.published_status is not None
            and f.phase in {"INDEXED", "SKIPPED"}
            and all(
                m.outcome in {"ACKNOWLEDGED", "REJECTED"} and m.acknowledged_at is not None
                for m in f.mutations
            )
            for f in self.files
        )


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def read_attempt(job: IndexingJob, collection: str | None = None) -> BuildAttempt:
    try:
        if (
            not isinstance(job.attempt_manifest, dict)
            or type(job.attempt_manifest.get("version")) is not int
            or job.attempt_manifest.get("version") != 1
            or job.attempt_manifest.get("selection_complete") is not True
        ):
            raise AttemptEvidenceError("Invalid manifest schema or incomplete selection")
        raw = json.dumps(job.attempt_manifest)
        if len(raw.encode()) > MAX_BYTES:
            raise AttemptEvidenceError("Oversized BUILD evidence")
        attempt = BuildAttempt.model_validate_json(raw)
        attempt.dump()
    except (ValueError, TypeError, ValidationError) as exc:
        raise AttemptEvidenceError("Invalid or unsupported BUILD attempt evidence") from exc
    if (
        job.operation != IndexingOperation.BUILD
        or (
            attempt.job_id,
            attempt.claim_id,
            attempt.worker_id,
            attempt.user_id,
            attempt.target_file_id,
        )
        != (job.id, job.claim_id, job.worker_id, job.user_id, job.file_id)
        or (collection is not None and attempt.collection != collection)
        or len({f.file_id for f in attempt.files}) != len(attempt.files)
        or (job.file_id is not None and [f.file_id for f in attempt.files] != [job.file_id])
    ):
        raise AttemptEvidenceError("BUILD evidence identity does not match the authoritative job")
    sequence = 0
    for f in attempt.files:
        if (f.document_id is None) != (f.content_hash is None):
            raise AttemptEvidenceError("Incomplete selected document identity")
        if (f.chunk_count is None) != (f.chunk_digest is None):
            raise AttemptEvidenceError("Incomplete chunk identity digest")
        if f.sql_published and f.published_status is None:
            raise AttemptEvidenceError("SQL publication status is absent")
        if f.phase in {"PREPARED", "INDEXED"} and (
            f.document_id is None
            or not isinstance(f.content_hash, str)
            or not f.content_hash
            or f.chunk_count is None
            or f.chunk_digest is None
            or len(f.chunk_digest) != 64
        ):
            raise AttemptEvidenceError("Incomplete BUILD snapshot evidence")
        for m in f.mutations:
            if (
                m.sequence != sequence
                or (m.outcome == "REJECTED" and m.operation != "create_collection")
                or m.collection != attempt.collection
                or f.document_id is None
                or not f.content_hash
                or f.chunk_count is None
                or f.chunk_digest is None
                or (m.outcome != "UNKNOWN") != (m.acknowledged_at is not None)
                or (m.point_count <= 100 and len(m.point_ids) != m.point_count)
                or (m.point_ids and digest(sorted(str(i) for i in m.point_ids)) != m.point_digest)
            ):
                raise AttemptEvidenceError("Contradictory BUILD mutation evidence")
            sequence += 1
    return attempt
