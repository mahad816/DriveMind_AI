"""Structure the DOCX reader must keep: headings, lists, tables (merged, nested, ragged) and order.

Every test checks the exact output text. A reader that only "contains" the right words would pass loose
checks while still destroying the table rows, so the expected strings below are written out in full.
"""

from __future__ import annotations

from io import BytesIO

from docx import Document
from docx.document import Document as DocumentType
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls

from app.ingestion.extractors.docx import extract_docx_text


def read(document: DocumentType) -> str:
    buffer = BytesIO()
    document.save(buffer)
    return extract_docx_text(buffer.getvalue())


def grid(document: DocumentType, rows: list[list[str]]):
    table = document.add_table(rows=len(rows), cols=max(len(r) for r in rows))
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            table.cell(r, c).text = text
    return table


# ---- headings and lists --------------------------------------------------------------------------


def test_title_and_numbered_heading_styles_become_markdown_headings():
    document = Document()
    document.add_heading("Report", level=0)  # style "Title"
    document.add_heading("Part one", level=1)
    document.add_heading("Detail", level=3)
    document.add_paragraph("Body text.")
    assert read(document) == "# Report\n\n# Part one\n\n### Detail\n\nBody text."


def test_list_styles_become_bullets_with_one_indent_step_per_level_and_no_blank_lines_between_items():
    document = Document()
    document.add_paragraph("Intro")
    document.add_paragraph("one", style="List Bullet")
    document.add_paragraph("two", style="List Bullet")
    document.add_paragraph("nested", style="List Bullet 2")
    document.add_paragraph("first step", style="List Number")
    document.add_paragraph("After the list")
    assert read(document) == ("Intro\n\n- one\n- two\n  - nested\n- first step\n\nAfter the list")


def test_a_paragraph_numbered_directly_is_a_list_item_but_numbering_switched_off_is_not():
    document = Document()
    listed = document.add_paragraph("directly numbered")
    listed._p.get_or_add_pPr().append(
        parse_xml(f'<w:numPr {nsdecls("w")}><w:ilvl w:val="1"/><w:numId w:val="7"/></w:numPr>')
    )
    plain = document.add_paragraph("numbering removed", style="List Bullet")
    plain._p.get_or_add_pPr().append(
        parse_xml(f'<w:numPr {nsdecls("w")}><w:numId w:val="0"/></w:numPr>')
    )
    assert read(document) == "  - directly numbered\n\nnumbering removed"


def test_blank_paragraphs_are_dropped_and_line_breaks_inside_a_paragraph_are_kept():
    document = Document()
    document.add_paragraph("   ")
    document.add_paragraph("line one\nline two")
    document.add_paragraph("")
    assert read(document) == "line one\nline two"


# ---- tables --------------------------------------------------------------------------------------


def test_table_becomes_header_separator_and_rows_between_its_paragraphs():
    document = Document()
    document.add_paragraph("Before")
    grid(document, [["Name", "Qty"], ["Bolt", "10"], ["Nut", "25"]])
    document.add_paragraph("After")
    assert read(document) == (
        "Before\n\n| Name | Qty |\n| --- | --- |\n| Bolt | 10 |\n| Nut | 25 |\n\nAfter"
    )


def test_a_table_that_opens_the_document_is_read_in_the_right_place():
    document = Document()
    grid(document, [["A", "B"], ["1", "2"]])
    document.add_paragraph("Tail")
    assert read(document) == "| A | B |\n| --- | --- |\n| 1 | 2 |\n\nTail"


def test_pipes_in_a_cell_are_escaped_and_multi_paragraph_cells_stay_on_one_line():
    document = Document()
    table = grid(document, [["Expr", "Note"], ["a|b", "x"]])
    cell = table.cell(1, 1)
    cell.add_paragraph("second paragraph")
    assert read(document) == "| Expr | Note |\n| --- | --- |\n| a\\|b | x second paragraph |"


def test_horizontally_merged_cell_keeps_its_text_once_and_the_row_keeps_its_width():
    document = Document()
    table = grid(document, [["Region", "Q1", "Q2"], ["North", "5", "6"], ["", "", ""]])
    table.cell(2, 0).merge(table.cell(2, 1))
    table.cell(2, 0).text = "Total across Q1 and Q2"
    table.cell(2, 2).text = "11"
    assert read(document).splitlines()[-1] == "| Total across Q1 and Q2 |  | 11 |"


def test_vertically_merged_cell_is_not_repeated_on_the_rows_it_covers():
    document = Document()
    table = grid(document, [["Team", "Person"], ["", "Ana"], ["", "Ben"]])
    table.cell(1, 0).merge(table.cell(2, 0))
    table.cell(1, 0).text = "Support"
    # some generators repeat the text inside the covered cell: it must still be read only once
    covered = table._tbl.tr_lst[2].tc_lst[0]
    assert covered.vMerge == "continue"
    covered.append(parse_xml(f"<w:p {nsdecls('w')}><w:r><w:t>Support</w:t></w:r></w:p>"))
    assert read(document).splitlines()[2:] == ["| Support | Ana |", "|  | Ben |"]


def test_a_nested_table_is_flattened_into_its_cell():
    document = Document()
    outer = grid(document, [["Item", "Detail"], ["Kit", ""]])
    inner = outer.cell(1, 1).add_table(rows=1, cols=2)
    inner.cell(0, 0).text = "red"
    inner.cell(0, 1).text = "blue"
    assert read(document).splitlines()[-1] == "| Kit | red blue |"


def test_rows_with_fewer_cells_are_padded_to_the_widest_row():
    document = Document()
    table = grid(document, [["A", "B", "C"], ["1", "2", "3"]])
    table._tbl.tr_lst[1].remove(table._tbl.tr_lst[1].tc_lst[2])
    assert read(document).splitlines()[-1] == "| 1 | 2 |  |"


def test_tables_without_any_text_are_left_out_entirely():
    document = Document()
    document.add_paragraph("Only this")
    grid(document, [["", ""], ["", ""]])
    assert read(document) == "Only this"


# ---- other body structure ------------------------------------------------------------------------


def test_paragraphs_inside_a_content_control_are_read_in_order():
    document = Document()
    document.add_paragraph("Before")
    control = parse_xml(
        f"<w:sdt {nsdecls('w')}><w:sdtContent><w:p><w:r><w:t>Inside the control</w:t></w:r></w:p>"
        "</w:sdtContent></w:sdt>"
    )
    document.element.body.insert(len(document.element.body) - 1, control)  # before sectPr
    document.add_paragraph("After")
    assert read(document) == "Before\n\nInside the control\n\nAfter"


def test_header_and_footer_text_is_not_part_of_the_document_text():
    document = Document()
    document.sections[0].header.paragraphs[0].text = "COMPANY CONFIDENTIAL"
    document.sections[0].footer.paragraphs[0].text = "Page footer"
    document.add_paragraph("Real content")
    assert read(document) == "Real content"


def test_a_pipe_free_cell_with_only_whitespace_does_not_break_the_row():
    document = Document()
    grid(document, [["A", "B"], ["  ", "x"]])
    assert read(document).splitlines()[-1] == "|  | x |"
