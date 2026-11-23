"""Verify the evaluation index against the frozen corpus, and refuse to start a frozen command on a bad one.

    uv run python -m evaluation.rag_eval.index_verify verify [--store v3]   # free: read the store, report
    uv run python -m evaluation.rag_eval.index_verify check FILE             # free: a saved manifest against the corpus

One verifier serves ``cli setup --frozen`` (after the build), ``cli run`` / ``cli rescore`` with ``--frozen`` and
both probes with ``--frozen`` (before any paid call). Reading the store is free: PostgreSQL and Qdrant on loopback,
only rows of the evaluation user, ``target.assert_safe`` first.

What is checked, file by file and chunk by chunk (not only counts):

* every frozen file is in the store exactly once, as one indexed document, and nothing else is there;
* the stored text has the expected digest, the pipeline version is current, and the stored chunks equal the
  chunks the current chunker makes from the expected text (so a stale, truncated or edited chunk is found even
  when the counts agree), public PDFs included;
* every chunk has exactly one Qdrant point with the same identifier, whose payload names the same chunk, file,
  owner, position and text version, and whose vector has the embedding model's dimension, is finite and unit
  length, and is not shared with a chunk of different text;
* the collection has the dimension of the configured embedding model and cosine distance;
* a Qdrant or database failure is a failure, never "unchecked".

Two modes. After a build ``setup`` passes the text it has just extracted from the original files, so the
expectation is the original document. A frozen command has no such text (re-reading all 33 public PDFs takes
about two minutes), so it compares against the frozen digests of the committed manifests and, for the public
PDFs, the digests the passing setup recorded in its receipt; the expected chunks are made from the stored text.
"""

import argparse
import asyncio
import hashlib
import json
import math
import sys
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from sqlalchemy import Select, func, select

from app.core.config import Settings
from app.db.enums import DriveFileStatus
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.embeddings.openai_service import resolve_embedding_dimension
from app.embeddings.qdrant_connection import create_qdrant_client
from app.ingestion.chunking import chunk_text
from app.ingestion.pipeline_version import EXTRACTION_PIPELINE_VERSION

from .frozen_corpus import FrozenCorpus, frozen_corpus
from .index_manifest import (
    DEFAULT_FOLDER,
    ID_PREFIX,
    IndexedFile,
    build_index_manifest,
    index_problems,
    write_index_manifest,
)
from .target import (
    EVAL_USER_ID,
    LEGACY_STORE,
    EvalStore,
    assert_safe,
    eval_settings,
    store_for,
)

SCROLL_PAGE = 256
UNIT_TOLERANCE = 0.02  # embeddings are returned normalised to length 1
MAX_LISTED = 12
LIMITATIONS = (
    "A vector cannot be proven to be the embedding of its chunk's text without embedding the text again "
    "(a paid call); what is checked is identity, ownership, dimension, finiteness, unit length and that no two "
    "chunks of different text share a vector.",
    "Qdrant does not store which embedding model made a vector; the model is read from the manifest the passing "
    "setup wrote, and the collection's dimension is checked against it. A rebuild with another model of the "
    "same dimension outside setup could not be told apart.",
)


# ---- what was read -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DbChunk:
    id: uuid.UUID
    index: int
    text: str
    text_hash: str  # the extracted_text_hash recorded in the chunk's metadata


@dataclass(frozen=True)
class DbDocument:
    id: uuid.UUID
    text_sha256: str
    text_hash: str  # the extracted_text_hash column
    pipeline_version: int
    chunks: tuple[DbChunk, ...]
    text: str = ""


@dataclass(frozen=True)
class DbFile:
    pk: uuid.UUID
    name: str
    status: str
    owner: uuid.UUID
    documents: tuple[DbDocument, ...]


@dataclass(frozen=True)
class DbSnapshot:
    files: Mapping[
        str, tuple[DbFile, ...]
    ]  # corpus path -> every file record that carries that path
    foreign_files: int  # file records of any other owner
    orphan_chunks: int  # chunk rows that belong to no file of the evaluation user


@dataclass(frozen=True)
class QdrantPoint:
    id: str
    payload: Mapping[str, Any]
    vector: tuple[float, ...] | None


@dataclass(frozen=True)
class QdrantSnapshot:
    vector_size: int | None
    distance: str | None
    points: tuple[QdrantPoint, ...]


@dataclass(frozen=True)
class ExpectedFile:
    path: str
    text_sha256: str
    chunk_texts: tuple[str, ...] | None  # None: not known, only the text digest is compared


@dataclass(frozen=True)
class IndexReport:
    files: int
    chunks: int
    points: int
    problems: list[str]
    limitations: list[str] = field(default_factory=lambda: list(LIMITATIONS))


@dataclass(frozen=True)
class VerifiedIndex:
    """A store that passed verification, with the settings every later step must use (never rebuilt elsewhere)."""

    store: EvalStore
    settings: Settings
    manifest: str
    report: IndexReport


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---- comparing (pure) ----------------------------------------------------------------------------------------


def _limited(path: str, lines: list[str]) -> list[str]:
    if len(lines) <= 3:
        return lines
    return [*lines[:3], f"{path}: ... and {len(lines) - 3} more of the same kind"]


def _file_problems(
    path: str, exp: ExpectedFile, files: tuple[DbFile, ...], user_id: uuid.UUID
) -> tuple[list[str], DbFile | None]:
    problems: list[str] = []
    if len(files) > 1:
        problems.append(f"{path}: {len(files)} file records carry this path (duplicate)")
    file = next(iter(files))
    if file.status != DriveFileStatus.INDEXED.value:
        problems.append(f"{path}: status is {file.status!r}, not indexed")
    if file.owner != user_id:
        problems.append(f"{path}: the file record has another owner than the evaluation user")
    if len(file.documents) != 1:
        problems.append(f"{path}: {len(file.documents)} documents, exactly 1 expected")
        return problems, None
    doc = file.documents[0]
    if doc.pipeline_version != EXTRACTION_PIPELINE_VERSION:
        problems.append(
            f"{path}: extracted with pipeline version {doc.pipeline_version}, "
            f"current is {EXTRACTION_PIPELINE_VERSION}"
        )
    if doc.text_sha256 != exp.text_sha256:
        problems.append(f"{path}: stored text differs from the expected text (digest mismatch)")
    chunks = sorted(doc.chunks, key=lambda c: c.index)
    if not chunks:
        problems.append(f"{path}: the index holds no chunks (0 chunks) for it")
        return problems, file
    if [c.index for c in chunks] != list(range(len(chunks))):
        problems.append(
            f"{path}: chunk numbering is not 0..{len(chunks) - 1} without gaps or repeats"
        )
    stale = [c.index for c in chunks if c.text_hash != doc.text_hash]
    if stale:
        problems.append(
            f"{path}: chunk(s) {stale[:5]} were built from a different version of the text than the stored document"
        )
    if exp.chunk_texts is not None:
        if len(chunks) != len(exp.chunk_texts):
            problems.append(
                f"{path}: {len(chunks)} chunks indexed, {len(exp.chunk_texts)} expected"
            )
        differing = [
            f"{path}: chunk {c.index} differs from the expected chunk text"
            for c, wanted in zip(chunks, exp.chunk_texts, strict=False)
            if c.text != wanted
        ]
        problems += _limited(path, differing)
    return problems, file


def _vector_problems(label: str, vector: tuple[float, ...] | None, dimension: int) -> list[str]:
    if vector is None:
        return [f"{label}: the point has no vector data"]
    if len(vector) != dimension:
        return [f"{label}: vector has {len(vector)} values, the model produces {dimension}"]
    if not all(math.isfinite(x) for x in vector):
        return [f"{label}: vector contains non-finite values"]
    norm = math.sqrt(sum(x * x for x in vector))
    if abs(norm - 1.0) > UNIT_TOLERANCE:
        return [
            f"{label}: vector length is {norm:.3f}, embeddings are unit length (zero, scaled or corrupt)"
        ]
    return []


def compare_index(
    expected: Mapping[str, ExpectedFile],
    db: DbSnapshot,
    qdrant: QdrantSnapshot,
    *,
    embedding_dimension: int,
    user_id: uuid.UUID,
) -> list[str]:
    """Every difference between what the index should hold and what was read (empty = consistent)."""
    problems: list[str] = []
    problems += [
        f"{p}: frozen file is not in the index" for p in sorted(set(expected) - set(db.files))
    ]
    problems += [
        f"{p}: indexed file is not in the frozen corpus"
        for p in sorted(set(db.files) - set(expected))
    ]
    if db.foreign_files:
        problems.append(
            f"{db.foreign_files} file record(s) belong to another owner than the evaluation user"
        )
    if db.orphan_chunks:
        problems.append(
            f"{db.orphan_chunks} orphan chunk row(s) belong to no file of the evaluation user"
        )

    chunk_owner: dict[str, tuple[str, DbFile, DbChunk]] = {}
    for path in sorted(set(expected) & set(db.files)):
        found, file = _file_problems(path, expected[path], db.files[path], user_id)
        problems += found
        if file is not None and len(file.documents) == 1:
            for chunk in file.documents[0].chunks:
                chunk_owner[str(chunk.id)] = (path, file, chunk)

    if qdrant.vector_size != embedding_dimension:
        problems.append(
            f"collection vector dimension is {qdrant.vector_size!r}, the embedding model produces {embedding_dimension}"
        )
    if (qdrant.distance or "").lower() != "cosine":
        problems.append(f"collection distance is {qdrant.distance!r}, retrieval needs cosine")

    seen: dict[str, QdrantPoint] = {}
    for point in qdrant.points:
        if point.id in seen:
            problems.append(f"point {point.id}: appears more than once")
        seen[point.id] = point
    problems += [
        f"{path}: chunk {chunk.index} ({cid}) has no vector in Qdrant"
        for cid, (path, _, chunk) in sorted(chunk_owner.items())
        if cid not in seen
    ]
    problems += [
        f"point {pid}: has no chunk in the index (stale or foreign vector)"
        for pid in sorted(set(seen) - set(chunk_owner))
    ]

    by_vector: dict[tuple[float, ...], list[tuple[str, str]]] = defaultdict(list)
    for pid, (path, file, chunk) in sorted(chunk_owner.items()):
        found_point = seen.get(pid)
        if found_point is None:
            continue
        point = found_point
        label = f"{path}: chunk {chunk.index} (point {pid})"
        wanted = {
            "chunk_id": pid,
            "drive_file_id": str(file.pk),
            "user_id": str(user_id),
            "filename": file.name,
            "chunk_index": chunk.index,
            "extracted_text_hash": chunk.text_hash,
        }
        problems += [
            f"{label}: payload {key} is {point.payload.get(key)!r}, expected {value!r}"
            for key, value in wanted.items()
            if point.payload.get(key) != value
        ]
        vector_found = _vector_problems(label, point.vector, embedding_dimension)
        problems += vector_found
        if not vector_found and point.vector is not None:
            by_vector[tuple(round(x, 6) for x in point.vector)].append((pid, chunk.text))
    for group in by_vector.values():
        if len({text for _, text in group}) > 1:
            problems.append(
                f"points {', '.join(pid for pid, _ in group[:4])}: an identical vector is stored for chunks of different text"
            )
    return problems


# ---- the expectation -----------------------------------------------------------------------------------------


def expected_from_texts(corpus: FrozenCorpus, texts: Mapping[str, str]) -> dict[str, ExpectedFile]:
    """The expectation after a build: the text just extracted from the original files and its chunks."""
    return {
        f.path: ExpectedFile(
            f.path,
            sha256_text(texts[f.path]),
            tuple(c.text for c in chunk_text(texts[f.path])),
        )
        for f in corpus.files
    }


def extraction_problems(corpus: FrozenCorpus, texts: Mapping[str, str]) -> list[str]:
    """Freshly extracted text against the digests and chunk counts the manifests froze (free, no store needed)."""
    problems: list[str] = []
    for path, wanted in sorted(corpus.expected_text_sha256.items()):
        if path in texts and sha256_text(texts[path]) != wanted:
            problems.append(f"{path}: the current extraction differs from the frozen text digest")
    for path, count in sorted(corpus.expected_chunks.items()):
        if path in texts and len(chunk_text(texts[path])) != count:
            problems.append(
                f"{path}: the current chunker makes a different number of chunks than the {count} frozen"
            )
    problems += [
        f"{f.path}: extracts to no text"
        for f in corpus.files
        if f.path in texts and not texts[f.path].strip()
    ]
    return problems


def expected_from_store(
    corpus: FrozenCorpus, receipt: Mapping[str, Any], db: DbSnapshot
) -> dict[str, ExpectedFile]:
    """The expectation of a frozen command: frozen digests, or the setup receipt's for the public PDFs.

    The expected chunks are made from the stored text, and only when that text has the expected digest.
    """
    recorded = receipt.get("files", {})
    out: dict[str, ExpectedFile] = {}
    for f in corpus.files:
        digest = corpus.expected_text_sha256.get(f.path) or str(
            recorded.get(f.path, {}).get("text_sha256", "")
        )
        chunks: tuple[str, ...] | None = None
        stored = db.files.get(f.path)
        if stored and len(stored[0].documents) == 1:
            doc = stored[0].documents[0]
            if digest and sha256_text(doc.text) == digest:
                chunks = tuple(c.text for c in chunk_text(doc.text))
        out[f.path] = ExpectedFile(f.path, digest, chunks)
    return out


def indexed_files(db: DbSnapshot) -> dict[str, IndexedFile]:
    """The per-file figures a manifest records, from the same snapshot that is verified."""
    out: dict[str, IndexedFile] = {}
    for path, files in db.files.items():
        file = files[0]
        doc = file.documents[0] if file.documents else None
        out[path] = IndexedFile(
            chunks=sum(len(d.chunks) for d in file.documents),
            text_sha256=doc.text_sha256 if doc else "",
            pipeline_version=doc.pipeline_version if doc else 0,
            status=file.status,
        )
    return out


# ---- reading the store (free) -----------------------------------------------------------------------------------


def snapshot_statements() -> tuple[Select[Any], Select[Any]]:
    """The two reads of the database snapshot. Read-only; both are scoped to ``EVAL_USER_ID``."""
    files = (
        select(
            DriveFile.id,
            DriveFile.drive_file_id,
            DriveFile.name,
            DriveFile.status,
            DriveFile.user_id,
            Document.id,
            Document.extracted_text,
            Document.extracted_text_hash,
            Document.pipeline_version,
        )
        .select_from(DriveFile)
        .outerjoin(Document, Document.drive_file_id == DriveFile.id)
        .where(DriveFile.user_id == EVAL_USER_ID)
    )
    chunks = (
        select(
            Chunk.id,
            Chunk.document_id,
            Chunk.chunk_index,
            Chunk.text,
            Chunk.metadata_json["extracted_text_hash"].as_string(),
        )
        .join(Document, Chunk.document_id == Document.id)
        .join(DriveFile, Document.drive_file_id == DriveFile.id)
        .where(DriveFile.user_id == EVAL_USER_ID)
    )
    return files, chunks


async def read_db_snapshot(settings: Settings) -> DbSnapshot:
    from .target import session_factory

    assert_safe(settings)
    files_statement, chunks_statement = snapshot_statements()
    sessions = session_factory(settings)
    async with sessions() as db:
        file_rows = (await db.execute(files_statement)).all()
        chunk_rows = (await db.execute(chunks_statement)).all()
        foreign = int(
            await db.scalar(
                select(func.count(DriveFile.id)).where(DriveFile.user_id != EVAL_USER_ID)
            )
            or 0
        )
        total_chunks = int(await db.scalar(select(func.count(Chunk.id))) or 0)
    by_doc: dict[uuid.UUID, list[DbChunk]] = defaultdict(list)
    for chunk_id, document_id, index, text, text_hash in chunk_rows:
        by_doc[document_id].append(DbChunk(chunk_id, int(index), str(text), str(text_hash or "")))
    grouped: dict[str, list[DbFile]] = defaultdict(list)
    documents: dict[tuple[str, uuid.UUID], list[DbDocument]] = defaultdict(list)
    heads: dict[tuple[str, uuid.UUID], tuple[uuid.UUID, str, str, uuid.UUID]] = {}
    for pk, drive_id, name, status, owner, doc_id, text, text_hash, version in file_rows:
        path = str(drive_id).removeprefix(ID_PREFIX)
        key = (path, pk)
        heads[key] = (pk, str(name), DriveFileStatus(status).value, owner)
        if doc_id is not None:
            body = str(text or "")
            documents[key].append(
                DbDocument(
                    doc_id,
                    sha256_text(body),
                    str(text_hash),
                    int(version),
                    tuple(by_doc.get(doc_id, ())),
                    body,
                )
            )
    for key, (pk, name, status, owner) in heads.items():
        grouped[key[0]].append(DbFile(pk, name, status, owner, tuple(documents.get(key, ()))))
    return DbSnapshot(
        files={path: tuple(files) for path, files in grouped.items()},
        foreign_files=foreign,
        orphan_chunks=max(total_chunks - len(chunk_rows), 0),
    )


async def read_qdrant_snapshot(settings: Settings) -> QdrantSnapshot:
    """Every point of the evaluation collection with payload and vector. Raises if anything cannot be read."""
    assert_safe(settings)
    client = create_qdrant_client(settings)
    try:
        info = await client.get_collection(settings.qdrant_collection)
        params = info.config.params.vectors
        size = getattr(params, "size", None)
        distance = getattr(getattr(params, "distance", None), "value", None)
        points: list[QdrantPoint] = []
        offset: Any = None
        while True:
            page, offset = await client.scroll(
                settings.qdrant_collection,
                limit=SCROLL_PAGE,
                offset=offset,
                with_payload=True,
                with_vectors=True,
            )
            for record in page:
                raw = record.vector
                points.append(
                    QdrantPoint(
                        str(record.id),
                        dict(record.payload or {}),
                        tuple(float(x) for x in cast(list[float], raw))
                        if isinstance(raw, list)
                        else None,
                    )
                )
            if offset is None:
                break
        return QdrantSnapshot(size, distance, tuple(points))
    finally:
        await client.close()


Reader = Callable[[Settings], Awaitable[Any]]


# ---- verifying -------------------------------------------------------------------------------------------------


async def verify_index(
    settings: Settings,
    corpus: FrozenCorpus,
    *,
    texts: Mapping[str, str] | None = None,
    receipt: Mapping[str, Any] | None = None,
    read_db: Reader = read_db_snapshot,
    read_qdrant: Reader = read_qdrant_snapshot,
) -> tuple[IndexReport, DbSnapshot | None, QdrantSnapshot | None]:
    """Read the store and compare it with the expectation. Any read failure is reported as a problem.

    Pass ``texts`` (extracted from the original files) after a build, or ``receipt`` (the setup manifest) for a
    frozen command; exactly one of them.
    """
    if (texts is None) == (receipt is None):
        raise ValueError("pass either the freshly extracted texts or the setup receipt")
    assert_safe(settings)
    problems: list[str] = []
    db: DbSnapshot | None = None
    qdrant: QdrantSnapshot | None = None
    try:
        db = await read_db(settings)
    except Exception as exc:  # noqa: BLE001 - whatever the cause, the database could not be verified
        problems.append(
            f"the database could not be read ({exc.__class__.__name__}); the index is unverified"
        )
    try:
        qdrant = await read_qdrant(settings)
    except Exception as exc:  # noqa: BLE001
        problems.append(
            f"Qdrant could not be read ({exc.__class__.__name__}); the vectors are unverified"
        )
    if db is None or qdrant is None:
        return IndexReport(0, 0, 0, problems), db, qdrant
    if texts is not None:
        problems += extraction_problems(corpus, texts)
        expected = expected_from_texts(corpus, texts)
    else:
        assert receipt is not None
        expected = expected_from_store(corpus, receipt, db)
    problems += compare_index(
        expected,
        db,
        qdrant,
        embedding_dimension=resolve_embedding_dimension(settings.embedding_model),
        user_id=EVAL_USER_ID,
    )
    chunks = sum(len(d.chunks) for files in db.files.values() for d in files[0].documents)
    return IndexReport(len(db.files), chunks, len(qdrant.points), problems), db, qdrant


def record_receipt(
    settings: Settings,
    corpus: FrozenCorpus,
    db: DbSnapshot,
    qdrant: QdrantSnapshot,
    *,
    folder: Path = DEFAULT_FOLDER,
) -> Path:
    """Write the setup receipt. Call it only after ``verify_index`` found no problem."""
    manifest = build_index_manifest(
        corpus,
        settings=settings,
        indexed=indexed_files(db),
        qdrant_points=len(qdrant.points),
        origin="setup",
    )
    return write_index_manifest(manifest, folder=folder)


# ---- the gate ----------------------------------------------------------------------------------------------------


def _latest_receipt(
    store: EvalStore, folder: Path
) -> tuple[Path | None, dict[str, Any] | None, int]:
    found: list[tuple[str, str, Path, dict[str, Any]]] = []
    unreadable = 0
    for path in sorted(folder.glob("index_manifest_*.json")):
        try:
            manifest = json.loads(path.read_text())
        except (OSError, ValueError):
            unreadable += 1
            continue
        if (
            isinstance(manifest, dict)
            and manifest.get("origin") == "setup"
            and manifest.get("store", {}).get("collection") == store.collection
            and manifest.get("store", {}).get("database") == store.database
        ):
            found.append((str(manifest.get("created_at", "")), path.name, path, manifest))
    if not found:
        return None, None, unreadable
    _, _, path, manifest = max(found)
    return path, manifest, unreadable


def _stop(store: EvalStore, problems: Sequence[str]) -> SystemExit:
    listed = "\n  ".join(problems[:MAX_LISTED])
    more = f"\n  ... and {len(problems) - MAX_LISTED} more" if len(problems) > MAX_LISTED else ""
    return SystemExit(
        f"INDEX NOT VERIFIED: {store.database} cannot be used for a frozen measurement "
        f"({len(problems)} problem(s)):\n  {listed}{more}\n"
        "Nothing was called. Rebuild into a new store with `cli setup --frozen --store vN`, "
        "then check it with `python -m evaluation.rag_eval.index_verify verify --store vN`."
    )


async def require_verified_index(
    store: EvalStore,
    *,
    tool_agent: bool = True,
    chat_model: str | None = None,
    corpus: FrozenCorpus | None = None,
    folder: Path = DEFAULT_FOLDER,
    read_db: Reader = read_db_snapshot,
    read_qdrant: Reader = read_qdrant_snapshot,
) -> VerifiedIndex:
    """Stop (``SystemExit``) unless ``store`` holds exactly the frozen corpus, intact and as built by setup.

    Free. Returns the settings of the verified store: the command must use them, so the store it measures is
    the store that was verified.
    """
    if store == LEGACY_STORE:
        raise SystemExit(
            f"{LEGACY_STORE.database} (v2) is the legacy store and is never used for the frozen corpus."
        )
    frozen = corpus if corpus is not None else frozen_corpus()
    settings = eval_settings(tool_agent=tool_agent, chat_model=chat_model, store=store)
    path, receipt, unreadable = _latest_receipt(store, folder)
    if receipt is None or path is None:
        note = f" ({unreadable} unreadable manifest file(s) ignored)" if unreadable else ""
        raise _stop(
            store,
            [f"no index manifest from a passing `cli setup --frozen` exists for this store{note}"],
        )
    problems = index_problems(receipt, frozen, require_vectors=True)
    recorded_model = receipt.get("embedding", {}).get("model")
    if recorded_model != settings.embedding_model:
        problems.append(
            f"the index was built with embedding model {recorded_model!r}, the configured model is {settings.embedding_model!r}"
        )
    report, db, qdrant = await verify_index(
        settings, frozen, receipt=receipt, read_db=read_db, read_qdrant=read_qdrant
    )
    problems += report.problems
    if db is not None and qdrant is not None:
        live = {p: i.chunks for p, i in indexed_files(db).items()}
        built = {p: e.get("chunks") for p, e in receipt.get("files", {}).items()}
        problems += [
            f"{p}: {live.get(p)} chunks now, {built.get(p)} when setup built the index (changed since)"
            for p in sorted(set(live) | set(built))
            if live.get(p) != built.get(p) and p in live and p in built
        ]
        if receipt.get("totals", {}).get("qdrant_points") != len(qdrant.points):
            problems.append(
                f"{len(qdrant.points)} vectors now, {receipt.get('totals', {}).get('qdrant_points')} when setup built the index (changed since)"
            )
    if problems:
        raise _stop(store, problems)
    return VerifiedIndex(store, settings, path.name, report)


# ---- command line ------------------------------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("command", choices=["verify", "check"])
    parser.add_argument("file", nargs="?", help="saved manifest (check)")
    parser.add_argument("--store", help="the frozen store to verify (default v3)")
    args = parser.parse_args(argv)
    corpus = frozen_corpus()
    if args.command == "check":
        if not args.file:
            parser.error("check needs a manifest file")
        problems = index_problems(
            json.loads(Path(args.file).read_text()), corpus, require_vectors=True
        )
        print(f"index manifest {args.file}: {len(problems)} problem(s)")
        for line in problems:
            print(" ", line)
        return 1 if problems else 0
    store = store_for(frozen=True, name=args.store)
    try:
        verified = asyncio.run(require_verified_index(store))
    except SystemExit as exc:
        print(exc)
        return 1
    r = verified.report
    print(
        f"{store.database}: verified ({r.files} files, {r.chunks} chunks, {r.points} vectors; receipt {verified.manifest})"
    )
    print("Not provable without a paid call:")
    for line in r.limitations:
        print(" -", line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
