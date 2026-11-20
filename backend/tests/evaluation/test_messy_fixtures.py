"""The generated test documents and their question set must be exactly what they claim to be.

These tests do not use the product's readers. They read the files back with the plain libraries and
compare with the content description in ``messy_fixtures``, which is the ground truth for the
questions. Whether the product reads the files well is a separate matter (``tests/known_issues``).
"""

import copy
import io
import time
from collections import Counter

import pytest
from docx import Document
from openpyxl import load_workbook
from pptx import Presentation
from pptx.shapes.autoshape import Shape
from pptx.shapes.graphfrm import GraphicFrame
from pypdf import PdfReader

from evaluation.rag_eval import messy_fixtures as mf
from evaluation.rag_eval.corpus import CORPUS_DIR, messy_files, synthetic_files, verify
from evaluation.rag_eval.dataset import load_cases, load_many, validate

CASES = load_cases("rag_v2_messy_cases.json")
FILES = synthetic_files() + messy_files()
TRUTH = {f.path: mf.truth_text(f.name) for f in messy_files()}


def slide_table(rows: mf.Table_ | None) -> mf.Table_:
    assert rows is not None
    return rows


def number(text: str) -> int:
    return int(text.replace(",", ""))


def case(case_id: str) -> dict:
    return next(c for c in CASES["cases"] if c["id"] == case_id)


def accepted(case_id: str) -> set[str]:
    return {alt.replace(",", "") for group in case(case_id)["must_include"] for alt in group}


# ---- the files themselves ---------------------------------------------------------------------------------


@pytest.mark.parametrize("fixture", mf.FIXTURES, ids=lambda f: f.name)
def test_a_fixture_is_built_identically_every_time(fixture):
    first = fixture.build()
    time.sleep(1.1)  # a library that writes "now" into the file shows up as a different second
    assert fixture.build() == first


def test_committed_files_match_the_manifest():
    verify(messy_files())  # raises if a committed file was edited by hand
    assert {f.name for f in messy_files()} == {f.name for f in mf.FIXTURES}


def test_the_docx_holds_the_described_headings_bullets_and_tables():
    doc = Document(io.BytesIO(mf.build_docx()))
    tables = [[[c.text for c in row.cells] for row in t.rows] for t in doc.tables]
    assert tables == [
        [list(mf.ROLLOUT_PACKAGES.header), *map(list, mf.ROLLOUT_PACKAGES.rows)],
        [list(mf.ROLLOUT_OWNERS.header), *map(list, mf.ROLLOUT_OWNERS.rows)],
    ]
    styles = Counter(p.style.name if p.style else "" for p in doc.paragraphs)
    assert styles["Heading 1"] == 1 and styles["Heading 2"] == 3 and styles["List Bullet"] == 3


def test_the_pptx_holds_titles_a_table_a_text_box_and_speaker_notes():
    prs = Presentation(io.BytesIO(mf.build_pptx()))
    slides = list(prs.slides)
    titles = [s.shapes.title.text if s.shapes.title else "" for s in slides]
    assert titles == [s.title for s in mf.BOARD_SLIDES]
    graphic = next(sh for sh in slides[2].shapes if isinstance(sh, GraphicFrame) and sh.has_table)
    rows = [[c.text for c in row.cells] for row in graphic.table.rows]
    assert rows[1] == list(slide_table(mf.BOARD_SLIDES[2].table).rows[0])
    assert slides[3].notes_slide.notes_text_frame is not None
    assert slides[3].notes_slide.notes_text_frame.text == mf.BOARD_SLIDES[3].notes
    assert not any(s.has_notes_slide for s in slides[:3])
    assert any(
        isinstance(sh, Shape) and sh.text_frame.text == mf.BOARD_SLIDES[3].textbox
        for sh in slides[3].shapes
    )


def test_the_xlsx_has_both_sheets_with_numbers_stored_as_numbers():
    book = load_workbook(io.BytesIO(mf.build_xlsx()))
    assert book.sheetnames == ["Orders", "Targets"]
    first = [c.value for c in next(book["Orders"].iter_rows(min_row=2, max_row=2))]
    assert first == ["SO-101", "Clinica Sao Bento", "Portugal", 4500, "Delivered"]
    assert book["Targets"]["B3"].value == 45000


def test_the_invoice_pdf_has_two_pages_with_header_and_footer_on_each():
    reader = PdfReader(io.BytesIO(mf.build_invoice_pdf()))
    texts = [page.extract_text() for page in reader.pages]
    assert len(texts) == 2
    assert all(mf.INVOICE_HEADER in t for t in texts)
    assert "Page 1 of 2" in texts[0] and "Page 2 of 2" in texts[1]
    assert "Total due" in texts[0] and "within 30 days" in texts[1]


def test_the_report_pdf_has_six_pages_each_with_the_running_header_and_a_page_number():
    reader = PdfReader(io.BytesIO(mf.build_report_pdf()))
    texts = [page.extract_text() for page in reader.pages]
    assert len(texts) == 6
    for number_, text in enumerate(texts, start=1):
        lines = text.splitlines()
        assert lines[0] == mf.REPORT_HEADER and str(number_) in lines
    assert "1,840,000" in texts[1] and "Spain" in texts[2]


def test_the_two_column_page_reads_left_column_before_right_column():
    page = PdfReader(io.BytesIO(mf.build_report_pdf())).pages[3].extract_text()
    assert page.index("91 percent") < page.index("6 planned maintenance")


# ---- the question set --------------------------------------------------------------------------------------


def test_every_case_is_grounded_in_the_ground_truth():
    assert validate(CASES, FILES, texts=TRUTH) == []


def test_the_validator_catches_a_wrong_anchor_and_a_wrong_expected_answer():
    broken = copy.deepcopy(CASES)
    broken["cases"] = [c for c in broken["cases"] if c["id"] in {"dx01", "xl01"}]
    broken["cases"][0]["evidence_anchors"][0]["quote"] = "Regional | 5 | 4,600 | 4"
    broken["cases"][1]["must_include"] = [["lost in transit"]]
    problems = validate(broken, FILES, texts=TRUTH)
    assert any("dx01" in p and "evidence quote" in p for p in problems)
    assert any("xl01" in p and "must_include" in p for p in problems)


def test_ids_are_unique_across_every_dataset_and_both_splits_exist():
    merged = load_many(["rag_v2_cases.json", "rag_v2_trap_cases.json", "rag_v2_messy_cases.json"])
    assert not any("duplicate id" in p for p in validate(merged, FILES, texts=TRUTH))
    splits = Counter(c["split"] for c in CASES["cases"])
    assert splits["dev"] >= 20 and splits["test"] >= 15


def test_every_fixture_has_enough_questions_and_the_files_it_needs_cover_each_kind():
    per_file = Counter(path for c in CASES["cases"] for path in c["expected_files"])
    assert all(per_file[f"messy/{f.name}"] >= 4 for f in mf.FIXTURES)
    categories = {c["category"] for c in CASES["cases"]}
    assert {
        "table_lookup",
        "table_calc",
        "slide_notes",
        "second_sheet",
        "ruled_table",
        "borderless_table",
        "two_columns",
        "page_two",
        "messy_not_found",
    } <= categories


def test_not_found_cases_ask_about_things_that_really_are_missing():
    missing = [c for c in CASES["cases"] if c["expected_behavior"] == "not_found"]
    assert len(missing) == 5
    for c in missing:
        assert not c["expected_files"] and c["reference_answer"] and c["must_not_include"]
    # the thing asked for appears nowhere in any fixture, so refusing is the only correct answer
    everything = " ".join(TRUTH.values()).lower()
    for word in ("enterprise", "discount", "france", "net profit", "q3 revenue"):
        assert word not in everything


# ---- computed answers are re-derived from the content description, not trusted -----------------------------


def test_dx04_adds_the_pilot_and_regional_setup_fees():
    fees = {row[0]: number(row[2]) for row in mf.ROLLOUT_PACKAGES.rows}
    assert str(fees["Pilot"] + fees["Regional"]) in accepted("dx04")


def test_px08_adds_the_three_regional_pipelines():
    total = sum(number(row[2]) for row in slide_table(mf.BOARD_SLIDES[2].table).rows)
    assert str(total) in accepted("px08")
    clinics = sum(number(row[1]) for row in slide_table(mf.BOARD_SLIDES[2].table).rows)
    assert str(clinics) in accepted("px03")  # the slide table and the highlights bullet agree


def test_xl04_sums_only_the_delivered_orders():
    delivered = sum(number(row[3]) for row in mf.ORDERS.rows if row[4] == "Delivered")
    assert str(delivered) in accepted("xl04")
    anchors = {a["quote"] for a in case("xl04")["evidence_anchors"]}
    assert len(anchors) == sum(row[4] == "Delivered" for row in mf.ORDERS.rows)


def test_vr03_subtracts_operating_costs_from_revenue_and_the_clinic_totals_add_up():
    revenue, costs = (number(row[2]) for row in mf.FINANCIALS.rows[:2])
    assert str(revenue - costs) in accepted("vr03")
    by_country = mf.CLINICS_BY_COUNTRY.rows
    assert sum(number(r[1]) for r in by_country) == number(mf.FINANCIALS.rows[2][1])
    assert sum(number(r[2]) for r in by_country) == number(mf.FINANCIALS.rows[2][2])


def test_vr07_is_the_difference_between_the_two_portugal_years():
    portugal = next(r for r in mf.CLINICS_BY_COUNTRY.rows if r[0] == "Portugal")
    assert str(number(portugal[2]) - number(portugal[1])) in accepted("vr07")


def test_the_invoice_totals_are_arithmetically_consistent():
    items = sum(
        number(r[3].split(".")[0]) * 100 + number(r[3].split(".")[1]) for r in mf.INVOICE_ITEMS.rows
    )
    subtotal, vat, total = (
        int(r[1].replace(",", "").replace(".", "")) for r in mf.INVOICE_TOTALS.rows
    )
    assert items == subtotal
    assert vat == round(subtotal * 0.23)
    assert total == subtotal + vat
    for r in mf.INVOICE_ITEMS.rows:  # each line: quantity x unit price = amount
        assert int(r[1]) * float(r[2].replace(",", "")) == float(r[3].replace(",", ""))


def test_the_stale_versus_current_trap_really_conflicts_with_the_older_file():
    team = (CORPUS_DIR / "synthetic" / "team_directory.txt").read_text()
    assert "Total: 12 employees" in team
    assert "11 employees" in TRUTH["messy/annual_report_2025.pdf"]
