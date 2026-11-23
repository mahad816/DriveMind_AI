"""The index manifest: what the evaluation index held when it was built, checked against the frozen corpus.

This module is the record and its pure checks: building a manifest from what was read, listing its
differences from the frozen corpus, writing it. Reading the index and verifying it live is
``index_verify`` (``uv run python -m evaluation.rag_eval.index_verify verify``), which also decides whether a
frozen command may start. Nothing here calls a provider or a database.

A manifest written by ``cli setup --frozen`` after a passing verification has ``origin: "setup"``: it is the
receipt of the build, and the only record of which embedding model made the vectors (Qdrant does not store
it). Only such a receipt can let a frozen command start.

Chunk counts are compared only where a manifest froze one (the 49 committed files). A public PDF has no frozen
count: its count is recorded and must be at least one, nothing more.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.db.enums import DriveFileStatus
from app.embeddings.openai_service import resolve_embedding_dimension
from app.ingestion.chunking import DEFAULT_CHUNK_OVERLAP, DEFAULT_TARGET_CHUNK_SIZE
from app.ingestion.pipeline_version import EXTRACTION_PIPELINE_VERSION

from .frozen_corpus import FrozenCorpus
from .target import ANSWER_FIELDS, store_of

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


def build_index_manifest(
    corpus: FrozenCorpus,
    *,
    settings: Settings,
    indexed: Mapping[str, IndexedFile],
    qdrant_points: int | None,
    origin: str = "inspection",
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
        "origin": origin,  # "setup": written by cli setup after a passing verification; anything else is a note
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
            "name": store_of(settings).name,
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


def index_problems(
    manifest: Mapping[str, Any], corpus: FrozenCorpus, *, require_vectors: bool = False
) -> list[str]:
    """Differences between an index manifest and the frozen corpus (empty = consistent).

    A vector count that could not be read (``None``) is accepted unless ``require_vectors`` is set; every
    check that lets a command start sets it.
    """
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
    if points is None and require_vectors:
        problems.append("the vector store was not read, so the vectors are unchecked")
    if points is not None and points != chunk_sum:
        problems.append(f"vector count is {points}, the index holds {chunk_sum} chunks")
    return problems


def write_index_manifest(manifest: Mapping[str, Any], *, folder: Path = DEFAULT_FOLDER) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    store = manifest.get("store", {}).get("name", "unknown")
    path = folder / f"index_manifest_{manifest['corpus']['version_id']}_{store}_{stamp}.json"
    path.write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n")
    return path
