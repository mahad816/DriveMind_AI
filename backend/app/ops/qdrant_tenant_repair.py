"""Controlled owner-only repair, reusing the independent inventory verifier."""

from typing import Any
from uuid import UUID

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    FieldCondition,
    Filter,
    HasIdCondition,
    IsEmptyCondition,
    PayloadField,
    MatchValue,
    UpdateStatus,
    VectorParams,
)
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.db.models.chunk import Chunk
from app.db.models.drive_file import DriveFile
from app.db.models.user import User
from app.demo.manifest import load_manifest
from app.ops.qdrant_tenant_inventory import (
    InventoryError,
    canonical_uuid,
    inventory,
    lineage_query,
    point_issues,
    refuse_demo,
)

OWNER_ISSUES = {"missing_owner", "wrong_owner"}


def confirmation_target(settings: Settings) -> str:
    """Exact nonsecret target identity; connection passwords/parameters are never displayed."""
    url = make_url(settings.database_url)
    return f"{url.host}:{url.port or 5432}/{url.database}|{settings.qdrant_url.strip()}|{settings.qdrant_collection}"


async def current_rows(engine: AsyncEngine, ids: list[UUID]) -> dict[UUID, Any]:
    """Fresh, short read-only snapshot for every batch; no lock spans network I/O."""
    demo_files = [f.id for f in load_manifest().files]
    async with engine.connect() as conn:
        async with conn.begin():
            await conn.execute(text("SET TRANSACTION READ ONLY"))
            if (
                await conn.scalar(select(User.id).where(User.google_id.like("demo:%")).limit(1))
                is not None
                or await conn.scalar(
                    select(DriveFile.id).where(DriveFile.id.in_(demo_files)).limit(1)
                )
                is not None
            ):
                raise InventoryError("Demo targets are prohibited")
            rows = (await conn.execute(lineage_query().where(Chunk.id.in_(ids)))).all()
            return {r.id: r for r in rows}


def guarded_selector(records: list[Any]) -> Filter:
    """Conditions narrow updates to the inspected provenance; this is not a full CAS."""
    alternatives = []
    for record in records:
        payload = record.payload
        conditions: list[Any] = [HasIdCondition(has_id=[record.id])]
        for key in ("chunk_id", "drive_file_id", "extracted_text_hash", "chunk_index"):
            conditions.append(FieldCondition(key=key, match=MatchValue(value=payload[key])))
        if payload.get("user_id") is None:
            conditions.append(IsEmptyCondition(is_empty=PayloadField(key="user_id")))
        else:
            conditions.append(
                FieldCondition(key="user_id", match=MatchValue(value=payload["user_id"]))
            )
        alternatives.append(Filter(must=conditions))
    return Filter(should=alternatives)


async def apply_repair(
    engine: AsyncEngine,
    client: AsyncQdrantClient,
    settings: Settings,
    batch_size: int = 100,
    sample_limit: int = 100,
) -> tuple[dict[str, Any], int]:
    """Stop on any blocker/error. Earlier successful writes remain; reruns are idempotent."""
    result: dict[str, Any] = {
        "complete": False,
        "clean": False,
        "changed": 0,
        "already_correct": 0,
        "skipped": 0,
        "blocked": 0,
        "failed": 0,
        "samples": [],
        "error": None,
        "preflight": None,
        "verification": None,
    }

    def sample(ids: list[str], reason: str) -> None:
        for point_id in ids:
            if len(result["samples"]) < sample_limit:
                result["samples"].append({"point_id": point_id, "reason": reason})

    try:
        refuse_demo(settings)
        preflight = await inventory(engine, client, settings, batch_size, sample_limit)
        result["preflight"] = preflight.as_dict()
        if not preflight.complete or preflight.error:
            result["error"] = "Repair preflight failed"
            return result, 2
        blockers = set(preflight.issues) - OWNER_ISSUES
        if blockers:
            # Entire preflight is refused; retain issue counts rather than inventing a
            # unique-point count from overlapping scanner classifications.
            result["preflight_blockers"] = {k: preflight.issues[k] for k in sorted(blockers)}
            result["skipped"] = preflight.scanned_points
            result["samples"] = preflight.samples
            result["error"] = "Non-owner defects block repair"
            return result, 1
        collection = settings.qdrant_collection
        info = await client.get_collection(collection)
        config = info.config.params.vectors
        if not isinstance(config, VectorParams):
            raise InventoryError("Unsupported collection vector schema")
        offset: Any = None
        previous: UUID | None = None
        scanned = 0
        while True:
            discovered, next_offset = await client.scroll(
                collection, limit=batch_size, offset=offset, with_payload=False, with_vectors=False
            )
            ids = [canonical_uuid(r.id) for r in discovered]
            if any(i is None for i in ids) or (not ids and next_offset is not None):
                raise InventoryError("Repair discovery changed or incomplete")
            valid_ids = [i for i in ids if i is not None]
            for i in valid_ids:
                if previous is not None and i.int <= previous.int:
                    raise InventoryError("Non-progressing repair pagination")
                previous = i
            scanned += len(valid_ids)
            before_rows = await current_rows(engine, valid_ids)
            records = (
                await client.retrieve(
                    collection, [str(i) for i in valid_ids], with_payload=True, with_vectors=True
                )
                if valid_ids
                else []
            )
            by_id = {canonical_uuid(r.id): r for r in records}
            if set(by_id) != set(valid_ids) or len(by_id) != len(records):
                result["blocked"] += len(set(valid_ids) - set(by_id)) or 1
                sample([str(i) for i in valid_ids], "Point missing or lookup changed")
                result["error"] = "Repair batch changed"
                return result, 1
            # Revalidate the discovery snapshot immediately before preparing writes.
            latest_rows = await current_rows(engine, valid_ids)
            latest = (
                await client.retrieve(
                    collection, [str(i) for i in valid_ids], with_payload=True, with_vectors=True
                )
                if valid_ids
                else []
            )
            latest_by_id = {canonical_uuid(r.id): r for r in latest}
            if (
                before_rows != latest_rows
                or set(latest_by_id) != set(valid_ids)
                or len(latest_by_id) != len(latest)
            ):
                result["blocked"] += len(valid_ids)
                sample([str(i) for i in valid_ids], "Authoritative batch changed")
                result["error"] = "Repair batch changed"
                return result, 1
            groups: dict[UUID, list[Any]] = {}
            for i in valid_ids:
                record, row = latest_by_id[i], latest_rows.get(i)
                discovered_record = by_id[i]
                issues = point_issues(record, row, config.size)
                if record.vector != discovered_record.vector or {
                    k: v for k, v in (record.payload or {}).items() if k != "user_id"
                } != {k: v for k, v in (discovered_record.payload or {}).items() if k != "user_id"}:
                    issues.append("point_changed")
                if issues and not set(issues) <= OWNER_ISSUES:
                    result["blocked"] += 1
                    sample([str(i)], "Provenance or eligibility changed")
                elif not issues:
                    result["already_correct"] += 1
                elif row is not None:
                    groups.setdefault(row.owner, []).append(record)
                else:
                    raise InventoryError("Repair lineage could not be resolved")
            if result["blocked"]:
                result["skipped"] += sum(len(batch) for batch in groups.values())
                result["error"] = "Repair batch changed"
                return result, 1
            for owner, batch in groups.items():
                attempted = [canonical_uuid(r.id) for r in batch]
                attempt_ids = [i for i in attempted if i is not None]
                # Owner groups are separate writes: do not reuse an earlier group's
                # authorization snapshot across its network operation.
                group_rows = await current_rows(engine, attempt_ids)
                group_records = await client.retrieve(
                    collection, [str(i) for i in attempt_ids], with_payload=True, with_vectors=True
                )
                group_by_id = {canonical_uuid(r.id): r for r in group_records}
                ready = []
                group_blocked = []
                for record, i in zip(batch, attempt_ids, strict=True):
                    current_record = group_by_id.get(i)
                    issues = (
                        point_issues(current_record, group_rows.get(i), config.size)
                        if current_record is not None
                        else ["missing_point"]
                    )
                    if (
                        before_rows.get(i) != group_rows.get(i)
                        or current_record is None
                        or (issues and not set(issues) <= OWNER_ISSUES)
                        or current_record.vector != record.vector
                        or {
                            k: v
                            for k, v in (current_record.payload or {}).items()
                            if k != "user_id"
                        }
                        != {k: v for k, v in record.payload.items() if k != "user_id"}
                    ):
                        group_blocked.append(i)
                    elif not issues:
                        result["already_correct"] += 1
                    else:
                        ready.append(current_record)
                if (
                    group_blocked
                    or set(group_by_id) != set(attempt_ids)
                    or len(group_by_id) != len(group_records)
                ):
                    result["blocked"] += len(group_blocked) or len(attempt_ids)
                    result["skipped"] += len(ready)
                    sample([str(i) for i in group_blocked], "Owner group changed before write")
                    result["error"] = "Repair batch changed"
                    return result, 1
                if not ready:
                    continue
                batch = ready
                attempt_ids = [UUID(str(r.id)) for r in batch]
                try:
                    ack = await client.set_payload(
                        collection,
                        payload={"user_id": str(owner)},
                        points=guarded_selector(batch),
                        wait=True,
                    )
                    if ack.status != UpdateStatus.COMPLETED:
                        raise InventoryError("Payload update not acknowledged complete")
                    after_rows = await current_rows(engine, attempt_ids)
                    after = await client.retrieve(
                        collection,
                        [str(i) for i in attempt_ids],
                        with_payload=True,
                        with_vectors=True,
                    )
                    current = {canonical_uuid(r.id): r for r in after}
                    if set(current) != set(attempt_ids) or len(current) != len(after):
                        raise InventoryError("Payload read-back is incomplete")
                    failures = 0
                    for record, i in zip(batch, attempt_ids, strict=True):
                        now = current.get(i)
                        good = (
                            now is not None
                            and before_rows.get(i) == after_rows.get(i)
                            and not point_issues(now, after_rows.get(i), config.size)
                            and now.vector == record.vector
                            and {k: v for k, v in (now.payload or {}).items() if k != "user_id"}
                            == {k: v for k, v in record.payload.items() if k != "user_id"}
                        )
                        if good:
                            result["changed"] += 1
                        else:
                            failures += 1
                            sample([str(i)], "Payload update could not be verified")
                    if failures:
                        result["failed"] += failures
                        result["error"] = "Repair batch verification failed"
                        return result, 2
                except Exception:
                    # Provider outcome may be partial/unknown. Never count an acknowledgement alone.
                    result["failed"] += len(batch)
                    sample([str(i) for i in attempt_ids], "Payload update outcome uncertain")
                    raise InventoryError("Payload update failed or uncertain") from None
            if next_offset is None:
                break
            if next_offset == offset:
                raise InventoryError("Non-progressing repair pagination")
            offset = next_offset
        if scanned != preflight.scanned_points:
            raise InventoryError("Repair discovery changed or incomplete")
        verification = await inventory(engine, client, settings, batch_size, sample_limit)
        result["verification"] = verification.as_dict()
        if not verification.complete or verification.error:
            result["error"] = "Post-repair verification failed"
            return result, 2
        if verification.issues:
            result["error"] = "Post-repair coverage defects remain"
            return result, 1
        result.update(complete=True, clean=True)
        return result, 0
    except InventoryError as exc:
        result["error"] = str(exc)
    except Exception:
        result["error"] = "Repair storage operation failed"
    return result, 2
