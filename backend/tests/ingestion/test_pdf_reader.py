"""PDF reader on real PDF bytes: page separators, header/footer removal and ruled tables.

PDFs are drawn with ReportLab (a dev dependency). Every test that checks text compares the whole
expected string, so a reader that merely "contains" the right words cannot pass while mangling order.
"""

from __future__ import annotations

from collections.abc import Callable
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

from app.ingestion.extractors import pdf as pdf_module
from app.ingestion.extractors.pdf import PAGE_SEPARATOR, extract_pdf_text
from app.ingestion.extractors.pdf_tables import PageTable

_, HEIGHT = A4

PageDrawer = Callable[[Canvas, int], None]


def make_pdf(pages: int, draw: PageDrawer) -> bytes:
    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=A4, invariant=1)
    for number in range(1, pages + 1):
        draw(canvas, number)
        canvas.showPage()
    canvas.save()
    return buffer.getvalue()


def read(data: bytes) -> str:
    return extract_pdf_text(data)[0]


def line(canvas: Canvas, y: float, text: str, x: float = 72) -> None:
    canvas.setFont("Helvetica", 11)
    canvas.drawString(x, y, text)


def ruled_table(canvas: Canvas, top: float, rows: list[list[str]], *, left: float = 72) -> None:
    widths, height = [150, 90, 90], 22
    columns = len(rows[0])
    xs = [left]
    for width in widths[:columns]:
        xs.append(xs[-1] + width)
    for r in range(len(rows) + 1):
        canvas.line(left, top - r * height, xs[-1], top - r * height)
    for x in xs:
        canvas.line(x, top, x, top - len(rows) * height)
    canvas.setFont("Helvetica", 11)
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            canvas.drawString(xs[c] + 6, top - (r + 1) * height + 7, cell)


def report_page(canvas: Canvas, number: int) -> None:
    line(canvas, HEIGHT - 30, "ACME ANNUAL REPORT 2025", x=72)
    line(canvas, 30, f"Page {number} of 6", x=260)
    line(canvas, 600, f"Findings of chapter {number}.")


# ---- page separators ---------------------------------------------------------------------------------------


def test_pages_are_separated_by_a_form_feed_line_and_empty_pages_still_count():
    def draw(canvas: Canvas, number: int) -> None:
        if number != 2:
            line(canvas, 600, f"text of page {number}")

    text = read(make_pdf(3, draw))
    assert text == "text of page 1\n\n\f\n\f\n\ntext of page 3"
    assert text.count(PAGE_SEPARATOR) == 2


def test_trailing_empty_pages_leave_no_separator_and_all_empty_pages_leave_no_text():
    def draw(canvas: Canvas, number: int) -> None:
        if number == 1:
            line(canvas, 600, "only page with text")

    assert read(make_pdf(3, draw)) == "only page with text"
    assert extract_pdf_text(make_pdf(2, lambda c, n: None)) == ("", 2)


def test_leading_empty_pages_keep_their_separators_so_page_numbers_stay_right():
    def draw(canvas: Canvas, number: int) -> None:
        if number == 3:
            line(canvas, 600, "third page")

    assert read(make_pdf(3, draw)) == "\f\n\f\n\nthird page"


@patch("app.ingestion.extractors.pdf.PdfReader")
def test_a_form_feed_inside_page_text_is_not_mistaken_for_a_page_break(reader_cls: MagicMock):
    page = MagicMock()
    page.extract_text.return_value = "before\x0cafter"
    reader_cls.return_value = MagicMock(is_encrypted=False, pages=[page])
    assert extract_pdf_text(b"%PDF-1.4 fake")[0] == "before after"


# ---- headers, footers, page numbers -----------------------------------------------------------------------


def test_running_header_and_page_numbers_are_removed_but_the_first_header_stays():
    text = read(make_pdf(6, report_page))
    assert text.count("ACME ANNUAL REPORT 2025") == 1
    assert text.startswith("ACME ANNUAL REPORT 2025\nFindings of chapter 1.")
    assert "Page " not in text
    pages = text.split(f"\n\n{PAGE_SEPARATOR}\n\n")
    assert pages[1:] == [f"Findings of chapter {n}." for n in range(2, 7)]


def test_body_text_survives_when_it_repeats_the_header_words():
    def draw(canvas: Canvas, number: int) -> None:
        report_page(canvas, number)
        if number == 4:
            line(canvas, 560, "ACME ANNUAL REPORT 2025")  # same words, but in the body

    pages = read(make_pdf(6, draw)).split(f"\n\n{PAGE_SEPARATOR}\n\n")
    assert pages[3] == "Findings of chapter 4.\nACME ANNUAL REPORT 2025"


def test_a_short_document_keeps_its_repeated_header_but_loses_its_page_numbers():
    def draw(canvas: Canvas, number: int) -> None:
        line(canvas, HEIGHT - 30, "Invoice INV-1")
        line(canvas, 30, f"Page {number} of 2", x=260)
        line(canvas, 600, f"body {number}")

    pages = read(make_pdf(2, draw)).split(f"\n\n{PAGE_SEPARATOR}\n\n")
    assert pages == ["Invoice INV-1\nbody 1", "Invoice INV-1\nbody 2"]


def test_a_digit_in_the_body_is_not_a_page_number():
    def draw(canvas: Canvas, number: int) -> None:
        line(canvas, 600, "Clinics")
        line(canvas, 580, "4")

    assert read(make_pdf(1, draw)) == "Clinics\n4"


# ---- ruled tables ------------------------------------------------------------------------------------------


def test_a_ruled_table_becomes_a_markdown_table_in_the_place_of_its_cell_text():
    def draw(canvas: Canvas, number: int) -> None:
        line(canvas, 760, "Prices are in euros.")
        ruled_table(
            canvas, 720, [["Plan", "Seats", "Price"], ["Basic", "5", "40"], ["Team", "20", "120"]]
        )
        line(canvas, 600, "Taxes are extra.")

    assert read(make_pdf(1, draw)) == (
        "Prices are in euros.\n\n"
        "| Plan | Seats | Price |\n| --- | --- | --- |\n| Basic | 5 | 40 |\n| Team | 20 | 120 |\n\n"
        "Taxes are extra."
    )


def test_two_tables_on_one_page_each_get_their_own_markdown():
    def draw(canvas: Canvas, number: int) -> None:
        ruled_table(canvas, 760, [["A", "B"], ["1", "2"]])
        line(canvas, 690, "between")
        ruled_table(canvas, 650, [["C", "D"], ["3", "4"]])

    assert read(make_pdf(1, draw)) == (
        "| A | B |\n| --- | --- |\n| 1 | 2 |\n\nbetween\n\n| C | D |\n| --- | --- |\n| 3 | 4 |"
    )


def test_a_table_on_a_later_page_is_placed_on_that_page():
    def draw(canvas: Canvas, number: int) -> None:
        line(canvas, 760, f"page {number}")
        if number == 2:
            ruled_table(canvas, 720, [["K", "V"], ["x", "9"]])

    pages = read(make_pdf(2, draw)).split(f"\n\n{PAGE_SEPARATOR}\n\n")
    assert pages == ["page 1", "page 2\n\n| K | V |\n| --- | --- |\n| x | 9 |"]


def test_columns_without_ruling_lines_stay_flowing_text():
    def draw(canvas: Canvas, number: int) -> None:
        for i, (a, b, c) in enumerate([("Plan", "Seats", "Price"), ("Basic", "5", "40")]):
            for x, value in ((72, a), (230, b), (330, c)):
                line(canvas, 700 - i * 20, value, x=x)

    text = read(make_pdf(1, draw))
    assert "|" not in text
    assert all(word in text for word in ("Plan", "Seats", "Price", "Basic", "5", "40"))


def test_a_single_box_with_a_sentence_is_not_turned_into_a_table():
    def draw(canvas: Canvas, number: int) -> None:
        canvas.rect(72, 600, 400, 40)
        line(canvas, 615, "Note: keep this box as it is.", x=80)

    text = read(make_pdf(1, draw))
    assert text == "Note: keep this box as it is."


def one_table_page(canvas: Canvas, number: int) -> None:
    line(canvas, 760, "Intro text.")
    ruled_table(canvas, 720, [["Plan", "Price"], ["Basic", "40"]])


def test_a_table_is_not_used_when_its_text_differs_from_the_text_it_would_replace():
    """If pdfplumber's cells disagree with the page text, nothing may be dropped or invented."""
    wrong = PageTable(
        left=60,
        bottom=600,
        right=500,
        top=730,
        cells=("Totally", "different"),
        markdown="| X | Y |",
    )
    with patch.object(pdf_module, "find_page_tables", return_value=[wrong]):
        text = read(make_pdf(1, one_table_page))
    assert "| X | Y |" not in text
    assert "Basic" in text and "40" in text and "Intro text." in text


def test_a_table_whose_box_holds_extra_text_is_not_used():
    """A box that also covers a paragraph must not swallow it: that text would be lost."""
    wrong = PageTable(
        left=60,
        bottom=600,
        right=500,
        top=770,
        cells=("Plan", "Price", "Basic", "40"),
        markdown="| Plan |",
    )
    with patch.object(pdf_module, "find_page_tables", return_value=[wrong]):
        text = read(make_pdf(1, one_table_page))
    assert "Intro text." in text
    assert "| Plan |" not in text


def test_a_failure_in_table_detection_keeps_the_flowing_text():
    with patch.object(pdf_module, "find_page_tables", side_effect=RuntimeError("boom")):
        text = read(make_pdf(1, one_table_page))
    assert text.splitlines()[0] == "Intro text."
    assert "Basic" in text and "|" not in text


def test_a_failure_to_open_the_pdf_for_tables_keeps_the_flowing_text():
    with patch.object(pdf_module.pdfplumber, "open", side_effect=ValueError("bad")):
        text = read(make_pdf(1, one_table_page))
    assert "Basic" in text and "|" not in text


def test_pages_past_the_table_page_limit_keep_flowing_text(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(pdf_module, "MAX_TABLE_PAGES", 1)

    def draw(canvas: Canvas, number: int) -> None:
        ruled_table(canvas, 720, [["K", "V"], ["x", "9"]])

    pages = read(make_pdf(2, draw)).split(f"\n\n{PAGE_SEPARATOR}\n\n")
    assert pages[0].startswith("| K | V |")
    assert "|" not in pages[1] and "x" in pages[1]
