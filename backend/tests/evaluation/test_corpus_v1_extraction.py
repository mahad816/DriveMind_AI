"""Extraction smoke test: every corpus file goes through the product's own readers (free).

Corpus validation, not RAG quality: this proves the documents are readable, that the facts and the
embedded instructions survive extraction, and how many chunks each file becomes. It reads nothing from
a model, an embedding service or Google. A reader regression fails here, in a free test, and not in a
paid run.
"""

import json
from collections import Counter

import pytest

from evaluation.rag_eval import corpus_v1 as c
from evaluation.rag_eval import corpus_v1_content as k
from evaluation.rag_eval.corpus import CORPUS_DIR
from evaluation.rag_eval.text import contains

MANIFEST = json.loads((CORPUS_DIR / "v1_manifest.json").read_text())
FILES = MANIFEST["files"]
TEXTS = c.extract_all()


@pytest.mark.parametrize("entry", FILES, ids=lambda e: e["path"])
def test_a_file_extracts_with_its_canaries_digest_and_chunk_count(entry):
    text = TEXTS[entry["path"]]
    assert text.strip(), "the product's reader returned no text"
    assert len(entry["canaries"]) >= 3
    for canary in entry["canaries"]:
        assert contains(text, canary), f"canary {canary!r} lost by the reader"
    assert c.text_digest(text) == entry["text_sha256"], (
        "reader output changed; review, then --write"
    )
    assert c.chunk_count(text) == entry["chunks"]


@pytest.mark.parametrize("path", sorted(k.INJECTIONS))
def test_an_embedded_instruction_reaches_the_extracted_text_verbatim(path):
    _, instruction = k.INJECTIONS[path]
    assert " ".join(instruction.split()) in " ".join(TEXTS[path].split())


def test_the_six_long_documents_each_make_at_least_four_chunks():
    long = [f for f in FILES if "long" in f["tags"]]
    counts = {f["path"]: c.chunk_count(TEXTS[f["path"]]) for f in long}
    assert len(long) == 6, counts
    assert all(n >= 4 for n in counts.values()), counts


def test_the_chunk_count_table_by_format():
    per_format: Counter[str] = Counter()
    for f in FILES:
        if f["group"] == "v1":
            per_format[f["kind"]] += 1
    assert per_format == {"docx": 3, "xlsx": 3, "pptx": 3, "pdf": 3, "md": 3, "csv": 3, "txt": 1}


# ---- the reader defects the ticket names: a table row lost, a sheet skipped, notes ignored ---------------------


def test_no_table_row_is_lost_by_any_reader():
    tables = {
        "v1/driver_handbook.docx": [k.HANDBOOK_ALLOCATION],
        "v1/customs_and_border_guide.docx": [k.COMMODITIES],
        "v1/depot_safety_procedures.docx": [k.SAFETY_CONTACTS],
        "v1/marrowdale_annual_report_2025.pdf": [k.REPORT_FINANCIALS, k.REPORT_QUARTERS],
        "v1/quarterly_ops_review.pptx": [next(s.table for s in k.OPS_SLIDES if s.table)],
        "v1/network_expansion_plan.pptx": [next(s.table for s in k.EXPANSION_SLIDES if s.table)],
    }
    lost = []
    for path, found in tables.items():
        for table in found:
            lost += [
                (path, row) for row in table.rows if not all(cell in TEXTS[path] for cell in row)
            ]
    for depot_rows in k._ZONE_ROWS.values():
        lost += [
            ("cold chain", r)
            for r in depot_rows
            if not all(cell in TEXTS["v1/cold_chain_operations_manual.pdf"] for cell in r)
        ]
    for row in k.INCIDENTS:
        lost += (
            [("incident log", row)]
            if not all(
                cell.replace(",", "") in TEXTS["v1/incident_log_2026.csv"].replace(",", "")
                for cell in row
            )
            else []
        )
    for row in k.CUSTOMERS:
        lost += (
            [("customers", row)]
            if not all(cell in TEXTS["v1/customer_accounts.csv"] for cell in row)
            else []
        )
    assert lost == []


def test_no_sheet_is_skipped_and_every_cached_formula_value_is_shown():
    for path, builder in (
        ("v1/fleet_register.xlsx", k.fleet_sheets),
        ("v1/tariff_2026.xlsx", k.tariff_sheets),
        ("v1/fuel_and_toll_costs_q3.xlsx", k.fuel_sheets),
    ):
        for name, rows in builder():
            assert f"## Sheet: {name}" in TEXTS[path], (path, name)
            assert any(True for _ in rows)
    for route in k.tariff_sheets()[0][1][1:]:
        formula = route[6]
        assert isinstance(formula, k.Formula)
        assert f"{formula.cached:g}" in TEXTS["v1/tariff_2026.xlsx"], route[0]


def test_every_speaker_note_is_read():
    for path, slides in (
        ("v1/depot_induction.pptx", k.INDUCTION_SLIDES),
        ("v1/quarterly_ops_review.pptx", k.OPS_SLIDES),
        ("v1/network_expansion_plan.pptx", k.EXPANSION_SLIDES),
    ):
        for slide in slides:
            if slide.notes:
                assert slide.notes in " ".join(TEXTS[path].split()), (path, slide.title)
            if slide.textbox:
                assert slide.textbox in TEXTS[path], (path, slide.title)


def test_two_column_pdfs_keep_each_column_in_reading_order():
    report = TEXTS["v1/marrowdale_annual_report_2025.pdf"]
    names = [d.name for d in k.DEPOTS]
    start = report.index("Depot reviews")
    positions = [report.index(f"{name} earned", start) for name in names]
    assert positions == sorted(positions)
    news = TEXTS["v1/member_newsletter_autumn_2026.pdf"]
    assert news.index("Open day at Wren Hollow") < news.index("Fuel price update")


def test_the_real_google_exports_keep_their_sheet_values_and_speaker_notes():
    """Regression for the genuine Google files (not the generated stand-ins)."""
    sheet = TEXTS["google/google_open_day_rota.xlsx"]
    assert "| Tamsin Rooke | Tour guide | 10:00 | 320 |" in sheet
    assert "| Odile Wray | Catering | 09:00 | 480 |" in sheet
    slides = TEXTS["google/google_open_day_briefing.pptx"]
    assert "Notes: Count visitors at the gate on arrival and departure." in slides
    assert "## Slide 3: Safety" in slides and "- Visitors gather at assembly point C" in slides
    doc = TEXTS["google/google_open_day_notice.docx"]
    assert "Gates open at 10:00 and the last tour leaves at 15:00." in doc
