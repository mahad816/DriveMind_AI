"""Which detected tables are used: the strict filter, cleaning and the page box."""

from __future__ import annotations

from app.ingestion.extractors.pdf_tables import PageTable, accept_table, clean_rows

PAGE = {"page_width": 600.0, "page_height": 800.0}
BOX = {"box_width": 300.0, "box_height": 120.0}


def accepted(rows, **overrides):
    return accept_table(rows, **{**BOX, **PAGE, **overrides})


GOOD = [["Country", "2024", "2025"], ["Portugal", "24", "36"], ["Spain", "10", "17"]]


def test_a_filled_table_with_a_header_and_rows_is_accepted():
    assert accepted(GOOD)


def test_a_single_row_or_single_column_is_a_rule_line_not_a_table():
    assert not accepted([["a", "b", "c"]])
    assert not accepted([["a"], ["b"], ["c"]])


def test_a_mostly_empty_table_is_rejected_and_a_mostly_filled_one_accepted():
    sparse = [["Name", "", ""], ["", "x", ""], ["", "", ""]]
    assert not accepted(sparse)
    almost = [["a", "b", "c", "d", "e"], ["f", "g", "h", "i", ""]]  # 9 of 10 filled
    assert accepted(almost)


def test_cells_with_only_punctuation_do_not_count_as_filled():
    assert not accepted([["--", "--"], ["..", "||"], ["Name", "Value"]])


def test_a_box_that_is_the_whole_page_is_rejected_but_a_tall_or_wide_one_is_not():
    assert not accepted(GOOD, box_width=580.0, box_height=780.0)
    assert accepted(GOOD, box_width=580.0, box_height=300.0)  # full width, part of the height
    assert accepted(GOOD, box_width=300.0, box_height=780.0)  # full height, part of the width


def test_cells_that_are_paragraphs_make_a_layout_box_not_a_data_table():
    paragraph = "word " * 40  # 200 characters
    assert not accepted([[paragraph, paragraph], [paragraph, paragraph]])


def test_clean_rows_puts_each_cell_on_one_line_and_drops_empty_rows_and_columns():
    raw = [["Item\nname", None, "Qty"], [None, None, None], ["Pen", None, "2"]]
    assert clean_rows(raw) == [["Item name", "Qty"], ["Pen", "2"]]


def test_clean_rows_of_nothing_is_empty():
    assert clean_rows([[None, ""], [" ", None]]) == []
    assert clean_rows([]) == []


def test_a_table_contains_a_point_inside_its_box_with_a_two_point_margin():
    table = PageTable(
        left=100, bottom=200, right=300, top=400, cells=("a",), markdown="| a |\n| --- |"
    )
    assert table.contains(100, 200) and table.contains(300, 400) and table.contains(200, 300)
    assert table.contains(98.5, 401.5)
    assert not table.contains(97, 300) and not table.contains(200, 403)
