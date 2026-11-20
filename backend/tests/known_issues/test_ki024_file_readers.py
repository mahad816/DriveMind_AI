"""KI-024 (fixed in A2 to A5): what the file readers must produce for the generated fixtures.

The expected texts are written as "light Markdown" (``evaluation/rag_eval/messy_fixtures.py`` holds the
content): headings as ``#``, tables as ``| a | b |`` rows with a header row, bullets as ``- ``, slides as
``## Slide N: title`` with a ``Notes:`` line, sheets as ``## Sheet: name``, PDF pages separated by a
form-feed line. All of them pass now and stay as regression tests, together with the guards at the end
that check older behaviour (two-column order, borderless table values, body text) did not break.
"""

import re

import pytest

from app.ingestion.extractors.bootstrap import register_builtin_extractors
from app.ingestion.extractors.registry import get_extractor
from app.ingestion.extractors.base import UnsupportedMimeTypeError
from evaluation.rag_eval import messy_fixtures as mf
from evaluation.rag_eval.corpus import MIME


_SEPARATOR = re.compile(r"^:?-{3,}:?$")


def read(name: str) -> str:
    """Text the product's own reader returns for a fixture; a missing reader is an assertion."""
    register_builtin_extractors()
    path = mf.MESSY_DIR / name
    mime = MIME[path.suffix]
    try:
        extractor = get_extractor(mime)
    except UnsupportedMimeTypeError as exc:
        raise AssertionError(f"no reader registered for {mime}") from exc
    return extractor.extract(path.read_bytes(), mime_type=mime, filename=name).text


def markdown_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def markdown_rows(text: str) -> list[list[str]]:
    """Cells of every ``| a | b |`` line, separator rows (``| --- | --- |``) left out."""
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("|") and line.endswith("|") and len(line) > 1:
            cells = markdown_cells(line)
            if not all(_SEPARATOR.match(cell) for cell in cells):
                rows.append(cells)
    return rows


def plain(cell: str) -> str:
    return cell.replace(",", "").strip()


def assert_table(text: str, table: mf.Table_) -> None:
    """The header and every row of ``table`` appear as Markdown rows, and the header comes first."""
    rows = [[plain(c) for c in row] for row in markdown_rows(text)]
    expected = [[plain(c) for c in row] for row in (table.header, *table.rows)]
    for row in expected:
        assert row in rows, f"table row missing or split: {row}"
    positions = [rows.index(row) for row in expected]
    assert positions == sorted(positions), "table rows are out of order"
    lines = [line.strip() for line in text.splitlines()]
    header_at = next(
        i
        for i, line in enumerate(lines)
        if line.startswith("|") and [plain(c) for c in markdown_cells(line)] == expected[0]
    )
    separator = markdown_cells(lines[header_at + 1]) if header_at + 1 < len(lines) else []
    assert separator and all(_SEPARATOR.match(cell) for cell in separator), (
        "the header row must be followed by a separator row such as | --- | --- |"
    )


def position(text: str, needle: str) -> int:
    index = text.find(needle)
    assert index != -1, f"missing from the text: {needle!r}"
    return index


# ---- DOCX (fixed in A2, kept as regression tests) -------------------------------------------------------------------------------------------------


def test_docx_tables_are_read_as_markdown_tables():
    text = read("customer_rollout_plan.docx")
    assert_table(text, mf.ROLLOUT_PACKAGES)
    assert_table(text, mf.ROLLOUT_OWNERS)


def test_docx_headings_and_bullets_keep_their_markers():
    lines = read("customer_rollout_plan.docx").splitlines()
    assert "# Customer rollout packages" in lines
    assert {"## Packages", "## Training", "## Responsibilities"} <= set(lines)
    assert "- Each training session lasts 90 minutes." in lines
    assert "- Sessions are held on Wednesdays." in lines


def test_docx_paragraph_after_a_table_keeps_its_place():
    text = read("customer_rollout_plan.docx")
    after_table = position(text, "Setup fees are invoiced once, at contract signature.")
    # the paragraph follows the LAST row of the packages table and comes before the next heading
    assert position(text, "| Network |") < after_table < position(text, "## Training")


# ---- PPTX (fixed in A3, kept as regression tests) -------------------------------------------------------------------------------------------------


def test_pptx_slides_are_sections_with_titles_bullets_and_a_table():
    text = read("board_update_q3.pptx")
    lines = text.splitlines()
    for number, slide in enumerate(mf.BOARD_SLIDES, start=1):
        assert f"## Slide {number}: {slide.title}" in lines
    assert "- Signed 6 new clinics in Q3" in lines
    pipeline = mf.BOARD_SLIDES[2].table
    assert pipeline is not None
    assert_table(text, pipeline)


def test_pptx_speaker_notes_and_free_text_boxes_are_included():
    text = read("board_update_q3.pptx")
    notes = next((line for line in text.splitlines() if line.startswith("Notes:")), "")
    assert "55,000 USD" in notes and "14 October 2026" in notes
    assert "Next board review: January 2027" in text
    # notes belong to the slide they were written on (the fourth)
    assert position(text, "## Slide 4:") < position(text, "55,000 USD")


# ---- XLSX (A5) -------------------------------------------------------------------------------------------------


def test_xlsx_every_sheet_is_a_titled_table():
    text = read("sales_2026.xlsx")
    lines = text.splitlines()
    assert "## Sheet: Orders" in lines and "## Sheet: Targets" in lines
    assert_table(text, mf.ORDERS)
    assert_table(text, mf.TARGETS)
    assert (
        position(text, "## Sheet: Orders")
        < position(text, "SO-101")
        < position(text, "## Sheet: Targets")
    )


# ---- PDF (A4) --------------------------------------------------------------------------------------------------


def test_pdf_ruled_tables_become_markdown_tables():
    invoice = read("invoice_0457.pdf")
    assert_table(invoice, mf.INVOICE_ITEMS)
    assert_table(invoice, mf.INVOICE_TOTALS)
    assert_table(read("annual_report_2025.pdf"), mf.CLINICS_BY_COUNTRY)


def test_pdf_running_header_is_not_repeated_on_every_page():
    text = read("annual_report_2025.pdf")
    assert text.count(mf.REPORT_HEADER) <= 1, "the running header is in every chunk's text"


def test_pdf_page_numbers_are_not_part_of_the_text():
    """Single-digit values (clinic counts, ...) live inside table rows, so a bare digit line is a page number."""
    bare = [
        line
        for line in read("annual_report_2025.pdf").splitlines()
        if re.fullmatch(r"\s*\d\s*", line)
    ]
    assert bare == []
    assert not re.search(r"^Page \d+ of \d+$", read("invoice_0457.pdf"), re.MULTILINE)


# ---- guards: these pass today and must keep passing -------------------------------------------------------------


def test_guard_pdf_two_column_page_still_reads_left_column_before_right_column():
    text = read("annual_report_2025.pdf")
    assert position(text, "91 percent") < position(text, "6 planned maintenance")


def test_guard_pdf_borderless_table_values_and_their_labels_are_still_in_the_text():
    text = read("annual_report_2025.pdf")
    for label, *values in mf.FINANCIALS.rows:
        assert label in text
        assert all(value in text for value in values)
    assert "All amounts are in US dollars" in text


def test_guard_pdf_body_text_on_every_page_survives_header_and_page_number_cleaning():
    invoice, report = read("invoice_0457.pdf"), read("annual_report_2025.pdf")
    assert "Payment is due within 30 days of the issue date." in invoice
    assert "Billed to: Clinica Sao Bento" in invoice
    assert "This report covers the period 1 January to 31 December 2025." in report
    assert "11 employees and 61 clinics" in report.replace("\n", " ")


def test_guard_docx_paragraph_text_is_still_read():
    text = read("customer_rollout_plan.docx")
    assert "Customer rollout packages" in text
    assert "Each training session lasts 90 minutes." in text


@pytest.mark.parametrize(
    "mime",
    ["text/plain", "application/pdf", MIME[".docx"]],
)
def test_guard_existing_formats_keep_their_readers(mime):
    register_builtin_extractors()
    assert get_extractor(mime) is not None
