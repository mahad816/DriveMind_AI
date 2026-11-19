"""Corpus manifest, integrity checks and text access for the v2 evaluation.

Synthetic files are committed. Public documents are NOT committed: the manifest records their
source URL, licence and SHA-256, and ``fetch_public.py`` downloads and verifies them.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CORPUS_DIR = Path(__file__).resolve().parents[1] / "corpus"
MIME = {
    ".txt": "text/plain",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@dataclass(frozen=True)
class CorpusFile:
    path: str  # relative to CORPUS_DIR, e.g. "synthetic/budget_2026.txt"
    kind: str  # "synthetic" | "public"
    sha256: str
    meta: dict[str, Any]

    @property
    def name(self) -> str:
        return Path(self.path).name

    @property
    def mime_type(self) -> str:
        return MIME[Path(self.path).suffix.lower()]

    @property
    def absolute(self) -> Path:
        return CORPUS_DIR / self.path


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def synthetic_files() -> list[CorpusFile]:
    return [
        CorpusFile(f"synthetic/{p.name}", "synthetic", sha256_file(p), {})
        for p in sorted((CORPUS_DIR / "synthetic").glob("*.txt"))
    ]


def public_manifest() -> list[dict[str, Any]]:
    path = CORPUS_DIR / "public_manifest.json"
    return json.loads(path.read_text())["documents"] if path.exists() else []


def public_files(*, require_present: bool = True) -> list[CorpusFile]:
    files = []
    for entry in public_manifest():
        file = CorpusFile(f"public/{entry['filename']}", "public", entry["sha256"], entry)
        if require_present and not file.absolute.exists():
            raise FileNotFoundError(
                f"{file.path} is missing; run `python -m evaluation.rag_eval.fetch_public`"
            )
        files.append(file)
    return files


def verify(files: list[CorpusFile]) -> None:
    """Fail loudly if any public document changed upstream or was edited locally."""
    for file in files:
        if file.kind == "public" and sha256_file(file.absolute) != file.sha256:
            raise ValueError(f"{file.path} does not match its recorded SHA-256")


def extract_text(file: CorpusFile) -> str:
    """Text exactly as the product's own extractors see it (what retrieval can ever find)."""
    from app.ingestion.extractors.bootstrap import register_builtin_extractors
    from app.ingestion.extractors.registry import get_extractor

    register_builtin_extractors()
    return (
        get_extractor(file.mime_type)
        .extract(file.absolute.read_bytes(), mime_type=file.mime_type, filename=file.name)
        .text
    )
