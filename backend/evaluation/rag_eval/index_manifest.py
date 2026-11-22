"""The index manifest: what the disposable evaluation index holds, checked against the frozen corpus.

    uv run python -m evaluation.rag_eval.index_manifest write     # read the eval index, write and check a manifest
    uv run python -m evaluation.rag_eval.index_manifest check [FILE]   # check a saved manifest (default: read the index)

Reading the index is free (PostgreSQL and Qdrant on loopback; no provider call). It only reads rows that belong
to the evaluation user, in a ``drivemind_eval`` store; ``target.assert_safe`` refuses anything else. The manifest
is written into the Git-ignored results folder.

Chunk counts are compared only where a manifest froze one (the 49 committed files). A public PDF has no frozen
count: its count is recorded and must be at least one, nothing more.
"""

import argparse
import asyncio
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Select, func, select

from app.core.config import Settings
from app.db.enums import DriveFileStatus
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.embeddings.openai_service import resolve_embedding_dimension
from app.embeddings.qdrant_connection import create_qdrant_client
from app.ingestion.chunking import DEFAULT_CHUNK_OVERLAP, DEFAULT_TARGET_CHUNK_SIZE
from app.ingestion.pipeline_version import EXTRACTION_PIPELINE_VERSION

from .frozen_corpus import FrozenCorpus, frozen_corpus
from .target import ANSWER_FIELDS, EVAL_USER_ID, assert_safe, eval_settings, session_factory

SCHEMA_VERSION = 1
DEFAULT_FOLDER = Path(__file__).resolve().parents[1] / "results"
ID_PREFIX = "eval:"  # target.ingest stores each file as drive_file_id "eval:<corpus path>"


@dataclass(frozen=True)
class IndexedFile:
    """What the index holds for one corpus file."""

    chunks: int
    text_sha256: str  # SHA-256 of the stored extracted text ("" if there is no document)
    pipeline_version: int
    status: str


def indexed_statement() -> Select[Any]:
    """Per-file state of the evaluation user's files. Read-only and scoped to ``EVAL_USER_ID``."""
    chunks = select(func.count(Chunk.id)).where(Chunk.document_id == Document.id).scalar_subquery()
    digest = func.encode(func.sha256(func.convert_to(Document.extracted_text, "UTF8")), "hex")
    return (
        select(
            DriveFile.drive_file_id,
            DriveFile.status,
            func.coalesce(chunks, 0),
            func.coalesce(digest, ""),
            func.coalesce(Document.pipeline_version, 0),
        )
        .select_from(DriveFile)
        .outerjoin(Document, Document.drive_file_id == DriveFile.id)
        .where(DriveFile.user_id == EVAL_USER_ID)
    )


async def read_indexed(settings: Settings) -> dict[str, IndexedFile]:
    """Corpus path -> what the index holds, for the evaluation user only."""
    assert_safe(settings)
    sessions = session_factory(settings)
    async with sessions() as db:
        rows = (await db.execute(indexed_statement())).all()
    return {
        str(drive_id).removeprefix(ID_PREFIX): IndexedFile(
            chunks=int(count),
            text_sha256=str(text_sha),
            pipeline_version=int(version),
            status=DriveFileStatus(status).value,
        )
        for drive_id, status, count, text_sha, version in rows
    }


async def count_vectors(settings: Settings) -> int | None:
    """Points in the evaluation collection, or ``None`` when it cannot be read (reported, not guessed)."""
    assert_safe(settings)
    client = create_qdrant_client(settings)
    try:
        return int((await client.count(settings.qdrant_collection, exact=True)).count)
    except Exception:  # noqa: BLE001 - an absent collection or a stopped container means "unchecked"
        return None
    finally:
        await client.close()


def build_index_manifest(
    corpus: FrozenCorpus,
    *,
    settings: Settings,
    indexed: Mapping[str, IndexedFile],
    qdrant_points: int | None,
) -> dict[str, Any]:
    by_path = {f.path: f for f in corpus.files}
    files: dict[str, Any] = {}
    for path, item in sorted(indexed.items()):
        known = by_path.get(path)
        files[path] = {
            "kind": known.kind if known else None,
            "sha256": known.sha256 if known else None,
            "chunks": item.chunks,
            "expected_chunks": corpus.expected_chunks.get(path),
            "text_sha256": item.text_sha256,
            "pipeline_version": item.pipeline_version,
            "status": item.status,
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "corpus": {
            "version_id": corpus.version_id,
            "files_digest": corpus.files_digest,
            "public_manifest_sha256": corpus.public_manifest_sha256,
            "files": len(corpus.files),
        },
        "embedding": {
            "model": settings.embedding_model,
            "dimension": resolve_embedding_dimension(settings.embedding_model),
        },
        "pipeline": {
            "extraction_pipeline_version": EXTRACTION_PIPELINE_VERSION,
            "chunk_target_size": DEFAULT_TARGET_CHUNK_SIZE,
            "chunk_overlap": DEFAULT_CHUNK_OVERLAP,
        },
        "store": {
            "database": str(settings.database_url).rsplit("/", 1)[-1],
            "collection": settings.qdrant_collection,
        },
        "settings": {name: getattr(settings, name) for name in ANSWER_FIELDS},
        "files": files,
        "totals": {
            "files": len(files),
            "chunks": sum(v["chunks"] for v in files.values()),
            "qdrant_points": qdrant_points,
        },
    }


def index_problems(manifest: Mapping[str, Any], corpus: FrozenCorpus) -> list[str]:
    """Differences between an index manifest and the frozen corpus (empty = consistent)."""
    problems: list[str] = []
    if manifest.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"index manifest schema version is {manifest.get('schema_version')!r}")
    recorded = manifest.get("corpus", {})
    if recorded.get("version_id") != corpus.version_id:
        problems.append(
            f"corpus version is {recorded.get('version_id')!r}, the frozen corpus is {corpus.version_id!r}"
        )
    if recorded.get("files_digest") != corpus.files_digest:
        problems.append("files digest differs from the frozen corpus")
    if recorded.get("public_manifest_sha256") != corpus.public_manifest_sha256:
        problems.append("public manifest checksum differs from the frozen corpus")
    pipeline = manifest.get("pipeline", {})
    for key, current in (
        ("extraction_pipeline_version", EXTRACTION_PIPELINE_VERSION),
        ("chunk_target_size", DEFAULT_TARGET_CHUNK_SIZE),
        ("chunk_overlap", DEFAULT_CHUNK_OVERLAP),
    ):
        if pipeline.get(key) != current:
            problems.append(f"{key} is {pipeline.get(key)!r}, the application uses {current!r}")
    embedding = manifest.get("embedding", {})
    try:
        if embedding.get("dimension") != resolve_embedding_dimension(str(embedding.get("model"))):
            problems.append(
                f"embedding dimension {embedding.get('dimension')!r} does not fit the model"
            )
    except Exception:  # noqa: BLE001 - an unsupported model name is the problem being reported
        problems.append(f"embedding model {embedding.get('model')!r} is not supported")
    if not str(manifest.get("store", {}).get("collection", "")).startswith("drivemind_eval"):
        problems.append("the index is not a drivemind_eval collection")

    files: Mapping[str, Mapping[str, Any]] = manifest.get("files", {})
    wanted = {f.path: f for f in corpus.files}
    problems += [f"{p}: frozen file is not in the index" for p in sorted(set(wanted) - set(files))]
    problems += [
        f"{p}: indexed file is not in the frozen corpus" for p in sorted(set(files) - set(wanted))
    ]
    for path in sorted(set(wanted) & set(files)):
        entry = files[path]
        if entry.get("status") != DriveFileStatus.INDEXED.value:
            problems.append(f"{path}: status is {entry.get('status')!r}, not indexed")
        if not isinstance(entry.get("chunks"), int) or entry["chunks"] < 1:
            problems.append(f"{path}: the index holds no chunks for it")
        if entry.get("sha256") != wanted[path].sha256:
            problems.append(f"{path}: recorded file checksum differs from the frozen corpus")
        frozen_chunks = corpus.expected_chunks.get(path)
        if frozen_chunks is not None and entry.get("chunks") != frozen_chunks:
            problems.append(f"{path}: {entry.get('chunks')} chunks indexed, {frozen_chunks} frozen")
        frozen_text = corpus.expected_text_sha256.get(path)
        if frozen_text is not None and entry.get("text_sha256") != frozen_text:
            problems.append(f"{path}: stored text differs from the frozen text digest")
        if entry.get("pipeline_version") != EXTRACTION_PIPELINE_VERSION:
            problems.append(
                f"{path}: extracted with pipeline version {entry.get('pipeline_version')!r}, "
                f"current is {EXTRACTION_PIPELINE_VERSION}"
            )

    totals = manifest.get("totals", {})
    if totals.get("files") != len(files):
        problems.append(
            f"total files is {totals.get('files')!r}, the entries add up to {len(files)}"
        )
    chunk_sum = sum(e.get("chunks", 0) for e in files.values() if isinstance(e.get("chunks"), int))
    if totals.get("chunks") != chunk_sum:
        problems.append(
            f"total chunks is {totals.get('chunks')!r}, the entries add up to {chunk_sum}"
        )
    points = totals.get("qdrant_points")
    if points is not None and points != chunk_sum:
        problems.append(f"vector count is {points}, the index holds {chunk_sum} chunks")
    return problems


def write_index_manifest(manifest: Mapping[str, Any], *, folder: Path = DEFAULT_FOLDER) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    path = folder / f"index_manifest_{manifest['corpus']['version_id']}_{stamp}.json"
    path.write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n")
    return path


async def record_index(settings: Settings, corpus: FrozenCorpus) -> tuple[Path, list[str]]:
    """Read the evaluation index, write its manifest and return the path and any inconsistencies."""
    manifest = build_index_manifest(
        corpus,
        settings=settings,
        indexed=await read_indexed(settings),
        qdrant_points=await count_vectors(settings),
    )
    return write_index_manifest(manifest), index_problems(manifest, corpus)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("command", choices=["write", "check"])
    parser.add_argument("file", nargs="?", help="saved manifest (check)")
    args = parser.parse_args(argv)
    corpus = frozen_corpus()
    if args.command == "check" and args.file:
        problems = index_problems(json.loads(Path(args.file).read_text()), corpus)
        where = args.file
    else:
        path, problems = asyncio.run(record_index(eval_settings(tool_agent=False), corpus))
        where = str(path)
    print(f"index manifest {where}: {len(problems)} problem(s)")
    for line in problems:
        print(" ", line)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
