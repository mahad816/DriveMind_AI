"""The complete frozen M1 corpus is selected from the committed manifests, and every deviation is named (free).

Each breaking test copies the small corpus folders into a temporary root (the 46 MB of public PDFs are
symlinked, never copied), changes one thing and expects one named problem. No provider, no database.
"""

import copy
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from evaluation.rag_eval import corpus_v1
from evaluation.rag_eval.corpus import (
    CORPUS_DIR,
    MIME,
    messy_files,
    public_files,
    synthetic_files,
    v1_files,
)
from evaluation.rag_eval.frozen_corpus import (
    FrozenCorpusError,
    corpus_for,
    frozen_corpus,
    frozen_problems,
)

REAL = json.loads((CORPUS_DIR / "v1_manifest.json").read_text())


@pytest.fixture
def root(tmp_path: Path) -> Path:
    for folder in ("v1", "messy", "synthetic", "google"):
        shutil.copytree(CORPUS_DIR / folder, tmp_path / folder)
    (tmp_path / "public").mkdir()
    for source in (CORPUS_DIR / "public").glob("*.pdf"):
        (tmp_path / "public" / source.name).symlink_to(source)
    for name in ("v1_manifest.json", "public_manifest.json", "messy_manifest.json"):
        shutil.copy(CORPUS_DIR / name, tmp_path / name)
    return tmp_path


def rewrite_manifest(root: Path, change: Any) -> None:
    path = root / "v1_manifest.json"
    manifest = copy.deepcopy(json.loads(path.read_text()))
    change(manifest)
    path.write_text(json.dumps(manifest))


def break_file(root: Path, relative: str, data: bytes) -> None:
    target = root / relative
    target.unlink()  # a symlinked public file must not write through to the real one
    target.write_bytes(data)


# ---- the real corpus -------------------------------------------------------------------------------------


def test_the_real_frozen_corpus_is_accepted_and_complete():
    assert frozen_problems() == []
    corpus = frozen_corpus()
    paths = [f.path for f in corpus.files]
    assert len(paths) == len(set(paths))
    by_kind = {k: sum(f.kind == k for f in corpus.files) for k in {f.kind for f in corpus.files}}
    assert set(by_kind) == {"synthetic", "messy", "v1", "google", "public"}
    assert by_kind["synthetic"] == len(synthetic_files())
    assert by_kind["messy"] == len(messy_files())
    assert by_kind["public"] == len(public_files())
    assert by_kind["v1"] + by_kind["google"] == len(v1_files())
    assert len(corpus.files) == len(REAL["files"]) + len(public_files())
    assert corpus.version_id == REAL["corpus_version"]


def test_every_supported_format_is_present_and_has_a_mime_type():
    corpus = frozen_corpus()
    suffixes = {Path(f.path).suffix for f in corpus.files}
    assert {".txt", ".md", ".csv", ".pdf", ".docx", ".pptx", ".xlsx"} <= suffixes
    assert suffixes <= set(MIME)
    assert all(f.mime_type == MIME[Path(f.path).suffix] for f in corpus.files)
    assert all(f.absolute.is_file() for f in corpus.files)


def test_chunk_counts_are_only_the_frozen_ones_and_never_invented_for_public_files():
    corpus = frozen_corpus()
    assert set(corpus.expected_chunks) == {e["path"] for e in REAL["files"]}
    assert not [p for p in corpus.expected_chunks if p.startswith("public/")]
    assert all(n >= 1 for n in corpus.expected_chunks.values())
    assert set(corpus.expected_text_sha256) == set(corpus.expected_chunks)


def test_the_corpus_identity_binds_the_files_and_the_public_manifest():
    corpus = frozen_corpus()
    assert corpus.public_manifest_sha256 == REAL["public_manifest_sha256"]
    assert len(corpus.files_digest) == 64
    assert frozen_corpus().files_digest == corpus.files_digest  # deterministic


def test_the_frozen_set_is_a_superset_of_every_legacy_selection():
    from evaluation.rag_eval.cli import corpus_files

    frozen = {f.path: f for f in corpus_for(frozen=True, with_messy=False)}
    legacy = {f.path: f for f in corpus_files(with_messy=True)}
    assert set(legacy) <= set(frozen)
    assert all(frozen[p].sha256 == legacy[p].sha256 for p in legacy)


# ---- legacy behaviour is unchanged -------------------------------------------------------------------------


def test_legacy_selection_is_unchanged_by_default():
    default = corpus_for(frozen=False, with_messy=False)
    assert [f.path for f in default] == [f.path for f in synthetic_files() + public_files()]
    with_messy = corpus_for(frozen=False, with_messy=True)
    assert [f.path for f in with_messy] == [
        f.path for f in synthetic_files() + public_files() + messy_files()
    ]


def test_frozen_selection_ignores_the_messy_flag():
    assert [f.path for f in corpus_for(frozen=True, with_messy=True)] == [
        f.path for f in corpus_for(frozen=True, with_messy=False)
    ]


# ---- missing, changed and unexpected files ------------------------------------------------------------------


def test_a_fabricated_copy_of_the_real_corpus_is_accepted(root):
    assert frozen_problems(root) == []


def test_a_missing_manifest_file_is_named(root):
    (root / "v1" / "cooperative_bylaws.txt").unlink()
    assert any("v1/cooperative_bylaws.txt" in p and "missing" in p for p in frozen_problems(root))


def test_a_changed_file_is_named(root):
    path = root / "synthetic" / "budget_2026.txt"
    path.write_text(path.read_text() + "\nAn edit.")
    assert any("synthetic/budget_2026.txt" in p and "SHA-256" in p for p in frozen_problems(root))


def test_a_truncated_binary_file_is_named(root):
    path = root / "v1" / "cold_chain_operations_manual.pdf"
    path.write_bytes(path.read_bytes()[:100])
    assert any("cold_chain_operations_manual.pdf" in p for p in frozen_problems(root))


def test_an_empty_file_is_named(root):
    (root / "google" / "google_open_day_rota.xlsx").write_bytes(b"")
    assert any("google_open_day_rota.xlsx" in p for p in frozen_problems(root))


def test_a_missing_public_pdf_is_named(root):
    (root / "public" / "nist_sp800_145.pdf").unlink()
    assert any("public/nist_sp800_145.pdf" in p and "missing" in p for p in frozen_problems(root))


def test_a_changed_public_pdf_is_named(root):
    break_file(root, "public/nist_sp800_145.pdf", b"%PDF-1.4 not the real one")
    assert any("public/nist_sp800_145.pdf" in p and "SHA-256" in p for p in frozen_problems(root))


def test_an_unlisted_file_in_a_corpus_folder_is_named(root):
    (root / "synthetic" / "stray.txt").write_text("not frozen")
    (root / "public" / "stray.pdf").write_bytes(b"%PDF")
    problems = frozen_problems(root)
    assert any("synthetic/stray.txt" in p and "not in the manifest" in p for p in problems)
    assert any("public/stray.pdf" in p and "not in the manifest" in p for p in problems)


def test_a_manifest_entry_with_an_unsupported_extension_is_named(root):
    (root / "synthetic" / "notes.rtf").write_text("x")
    import hashlib

    digest = hashlib.sha256(b"x").hexdigest()

    def change(m: dict[str, Any]) -> None:
        m["files"].append({**m["files"][0], "path": "synthetic/notes.rtf", "sha256": digest})

    rewrite_manifest(root, change)
    assert any("synthetic/notes.rtf" in p and "unsupported" in p for p in frozen_problems(root))


def test_a_file_count_mismatch_between_manifest_and_disk_is_named(root):
    def change(m: dict[str, Any]) -> None:
        m["files"] = [f for f in m["files"] if f["path"] != "v1/cooperative_bylaws.txt"]

    rewrite_manifest(root, change)
    problems = frozen_problems(root)
    assert any("v1/cooperative_bylaws.txt" in p and "not in the manifest" in p for p in problems)


def test_a_manifest_checksum_edit_without_a_new_version_is_named(root):
    def change(m: dict[str, Any]) -> None:
        m["files"][0]["sha256"] = "0" * 64

    rewrite_manifest(root, change)
    problems = frozen_problems(root)
    assert any("SHA-256" in p for p in problems)
    assert any("corpus_version" in p for p in problems)


def test_a_changed_public_manifest_is_named(root):
    path = root / "public_manifest.json"
    path.write_text(path.read_text().replace("NIST", "NIST ", 1))
    assert any("public manifest" in p for p in frozen_problems(root))


def test_incomplete_google_exports_are_named(root):
    (root / "google" / "google_open_day_notice.docx").unlink()
    assert any("google_open_day_notice.docx" in p for p in frozen_problems(root))

    def change(m: dict[str, Any]) -> None:
        m["google_exports"]["status"] = "pending"

    rewrite_manifest(root, change)
    assert any("Google" in p and "pinned" in p for p in frozen_problems(root))


def test_duplicate_file_names_are_named_because_the_index_and_probes_key_on_them(root):
    def change(m: dict[str, Any]) -> None:
        clone = {**next(f for f in m["files"] if f["path"] == "v1/cooperative_bylaws.txt")}
        clone["path"] = "synthetic/cooperative_bylaws.txt"
        m["files"].append(clone)

    shutil.copy(
        root / "v1" / "cooperative_bylaws.txt", root / "synthetic" / "cooperative_bylaws.txt"
    )
    rewrite_manifest(root, change)
    assert any("duplicate file name" in p for p in frozen_problems(root))


def test_the_messy_manifest_must_agree_with_the_frozen_manifest(root):
    path = root / "messy_manifest.json"
    data = json.loads(path.read_text())
    name = sorted(data["files"])[0]
    data["files"][name] = "f" * 64
    path.write_text(json.dumps(data))
    assert any(name in p and "messy_manifest" in p for p in frozen_problems(root))


def test_frozen_corpus_raises_with_every_problem_listed(root):
    (root / "v1" / "cooperative_bylaws.txt").unlink()
    (root / "public" / "nist_sp800_145.pdf").unlink()
    with pytest.raises(FrozenCorpusError) as caught:
        frozen_corpus(root)
    text = str(caught.value)
    assert "cooperative_bylaws.txt" in text and "nist_sp800_145.pdf" in text
    assert len(caught.value.problems) >= 2


def test_a_corrupt_manifest_file_is_reported_not_raised_as_a_json_error(root):
    (root / "v1_manifest.json").write_text("{not json")
    assert any("v1_manifest.json" in p for p in frozen_problems(root))


def test_the_check_reads_the_manifest_not_a_hardcoded_list():
    """The count follows the manifest: the same code on a manifest with one fewer file expects one fewer."""
    assert corpus_v1.MANIFEST == CORPUS_DIR / "v1_manifest.json"
    assert len(frozen_corpus().files) == len(REAL["files"]) + len(public_files())
