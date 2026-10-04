"""Versioned allowlist and integrity checks for checked-in synthetic samples."""

from datetime import datetime
from pathlib import Path
from uuid import UUID, NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ingestion.extractors.plain_text import normalize_extracted_text
from app.ingestion.hash_util import compute_extracted_text_hash

CORPUS_ROOT = Path(__file__).resolve().parent / "corpus"


class SampleFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(pattern=r"^[a-z_]+\.txt$")
    id: UUID
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @property
    def document_id(self) -> UUID:
        return uuid5(NAMESPACE_URL, f"drivemind-demo/document/{self.id}")

    @property
    def external_id(self) -> str:
        return f"demo:{self.id}"


class DemoQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str
    question: str
    expected_files: list[str]
    expect_evidence: bool


class CorpusManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str
    title: str
    modified_at: datetime
    files: list[SampleFile] = Field(min_length=1, max_length=10)
    questions: list[DemoQuestion]

    @model_validator(mode="after")
    def validate_entries(self) -> "CorpusManifest":
        names = {entry.filename for entry in self.files}
        if len(names) != len(self.files) or len({entry.id for entry in self.files}) != len(names):
            raise ValueError("Duplicate corpus entry")
        if any(not set(q.expected_files) <= names for q in self.questions):
            raise ValueError("Question references an unapproved file")
        return self

    def read_sample(self, filename: str, *, root: Path = CORPUS_ROOT) -> str:
        entry = next((entry for entry in self.files if entry.filename == filename), None)
        if entry is None:
            raise ValueError("Unapproved sample filename")
        path = root / filename
        if path.is_symlink() or path.resolve().parent != root.resolve():
            raise ValueError("Sample path must remain inside the corpus")
        text = normalize_extracted_text(path.read_text(encoding="utf-8"))
        if compute_extracted_text_hash(text) != entry.sha256:
            raise ValueError("Sample content does not match the approved manifest")
        return text


def load_manifest() -> CorpusManifest:
    return CorpusManifest.model_validate_json((CORPUS_ROOT / "manifest.json").read_text())
