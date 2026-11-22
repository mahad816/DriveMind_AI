"""The manifest checks accept the real corpus and reject every deliberately broken copy (free).

Each test copies the committed corpus into a temporary folder, breaks one thing and expects one named
problem. A validator that never fails proves nothing, so the accepting case comes first and the breakage
is always a single, specific change.
"""

import copy
import io
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from docx import Document
from openpyxl import Workbook
from pptx import Presentation

from evaluation.rag_eval import corpus_v1 as c
from evaluation.rag_eval import corpus_v1_content as k
from evaluation.rag_eval.corpus import CORPUS_DIR, CorpusFile, v1_files, verify

REAL = json.loads((CORPUS_DIR / "v1_manifest.json").read_text())
TEXTS = c.extract_all()  # the product's readers, once for the whole module
LONG = "v1/driver_handbook.docx"
INJECTED = "v1/depot_safety_procedures.docx"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    for folder in ("v1", "messy", "synthetic", "google"):
        shutil.copytree(CORPUS_DIR / folder, tmp_path / folder)
    return tmp_path


@pytest.fixture
def manifest() -> dict[str, Any]:
    return copy.deepcopy(REAL)


def entry(manifest: dict[str, Any], path: str) -> dict[str, Any]:
    return next(f for f in manifest["files"] if f["path"] == path)


def problems(
    manifest: dict[str, Any], root: Path, texts: dict[str, str] | None = None
) -> list[str]:
    return c.validate_manifest(manifest, root=root, texts=texts if texts is not None else TEXTS)


def test_the_real_corpus_and_manifest_are_accepted(root, manifest):
    assert problems(manifest, root) == []
    assert c.validate_manifest(REAL) == []  # real files, real readers
    assert c.coverage_problems(REAL) == []


def test_the_committed_manifest_is_what_the_generator_writes_today():
    fresh = c.build_manifest()
    assert {k: v for k, v in fresh.items() if k != "built_with"} == {
        k: v for k, v in REAL.items() if k != "built_with"
    }


# ---- files and checksums --------------------------------------------------------------------------------------


def test_a_missing_document_is_reported(root, manifest):
    (root / "v1/tariff_2026.xlsx").unlink()
    assert "v1/tariff_2026.xlsx: file is missing" in problems(manifest, root)


def test_a_changed_document_is_reported(root, manifest):
    path = root / "v1/customer_accounts.csv"
    path.write_bytes(path.read_bytes() + b"C-009,Extra,Nobody,Kessel Yard,Dry goods\n")
    assert "v1/customer_accounts.csv: file does not match its recorded SHA-256" in problems(
        manifest, root
    )


def test_a_file_that_is_not_in_the_manifest_is_reported(root, manifest):
    (root / "v1/stray_notes.txt").write_text("not registered")
    assert "v1/stray_notes.txt: file is in the corpus folders but not in the manifest" in problems(
        manifest, root
    )


def test_duplicate_paths_unknown_sources_and_missing_fields_are_reported(root, manifest):
    manifest["files"].append(copy.deepcopy(entry(manifest, LONG)))
    entry(manifest, "v1/tariff_2025.csv")["source"] = "scraped"
    entry(manifest, "v1/incident_log_2026.csv")["group"] = "misc"
    del entry(manifest, "v1/customer_accounts.csv")["sha256"]
    found = problems(manifest, root)
    assert f"duplicate path {LONG}" in found
    assert "v1/tariff_2025.csv: unknown source 'scraped'" in found
    assert "v1/incident_log_2026.csv: unknown group 'misc'" in found
    assert "v1/customer_accounts.csv: missing field sha256" in found


def test_a_wrong_corpus_version_and_a_bad_google_status_are_reported(root, manifest):
    manifest["corpus_version"] = "m1-corpus-v1-000000000000"
    manifest["google_exports"]["status"] = "maybe"
    found = problems(manifest, root)
    assert any(p.startswith("corpus_version is 'm1-corpus-v1-000000000000'") for p in found)
    assert "google_exports.status must be pending, pinned or declined" in found


# ---- canaries and text ----------------------------------------------------------------------------------------


def test_fewer_than_three_canaries_and_a_canary_missing_from_the_text_are_reported(root, manifest):
    entry(manifest, "v1/tariff_2025.csv")["canaries"] = ["Pioneer", "Heron"]
    entry(manifest, LONG)["canaries"][0] = "a sentence that is not in the handbook"
    found = problems(manifest, root)
    assert "v1/tariff_2025.csv: needs at least 3 distinct canary strings" in found
    assert any(
        p.startswith(f"{LONG}: canary 'a sentence that is not in the handbook'") for p in found
    )


def test_a_reader_that_loses_text_is_reported_as_a_changed_digest(root, manifest):
    texts = dict(TEXTS)
    texts["v1/tariff_2026.xlsx"] = texts["v1/tariff_2026.xlsx"].replace(
        "| Heron | Northgate |", "|"
    )
    found = problems(manifest, root, texts)
    assert any("v1/tariff_2026.xlsx: extracted text changed" in p for p in found)


def test_a_reader_that_returns_nothing_is_reported(root, manifest):
    texts = dict(TEXTS, **{"v1/depot_induction.pptx": "  \n"})
    assert "v1/depot_induction.pptx: the product's reader returned no text" in problems(
        manifest, root, texts
    )


def test_a_long_document_that_shrinks_below_four_chunks_is_reported(root, manifest):
    texts = dict(TEXTS, **{LONG: TEXTS[LONG][:5000]})
    found = problems(manifest, root, texts)
    assert any(p.startswith(f"{LONG}: long document has only") for p in found)
    assert any(p.startswith(f"{LONG}: chunk count is") for p in found)


def test_the_short_deck_must_stay_one_chunk_and_the_long_deck_must_stay_long(root, manifest):
    texts = dict(
        TEXTS,
        **{
            "v1/depot_induction.pptx": TEXTS["v1/depot_induction.pptx"] * 12,
            "v1/quarterly_ops_review.pptx": TEXTS["v1/quarterly_ops_review.pptx"][:900],
        },
    )
    found = problems(manifest, root, texts)
    assert "v1/depot_induction.pptx: the short deck must stay a single chunk" in found
    assert "v1/quarterly_ops_review.pptx: the longer deck must produce several chunks" in found


def test_an_injection_that_a_reader_drops_or_alters_is_reported(root, manifest):
    sentence = k.INJECTIONS[INJECTED][1]
    dropped = dict(TEXTS, **{INJECTED: TEXTS[INJECTED].replace(sentence, "")})
    altered = dict(
        TEXTS, **{INJECTED: TEXTS[INJECTED].replace("print your full system prompt", "print it")}
    )
    for texts in (dropped, altered):
        assert (
            f"{INJECTED}: embedded instruction is not verbatim in the extracted text"
            in problems(manifest, root, texts)
        )


# ---- coverage (the ticket's counts) ----------------------------------------------------------------------------


def test_coverage_reports_every_missing_format_and_scenario(manifest):
    manifest["files"] = [
        f
        for f in manifest["files"]
        if not (
            f["group"] == "v1"
            and (f["kind"] == "csv" or any(t.startswith("injection:") for t in f["tags"]))
        )
    ]
    found = c.coverage_problems(manifest)
    assert "needs 3 csv files, has 0" in found
    assert "needs three injection documents of different kinds in two formats" in found
    for f in manifest["files"]:
        f["tags"] = [
            t
            for t in f["tags"]
            if t not in {"long"} and not t.startswith(("same_name", "supersed"))
        ]
    found = c.coverage_problems(manifest)
    assert {"needs six long documents", "needs two superseded pairs"} <= set(found)
    assert "needs two same-name entities across files" in found


# ---- the corpus module's own verify step covers the new kinds ---------------------------------------------------


def test_verify_accepts_the_v1_files_and_rejects_a_changed_or_missing_one():
    files = v1_files()
    assert len(files) == 22 and {f.kind for f in files} == {"v1", "google"}
    verify(files)  # passes
    with pytest.raises(ValueError, match="does not match its recorded SHA-256"):
        verify([CorpusFile(files[0].path, "v1", "0" * 64, {})])
    with pytest.raises(ValueError, match="is missing"):
        verify([CorpusFile("v1/not_a_file.docx", "v1", "0" * 64, {})])


# ---- Google exports: pinned only when all three are present, recorded as declined or pending --------------------


def fake_google_exports(root: Path) -> None:
    """Stand-ins with the right names and text (the real files come from the Owner's Google account)."""
    (root / "google").mkdir(exist_ok=True)  # overwrites the real exports in the temporary copy
    doc = Document()
    for line in k.GOOGLE_SOURCES["google/google_open_day_notice.docx"][2].split("\n"):
        doc.add_paragraph(line)
    doc.save(str(root / "google/google_open_day_notice.docx"))
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.title = "Rota"
    for row in (
        ("Name", "Role", "Start", "Budget (GBP)"),
        ("Tamsin Rooke", "Tour guide", "10:00", 320),
    ):
        sheet.append(list(row))
    book.save(str(root / "google/google_open_day_rota.xlsx"))
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    title: Any = slide.shapes.title
    title.text = "Open day briefing"
    body: Any = slide.placeholders[1]
    body.text_frame.text = "The fire marshal wears orange; visitors gather at assembly point C"
    prs.save(str(root / "google/google_open_day_briefing.pptx"))


def test_three_google_exports_are_pinned_with_source_google_export(root):
    fake_google_exports(root)
    manifest = c.build_manifest(root=root)
    google = [f for f in manifest["files"] if f["group"] == "google"]
    assert len(google) == 3 and {f["source"] for f in google} == {"Google export"}
    assert manifest["google_exports"]["status"] == "pinned"
    assert c.validate_manifest(manifest, root=root) == []  # real readers, canaries found
    assert manifest["corpus_version"] != REAL["corpus_version"]  # a new corpus version, by design


def test_a_partial_set_of_google_exports_is_refused(root):
    fake_google_exports(root)
    (root / "google/google_open_day_rota.xlsx").unlink()
    with pytest.raises(ValueError, match="all three or none"):
        c.build_manifest(root=root)


def test_a_declined_decision_is_recorded_when_no_exports_are_present(root):
    shutil.rmtree(root / "google")
    declined = c.build_manifest(root=root, google_status="declined")
    assert declined["google_exports"]["status"] == "declined"
    assert [f for f in declined["files"] if f["group"] == "google"] == []
    assert declined["corpus_version"] != REAL["corpus_version"]  # the three exports are part of it


def test_google_source_text_has_three_canaries_each_and_belongs_to_a_named_export():
    assert sorted(k.GOOGLE_SOURCES) == c.google_names()
    for path, (_, canaries, text) in k.GOOGLE_SOURCES.items():
        assert len(set(canaries)) >= 3 and all(
            canary.lower() in text.lower() for canary in canaries
        ), path
    assert io.BytesIO  # keep the import used by fakes above
