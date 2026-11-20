"""XLSX reader: exact output for sheets, values, hidden sheets, size limits and damaged files.

Every text check compares the whole expected string. Workbooks are written with openpyxl; the few
tests that need what only Excel writes (a stored formula result, a wrong used range) patch the XML.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date, datetime
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from openpyxl import Workbook

from app.connectors.google_drive.constants import DOCX_MIME, XLSX_MIME
from app.ingestion.extractors import XlsxTextExtractor, get_extractor
from app.ingestion.extractors import xlsx as xlsx_module
from app.ingestion.extractors.base import ExtractionError
from app.ingestion.extractors.tabular import MAX_CELL_CHARS, MAX_COLUMNS, MAX_ROWS_PER_SHEET
from app.ingestion.extractors.xlsx import extract_xlsx_text


def save(workbook: Workbook) -> bytes:
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def book(*sheets: tuple[str, Sequence[Sequence[object]]]) -> Workbook:
    workbook = Workbook()
    workbook.remove(workbook.active)  # type: ignore[arg-type]
    for name, rows in sheets:
        sheet = workbook.create_sheet(name)
        for row in rows:
            sheet.append(row)
    return workbook


def read(workbook: Workbook) -> str:
    return extract_xlsx_text(save(workbook))[0]


def patch_sheet_xml(data: bytes, change) -> bytes:
    """The workbook with ``change`` applied to the XML of its first sheet."""
    out = BytesIO()
    with ZipFile(BytesIO(data)) as source, ZipFile(out, "w", ZIP_DEFLATED) as target:
        for item in source.infolist():
            content = source.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                content = change(content.decode()).encode()
            target.writestr(item, content)
    return out.getvalue()


# ---- sheets and tables --------------------------------------------------------------------------------------


def test_each_sheet_is_a_titled_table_with_the_first_row_as_header():
    text = read(
        book(
            (
                "Orders",
                [["ID", "Region", "Amount"], ["SO-1", "Portugal", 4500], ["SO-2", "Spain", 1200]],
            ),
            ("Targets", [["Region", "Target"], ["Portugal", 60000]]),
        )
    )
    assert text == (
        "## Sheet: Orders\n\n"
        "| ID | Region | Amount |\n| --- | --- | --- |\n| SO-1 | Portugal | 4500 |\n| SO-2 | Spain | 1200 |\n\n"
        "## Sheet: Targets\n\n"
        "| Region | Target |\n| --- | --- |\n| Portugal | 60000 |"
    )


def test_values_are_written_without_float_noise_and_dates_as_iso():
    text = read(
        book(
            (
                "V",
                [
                    ["int", "float", "sum", "yes", "day", "moment", "text"],
                    [3, 2.5, 0.1 + 0.2, True, date(2026, 3, 5), datetime(2026, 3, 5, 14, 30), "x"],
                ],
            )
        )
    )
    assert text.splitlines()[-1] == "| 3 | 2.5 | 0.3 | TRUE | 2026-03-05 | 2026-03-05 14:30 | x |"


def test_blank_rows_blank_columns_and_leading_blank_rows_are_dropped():
    text = read(
        book(
            (
                "S",
                [
                    [None, None, None],
                    [None, "Name", None, "Qty"],
                    [None, None, None],
                    [None, "pen", None, 2],
                ],
            )
        )
    )
    assert text == "## Sheet: S\n\n| Name | Qty |\n| --- | --- |\n| pen | 2 |"


def test_pipes_and_line_breaks_inside_a_cell_cannot_break_the_row():
    text = read(book(("S", [["a|b", "two\nlines"], ["x", "y"]])))
    assert text == "## Sheet: S\n\n| a\\|b | two lines |\n| --- | --- |\n| x | y |"


def test_a_merged_cell_keeps_its_text_once_in_the_top_left_cell():
    workbook = book(("S", [["Region", "Q1", "Q2"], ["Both quarters", None, 11]]))
    workbook["S"].merge_cells("A2:B2")
    assert read(workbook).splitlines()[-1] == "| Both quarters |  | 11 |"


def test_a_very_long_cell_is_cut_with_an_ellipsis():
    text = read(book(("S", [["note", "k"], ["w" * 2000, "z"]])))
    cell = text.splitlines()[-1].split("|")[1].strip()
    assert len(cell) == MAX_CELL_CHARS and cell.endswith("…")


def test_the_sheet_title_is_a_single_line():
    assert read(book(("Q1  report", [["a", "b"], [1, 2]]))).startswith("## Sheet: Q1 report\n")


# ---- what is skipped -------------------------------------------------------------------------------------------


def test_hidden_sheets_are_not_read_and_not_counted():
    workbook = book(("Shown", [["a", "b"], [1, 2]]), ("Secret", [["pw", "x"], ["hunter2", 1]]))
    workbook["Secret"].sheet_state = "hidden"
    text, sheets = extract_xlsx_text(save(workbook))
    assert "Secret" not in text and "hunter2" not in text
    assert sheets == 1


def test_an_empty_sheet_leaves_no_heading_but_all_empty_sheets_leave_no_text():
    workbook = book(("Empty", []), ("Data", [["a", "b"], [1, 2]]))
    assert read(workbook) == "## Sheet: Data\n\n| a | b |\n| --- | --- |\n| 1 | 2 |"
    assert extract_xlsx_text(save(book(("A", []), ("B", [[None, None]])))) == ("", 2)


def test_formula_cells_give_the_stored_result_and_an_unstored_one_is_empty():
    data = save(book(("S", [["label", "value"], ["a", 1], ["total", "=SUM(B2:B2)"]])))
    assert read_from(data).splitlines()[-1] == "| total |  |"  # a script wrote it: no stored result
    stored = patch_sheet_xml(data, lambda xml: re.sub(r"<v\s*/>|<v></v>", "<v>42</v>", xml))
    assert read_from(stored).splitlines()[-1] == "| total | 42 |"


def read_from(data: bytes) -> str:
    return extract_xlsx_text(data)[0]


def test_a_sheet_whose_stored_used_range_is_wrong_is_still_read_completely():
    data = save(book(("S", [["a", "b"], [1, 2], [3, 4], [5, 6]])))
    narrowed = patch_sheet_xml(
        data, lambda xml: re.sub(r'<dimension ref="[^"]*"', '<dimension ref="A1"', xml)
    )
    assert "| 5 | 6 |" in read_from(narrowed)


# ---- size limits, always announced ---------------------------------------------------------------------------


def rows_of(count: int, *, header: str = "n") -> list[list[object]]:
    return [[header, "v"], *([i, i * 2] for i in range(1, count + 1))]


def test_a_sheet_keeps_a_header_and_1000_rows_and_says_it_stopped():
    text = read(book(("Big", rows_of(MAX_ROWS_PER_SHEET + 200))))
    table = [line for line in text.splitlines() if line.startswith("|")]
    assert len(table) == 2 + MAX_ROWS_PER_SHEET
    assert table[-1] == f"| {MAX_ROWS_PER_SHEET} | {MAX_ROWS_PER_SHEET * 2} |"
    assert text.endswith(f"Note: only the first {MAX_ROWS_PER_SHEET} rows are indexed.")


def test_exactly_1000_rows_is_complete_and_has_no_note():
    text = read(book(("Edge", rows_of(MAX_ROWS_PER_SHEET))))
    assert "Note:" not in text
    assert text.splitlines()[-1] == f"| {MAX_ROWS_PER_SHEET} | {MAX_ROWS_PER_SHEET * 2} |"


def test_a_sheet_wider_than_50_columns_keeps_50_and_says_so():
    header = [f"c{i}" for i in range(MAX_COLUMNS + 10)]
    text = read(book(("Wide", [header, list(range(MAX_COLUMNS + 10))])))
    assert text.splitlines()[2].count("|") == MAX_COLUMNS + 1
    assert f"c{MAX_COLUMNS - 1}" in text and f"c{MAX_COLUMNS}" not in text
    assert text.endswith(f"Note: only the first {MAX_COLUMNS} columns are indexed.")


def test_the_workbook_row_budget_is_shared_and_later_sheets_are_listed_not_silently_dropped():
    sheets = [
        (f"S{i}", rows_of(MAX_ROWS_PER_SHEET)) for i in range(5)
    ]  # 5 x 1000 = the whole budget
    sheets.append(("Late", rows_of(3)))
    text = read(book(*sheets))
    assert "## Sheet: S4" in text and "## Sheet: Late" not in text
    assert text.endswith("Note: sheets not indexed because of the size limit: Late.")


def test_a_sheet_that_only_partly_fits_the_workbook_budget_is_cut_with_a_note():
    sheets = [(f"S{i}", rows_of(MAX_ROWS_PER_SHEET)) for i in range(4)]  # 4000 used, 1000 left
    sheets.append(("Part", rows_of(MAX_ROWS_PER_SHEET + 5)))
    text = read(book(*sheets))
    part = text.split("## Sheet: Part")[1]
    assert part.count("\n| ") == 2 + MAX_ROWS_PER_SHEET  # header, separator, 1000 rows
    assert part.endswith(f"Note: only the first {MAX_ROWS_PER_SHEET} rows are indexed.")


def test_more_than_25_sheets_keeps_25_and_lists_the_rest():
    text = read(book(*[(f"T{i:02d}", [["a", "b"], [i, i]]) for i in range(30)]))
    assert text.count("## Sheet: ") == 25
    assert text.endswith(
        "Note: sheets not indexed because of the size limit: T25, T26, T27, T28, T29."
    )


def test_the_list_of_left_out_sheets_is_itself_capped():
    text = read(book(*[(f"T{i:02d}", [["a", "b"], [i, i]]) for i in range(40)]))
    assert text.endswith("T25, T26, T27, T28, T29, T30, T31, T32, T33, T34 and 5 more.")


# ---- damaged, wrong or oversized files -----------------------------------------------------------------------


def test_empty_garbage_and_wrong_type_are_extraction_errors():
    with pytest.raises(ExtractionError, match="XLSX file is empty"):
        extract_xlsx_text(b"")
    with pytest.raises(ExtractionError, match="Failed to read XLSX content"):
        extract_xlsx_text(b"not a workbook")
    with pytest.raises(ExtractionError, match="does not support MIME type"):
        XlsxTextExtractor().extract(b"x", mime_type=DOCX_MIME, filename="x.docx")


def test_a_zip_that_is_not_a_workbook_is_an_extraction_error():
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("hello.txt", "hi")
    with pytest.raises(ExtractionError, match="Failed to read XLSX content"):
        extract_xlsx_text(buffer.getvalue())


def test_a_workbook_over_the_size_limit_is_refused(monkeypatch: pytest.MonkeyPatch):
    data = save(book(("S", [["a", "b"], [1, 2]])))
    monkeypatch.setattr(xlsx_module, "MAX_XLSX_BYTES", len(data) - 1)
    with pytest.raises(ExtractionError, match="too large"):
        extract_xlsx_text(data)


def test_a_small_file_that_unpacks_to_a_huge_one_is_refused(monkeypatch: pytest.MonkeyPatch):
    data = save(book(("S", [["a", "b"], [1, 2]])))
    monkeypatch.setattr(xlsx_module, "MAX_UNPACKED_BYTES", 100)
    with pytest.raises(ExtractionError, match="too large once unpacked"):
        extract_xlsx_text(data)


# ---- extractor class -----------------------------------------------------------------------------------------


def test_extractor_reports_visible_sheet_count_and_registers_for_xlsx():
    data = save(book(("A", [["x", "y"], [1, 2]]), ("B", [["x", "y"], [3, 4]])))
    result = get_extractor(XLSX_MIME).extract(data, mime_type=XLSX_MIME, filename="b.xlsx")
    assert result.page_count == 2
    assert result.metadata["extractor"] == "xlsx_text"
    assert result.text.count("## Sheet:") == 2
