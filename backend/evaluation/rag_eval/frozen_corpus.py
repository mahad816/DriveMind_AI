"""The complete frozen M1 corpus, selected from the committed manifests and checked file by file.

``v1_manifest.json`` freezes 49 files (synthetic, messy, the Marrowdale v1 documents and the three Google
exports) with their SHA-256, extracted-text digest and chunk count; ``public_manifest.json`` freezes the
public PDFs, and the corpus version binds both. This module reads those manifests; it keeps no file list of
its own, so the corpus can only change through them. Nothing here calls a provider or a database.

    frozen_problems()   every difference between the manifests and the files on disk (empty = intact)
    frozen_corpus()     the intact corpus as ``CorpusFile`` objects, or ``FrozenCorpusError`` listing every problem
    corpus_for(...)     the selection the evaluation commands use: the legacy one, or the frozen one

Chunk counts and text digests are recorded only where a manifest froze them (the 49 files); a public PDF
has none, and none is invented for it.
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import corpus_v1
from .corpus import (
    CORPUS_DIR,
    MIME,
    CorpusFile,
    messy_files,
    public_files,
    sha256_file,
    synthetic_files,
)

V1_MANIFEST = "v1_manifest.json"
PUBLIC_MANIFEST = "public_manifest.json"
MESSY_MANIFEST = "messy_manifest.json"


class FrozenCorpusError(ValueError):
    """The frozen corpus is not intact; ``problems`` names every difference."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("the frozen corpus is not intact:\n  " + "\n  ".join(problems))


@dataclass(frozen=True)
class FrozenCorpus:
    version_id: str
    public_manifest_sha256: str
    files: tuple[CorpusFile, ...]
    expected_chunks: Mapping[str, int]  # only files whose chunk count a manifest froze
    expected_text_sha256: Mapping[str, str]

    @property
    def files_digest(self) -> str:
        """Same formula as the run manifest's ``corpus.files_digest``, so the two can be compared."""
        pairs = sorted((f.path, f.sha256) for f in self.files)
        return hashlib.sha256(json.dumps(pairs).encode()).hexdigest()


def _load(path: Path, problems: list[str]) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        problems.append(f"{path.name}: cannot be read as JSON ({exc.__class__.__name__})")
        return None


def _manifest_entries(manifest: Any, problems: list[str]) -> list[dict[str, Any]]:
    entries = manifest.get("files") if isinstance(manifest, dict) else None
    if isinstance(entries, list) and all(
        isinstance(e, dict) and e.get("path") and e.get("sha256") for e in entries
    ):
        return list(entries)
    problems.append(f"{V1_MANIFEST}: has no usable 'files' list")
    return []


def _file_problems(root: Path, path: str, sha256: str) -> list[str]:
    absolute = root / path
    if not absolute.is_file():
        return [f"{path}: file is missing"]
    if sha256_file(absolute) != sha256:
        return [
            f"{path}: file does not match its recorded SHA-256 (changed, truncated or corrupted)"
        ]
    return []


def _check_loaded(
    root: Path, problems: list[str]
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]] | None:
    manifest = _load(root / V1_MANIFEST, problems)
    public = _load(root / PUBLIC_MANIFEST, problems)
    entries = _manifest_entries(manifest, problems)
    documents = public.get("documents") if isinstance(public, dict) else None
    if not isinstance(documents, list):
        problems.append(f"{PUBLIC_MANIFEST}: has no 'documents' list")
        documents = []
    if not entries or manifest is None:
        return None
    return manifest, entries, documents


def frozen_problems(root: Path = CORPUS_DIR) -> list[str]:
    """Every difference between the manifests and the files under ``root`` (empty = intact)."""
    problems: list[str] = []
    loaded = _check_loaded(root, problems)
    if loaded is None:
        return problems
    manifest, entries, documents = loaded

    paths = [e["path"] for e in entries]
    problems += [
        f"duplicate path {p} in {V1_MANIFEST}"
        for p in sorted({p for p in paths if paths.count(p) > 1})
    ]
    for entry in entries:
        path = entry["path"]
        if Path(path).suffix.lower() not in MIME:
            problems.append(f"{path}: unsupported file type")
        problems += _file_problems(root, path, entry["sha256"])
    problems += [
        f"{p}: file is in the corpus folders but not in the manifest"
        for p in sorted(set(corpus_v1._entries_by_path(root)) - set(paths))
    ]

    public_path = root / PUBLIC_MANIFEST
    if public_path.is_file() and sha256_file(public_path) != manifest.get("public_manifest_sha256"):
        problems.append(f"public manifest differs from the SHA-256 recorded in {V1_MANIFEST}")
    listed_public = set()
    for doc in documents:
        path = f"public/{doc.get('filename')}"
        listed_public.add(path)
        if Path(path).suffix.lower() not in MIME:
            problems.append(f"{path}: unsupported file type")
        problems += _file_problems(root, path, str(doc.get("sha256")))
    on_disk = {p.relative_to(root).as_posix() for p in (root / "public").glob("*") if p.is_file()}
    problems += [
        f"{p}: file is in the corpus folders but not in the manifest"
        for p in sorted(on_disk - listed_public)
    ]

    expected_version = corpus_v1.corpus_version(
        entries, str(manifest.get("public_manifest_sha256"))
    )
    if manifest.get("corpus_version") != expected_version:
        problems.append(
            f"corpus_version is {manifest.get('corpus_version')!r}, the manifest's files give {expected_version!r}"
        )

    google = manifest.get("google_exports", {})
    missing_google = sorted(set(google.get("expected", [])) - set(paths))
    if google.get("status") != "pinned" or missing_google:
        problems.append(
            f"Google exports must be pinned and all listed (status {google.get('status')!r}, "
            f"not listed: {missing_google})"
        )

    messy_path = root / MESSY_MANIFEST
    messy_recorded = _load(messy_path, problems)
    if isinstance(messy_recorded, dict):
        frozen_messy = {
            Path(e["path"]).name: e["sha256"] for e in entries if e.get("group") == "messy"
        }
        for name, digest in sorted(messy_recorded.get("files", {}).items()):
            if frozen_messy.get(name) != digest:
                problems.append(f"messy/{name}: {MESSY_MANIFEST} and {V1_MANIFEST} disagree")
        problems += [
            f"messy/{name}: {MESSY_MANIFEST} and {V1_MANIFEST} disagree"
            for name in sorted(set(frozen_messy) - set(messy_recorded.get("files", {})))
        ]

    names = [Path(p).name for p in [*paths, *sorted(listed_public)]]
    problems += [
        f"duplicate file name {n} (the index and the probes identify files by name)"
        for n in sorted({n for n in names if names.count(n) > 1})
    ]
    return problems


def frozen_corpus(root: Path = CORPUS_DIR) -> FrozenCorpus:
    """The intact frozen corpus. Raises ``FrozenCorpusError`` naming every problem otherwise.

    ``CorpusFile.absolute`` always points into the committed corpus folder; ``root`` exists so the checks can
    be run on a temporary copy.
    """
    problems = frozen_problems(root)
    if problems:
        raise FrozenCorpusError(problems)
    manifest = json.loads((root / V1_MANIFEST).read_text())
    entries = manifest["files"]
    public = json.loads((root / PUBLIC_MANIFEST).read_text())["documents"]
    files = [
        CorpusFile(e["path"], e["group"], e["sha256"], {"source": e.get("source")}) for e in entries
    ]
    files += [CorpusFile(f"public/{d['filename']}", "public", d["sha256"], d) for d in public]
    return FrozenCorpus(
        version_id=str(manifest["corpus_version"]),
        public_manifest_sha256=str(manifest["public_manifest_sha256"]),
        files=tuple(files),
        expected_chunks={e["path"]: int(e["chunks"]) for e in entries},
        expected_text_sha256={e["path"]: str(e["text_sha256"]) for e in entries},
    )


def corpus_for(*, frozen: bool, with_messy: bool) -> list[CorpusFile]:
    """The files an evaluation command works on.

    Default (legacy): synthetic and public files, plus the messy documents on request. Frozen: the complete
    M1 corpus; the messy documents are already part of it, so ``with_messy`` changes nothing.
    """
    if frozen:
        return list(frozen_corpus().files)
    files = synthetic_files() + public_files()
    return files + messy_files() if with_messy else files
