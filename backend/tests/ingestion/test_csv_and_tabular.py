"""CSV reader, Markdown files, and the shared table builder (values, limits, notes)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest

from app.connectors.google_drive.constants import CSV_MIME, MARKDOWN_MIME, TXT_MIME
from app.ingestion.extractors import CsvTextExtractor, get_extractor
from app.ingestion.extractors import csv_text as csv_module
from app.ingestion.extractors import tabular
from app.ingestion.extractors.base import ExtractionError
from app.ingestion.extractors.csv_text import extract_csv_text
from app.ingestion.extractors.tabular import MAX_CELL_CHARS, build_table, format_value

# ---- values --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (None, ""),
        (True, "TRUE"),
        (False, "FALSE"),
        (7, "7"),
        (7.0, "7"),
        (2.5, "2.5"),
        (0.1 + 0.2, "0.3"),
        (-3.0, "-3"),
        (1e20, "1e+20"),
        (float("nan"), "nan"),
        (date(2026, 3, 5), "2026-03-05"),
        (datetime(2026, 3, 5), "2026-03-05"),
        (datetime(2026, 3, 5, 14, 30), "2026-03-05 14:30"),
        (datetime(2026, 3, 5, 14, 30, 9), "2026-03-05 14:30:09"),
        (time(9, 5), "09:05"),
        (timedelta(hours=1), "1:00:00"),
        ("a|b\nc", "a\\|b c"),
        ("  spaced   out ", "spaced out"),
    ],
)
def test_format_value(value, text):
    assert format_value(value) == text


def test_a_long_text_value_is_cut_to_the_cell_limit():
    cut = format_value("word " * 400)
    assert len(cut) <= MAX_CELL_CHARS and cut.endswith("…")


# ---- build_table -----------------------------------------------------------------------------------------------


def test_build_table_header_rows_blank_rows_and_columns():
    table = build_table(
        [[None, None], ["a", None, "b"], [None, None, None], ["1", None, "2"]], row_limit=10
    )
    assert table.markdown == "| a | b |\n| --- | --- |\n| 1 | 2 |"
    assert not (table.rows_cut or table.columns_cut or table.scan_cut)
    assert table.notes(row_limit=10) == ""


def test_build_table_of_nothing_is_empty():
    assert build_table([], row_limit=5).markdown == ""
    assert build_table([[None], ["", ""]], row_limit=5).markdown == ""


def test_row_limit_counts_data_rows_and_the_header_is_extra():
    rows = [["h"], *([str(i)] for i in range(1, 6))]
    exact = build_table(rows, row_limit=5)
    assert exact.markdown.count("\n") == 6 and not exact.rows_cut
    cut = build_table(rows, row_limit=4)
    assert cut.rows_cut and cut.markdown.splitlines()[-1] == "| 4 |"
    assert cut.notes(row_limit=4) == "Note: only the first 4 rows are indexed."


def test_blank_rows_do_not_use_up_the_row_limit():
    rows = [["h"], [None], ["1"], [None], ["2"]]
    assert not build_table(rows, row_limit=2).rows_cut


def test_columns_over_the_limit_are_cut_and_only_flagged_when_they_held_values(monkeypatch):
    monkeypatch.setattr(tabular, "MAX_COLUMNS", 2)
    flagged = build_table([["a", "b", "c"], ["1", "2", "3"]], row_limit=5)
    assert flagged.markdown.splitlines()[0] == "| a | b |" and flagged.columns_cut
    assert flagged.notes(row_limit=5) == "Note: only the first 2 columns are indexed."
    assert not build_table([["a", "b", None], ["1", "2", ""]], row_limit=5).columns_cut


def test_a_huge_run_of_blank_rows_stops_the_scan_and_is_announced(monkeypatch):
    monkeypatch.setattr(tabular, "MAX_SCANNED_ROWS", 10)
    table = build_table([["h"], ["1"], *([None] for _ in range(50)), ["lost"]], row_limit=100)
    assert table.scan_cut and "lost" not in table.markdown
    assert "only the first 100 rows" in table.notes(row_limit=100)


def test_both_notes_are_joined():
    table = tabular.TableText("x", rows_cut=True, columns_cut=True)
    assert table.notes(row_limit=7) == (
        f"Note: only the first 7 rows are indexed and only the first {tabular.MAX_COLUMNS} columns are indexed."
    )


# ---- CSV -------------------------------------------------------------------------------------------------------


def test_comma_separated_file_is_a_table():
    assert extract_csv_text(b"name,qty\npen,2\nink,5\n") == (
        "| name | qty |\n| --- | --- |\n| pen | 2 |\n| ink | 5 |"
    )


@pytest.mark.parametrize("delimiter", [";", "\t", "|"])
def test_semicolon_tab_and_pipe_files_are_detected(delimiter):
    data = f"name{delimiter}qty\npen{delimiter}2\nink{delimiter}5\n".encode()
    assert extract_csv_text(data) == "| name | qty |\n| --- | --- |\n| pen | 2 |\n| ink | 5 |"


def test_quoted_commas_and_line_breaks_stay_inside_their_cell():
    data = b'name,note\n"Smith, J","line one\nline two"\n'
    assert (
        extract_csv_text(data) == "| name | note |\n| --- | --- |\n| Smith, J | line one line two |"
    )


def test_a_byte_order_mark_and_latin_1_text_are_handled():
    assert (
        extract_csv_text("﻿city,n\nMálaga,1\n".encode())
        == "| city | n |\n| --- | --- |\n| Málaga | 1 |"
    )
    assert (
        extract_csv_text("city,n\nMálaga,1\n".encode("latin-1")).splitlines()[-1]
        == "| Málaga | 1 |"
    )


def test_short_rows_are_padded_and_a_single_column_file_works():
    assert extract_csv_text(b"a,b,c\n1,2\n") == "| a | b | c |\n| --- | --- | --- |\n| 1 | 2 |  |"
    assert extract_csv_text(b"item\npen\nink\n") == "| item |\n| --- |\n| pen |\n| ink |"


def test_an_empty_or_blank_file_gives_no_text():
    assert extract_csv_text(b"") == ""
    assert extract_csv_text(b"\n \n,,\n") == ""


def test_csv_row_limit_is_announced(monkeypatch):
    monkeypatch.setattr(csv_module, "MAX_ROWS_PER_SHEET", 2)
    text = extract_csv_text(b"h\n1\n2\n3\n")
    assert text == "| h |\n| --- |\n| 1 |\n| 2 |\n\nNote: only the first 2 rows are indexed."


def test_a_nul_byte_cannot_reach_the_database():
    assert "\x00" not in extract_csv_text(b"a,b\nx\x00y,2\n")


def test_a_cell_beyond_the_csv_module_field_limit_is_an_extraction_error():
    with pytest.raises(ExtractionError, match="Failed to read CSV content"):
        extract_csv_text(b"a,b\n" + b"x" * 200_000 + b",1\n")


def test_csv_extractor_registers_reports_metadata_and_rejects_other_types():
    result = get_extractor(CSV_MIME).extract(b"a,b\n1,2\n", mime_type=CSV_MIME, filename="t.csv")
    assert result.text == "| a | b |\n| --- | --- |\n| 1 | 2 |"
    assert result.page_count is None and result.metadata["extractor"] == "csv_text"
    with pytest.raises(ExtractionError, match="does not support MIME type"):
        CsvTextExtractor().extract(b"x", mime_type=TXT_MIME, filename="x.txt")


# ---- Markdown files --------------------------------------------------------------------------------------------


def test_markdown_files_are_read_as_they_are():
    source = "# Title\n\n- one\n- two  \n"
    result = get_extractor(MARKDOWN_MIME).extract(
        source.encode(), mime_type=MARKDOWN_MIME, filename="n.md"
    )
    assert result.text == "# Title\n\n- one\n- two"
    assert result.metadata["source_mime_type"] == MARKDOWN_MIME
