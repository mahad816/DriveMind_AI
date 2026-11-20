"""PPTX reader: exact output for slides, bullets, tables, notes, groups and slide furniture.

Every test checks the full expected text so a reader that only "contains" the right words cannot
pass while scrambling structure.
"""

from __future__ import annotations

from io import BytesIO

import pytest
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml import parse_xml
from pptx.oxml.ns import nsdecls
from pptx.presentation import Presentation as PresentationType
from pptx.shapes.autoshape import Shape
from pptx.shapes.placeholder import SlidePlaceholder
from pptx.slide import Slide
from pptx.text.text import TextFrame
from pptx.util import Emu, Inches

from app.connectors.google_drive.constants import DOCX_MIME, PPTX_MIME
from app.ingestion.extractors import PptxTextExtractor, get_extractor
from app.ingestion.extractors.base import ExtractionError
from app.ingestion.extractors.pptx import extract_pptx_text

TITLE_ONLY, TITLE_AND_CONTENT, BLANK = 5, 1, 6


def read(prs: PresentationType) -> str:
    buffer = BytesIO()
    prs.save(buffer)
    return extract_pptx_text(buffer.getvalue())[0]


def frame_of(shape: object) -> TextFrame:
    assert isinstance(shape, Shape | SlidePlaceholder)
    return shape.text_frame


def title_frame(slide: Slide) -> TextFrame:
    return frame_of(slide.shapes.title)


def write_notes(slide: Slide, text: str) -> None:
    frame = slide.notes_slide.notes_text_frame
    assert frame is not None
    frame.text = text


def new_slide(prs: PresentationType, layout: int, title: str | None = None) -> Slide:
    slide = prs.slides.add_slide(prs.slide_layouts[layout])
    if title is not None:
        title_frame(slide).text = title
    return slide


def textbox(slide: Slide, text: str, *, left=0.7, top=3.0, width=4.0):
    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(0.6))
    box.text_frame.text = text
    return box


# ---- slides, titles, bullets --------------------------------------------------------------------


def test_content_placeholder_paragraphs_are_bullets_with_one_indent_step_per_level():
    prs = Presentation()
    slide = new_slide(prs, TITLE_AND_CONTENT, "Plan")
    frame = frame_of(slide.placeholders[1])
    frame.text = "Phase one"
    nested = frame.add_paragraph()
    nested.text = "detail"
    nested.level = 1
    frame.add_paragraph().text = "Phase two"
    assert read(prs) == "## Slide 1: Plan\n\n- Phase one\n  - detail\n- Phase two"


def test_a_text_box_is_a_plain_paragraph_unless_it_has_an_explicit_bullet():
    prs = Presentation()
    slide = new_slide(prs, TITLE_ONLY, "Mixed")
    textbox(slide, "plain sentence", top=2.0)
    bulleted = textbox(slide, "bullet in a box", top=3.0)
    bulleted.text_frame.paragraphs[0]._p.get_or_add_pPr().append(
        parse_xml(f'<a:buChar {nsdecls("a")} char="&#8226;"/>')
    )
    assert read(prs) == "## Slide 1: Mixed\n\nplain sentence\n\n- bullet in a box"


def test_bullet_switched_off_in_a_content_placeholder_gives_a_plain_paragraph():
    prs = Presentation()
    slide = new_slide(prs, TITLE_AND_CONTENT, "Quote")
    paragraph = frame_of(slide.placeholders[1]).paragraphs[0]
    paragraph.text = "No bullet here"
    paragraph._p.get_or_add_pPr().append(parse_xml(f"<a:buNone {nsdecls('a')}/>"))
    assert read(prs) == "## Slide 1: Quote\n\nNo bullet here"


def test_slide_numbers_count_every_slide_even_when_an_empty_one_is_left_out():
    prs = Presentation()
    new_slide(prs, TITLE_ONLY, "First")
    new_slide(prs, BLANK)  # nothing on it
    new_slide(prs, TITLE_ONLY, "Third")
    assert read(prs) == "## Slide 1: First\n\n## Slide 3: Third"


def test_a_slide_without_a_title_still_gets_a_numbered_heading():
    prs = Presentation()
    slide = new_slide(prs, BLANK)
    textbox(slide, "Only a text box")
    assert read(prs) == "## Slide 1\n\nOnly a text box"


def test_hidden_slides_are_read_and_marked():
    prs = Presentation()
    slide = new_slide(prs, TITLE_ONLY, "Backup")
    slide._element.set("show", "0")
    assert read(prs) == "## Slide 1: Backup (hidden)"


def test_line_breaks_inside_a_title_or_bullet_become_spaces():
    prs = Presentation()
    slide = new_slide(prs, TITLE_AND_CONTENT)
    title_frame(slide).text = "Two\vlines"
    frame_of(slide.placeholders[1]).text = "wrapped\vitem"
    assert read(prs) == "## Slide 1: Two lines\n\n- wrapped item"


# ---- tables -----------------------------------------------------------------------------------------


def test_a_table_has_a_header_separator_and_escaped_pipes():
    prs = Presentation()
    slide = new_slide(prs, TITLE_ONLY, "Data")
    table = slide.shapes.add_table(2, 2, Inches(1), Inches(2), Inches(6), Inches(2)).table
    for (r, c), value in {(0, 0): "Item", (0, 1): "Note", (1, 0): "a|b", (1, 1): "ok"}.items():
        table.cell(r, c).text = value
    assert read(prs) == "## Slide 1: Data\n\n| Item | Note |\n| --- | --- |\n| a\\|b | ok |"


def test_a_merged_table_cell_keeps_its_text_once():
    prs = Presentation()
    slide = new_slide(prs, TITLE_ONLY, "Merged")
    table = slide.shapes.add_table(2, 3, Inches(1), Inches(2), Inches(6), Inches(2)).table
    for c, value in enumerate(["Region", "Q1", "Q2"]):
        table.cell(0, c).text = value
    table.cell(1, 0).text = "Both quarters"
    table.cell(1, 0).merge(table.cell(1, 1))
    assert table.cell(1, 1).is_spanned
    table.cell(1, 1).text = "Both quarters"  # some generators repeat the text in the covered cell
    table.cell(1, 2).text = "11"
    assert read(prs).splitlines()[-1] == "| Both quarters |  | 11 |"


# ---- notes, order, furniture ----------------------------------------------------------------------


def test_notes_follow_the_slide_content_and_join_their_paragraphs():
    prs = Presentation()
    slide = new_slide(prs, TITLE_ONLY, "Decision")
    write_notes(slide, "First point.\nSecond point.")
    assert read(prs) == "## Slide 1: Decision\n\nNotes: First point. Second point."


def test_a_slide_with_only_speaker_notes_is_kept():
    prs = Presentation()
    slide = new_slide(prs, BLANK)
    write_notes(slide, "Remember to mention the 55,000 budget.")
    assert read(prs) == "## Slide 1\n\nNotes: Remember to mention the 55,000 budget."


def test_shapes_are_read_top_to_bottom_and_side_by_side_boxes_left_to_right():
    prs = Presentation()
    slide = new_slide(prs, BLANK)
    textbox(slide, "bottom", top=5.0)
    textbox(slide, "right column", left=5.0, top=1.1)  # slightly lower than its neighbour
    textbox(slide, "left column", left=0.5, top=1.0)
    assert read(prs) == "## Slide 1\n\nleft column\n\nright column\n\nbottom"


def test_footer_date_and_slide_number_placeholders_are_not_repeated_in_the_text():
    prs = Presentation()
    slide = new_slide(prs, TITLE_ONLY, "Real")
    for kind, text in (("ftr", "Company confidential"), ("dt", "20 Nov 2026"), ("sldNum", "7")):
        slide.shapes._spTree.append(
            parse_xml(
                f'<p:sp {nsdecls("p", "a")}><p:nvSpPr><p:cNvPr id="{90 + len(kind)}" name="{kind}"/>'
                f'<p:cNvSpPr/><p:nvPr><p:ph type="{kind}"/></p:nvPr></p:nvSpPr><p:spPr/>'
                f"<p:txBody><a:bodyPr/><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:txBody></p:sp>"
            )
        )
    assert read(prs) == "## Slide 1: Real"


def test_text_inside_a_group_is_read():
    prs = Presentation()
    slide = new_slide(prs, BLANK)
    group = slide.shapes.add_group_shape()
    box = group.shapes.add_textbox(Inches(1), Inches(1), Inches(3), Inches(0.5))
    box.text_frame.text = "Inside the group"
    assert read(prs) == "## Slide 1\n\nInside the group"


def test_pictures_and_empty_shapes_add_nothing():
    prs = Presentation()
    slide = new_slide(prs, TITLE_ONLY, "Picture slide")
    slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Emu(0), Emu(0), Inches(1), Inches(1)
    )  # empty rectangle
    assert read(prs) == "## Slide 1: Picture slide"


# ---- extractor class and failures -------------------------------------------------------------------


def test_extractor_reports_slide_count_as_page_count_and_registers_for_pptx():
    prs = Presentation()
    new_slide(prs, TITLE_ONLY, "A")
    new_slide(prs, TITLE_ONLY, "B")
    buffer = BytesIO()
    prs.save(buffer)
    result = get_extractor(PPTX_MIME).extract(
        buffer.getvalue(), mime_type=PPTX_MIME, filename="d.pptx"
    )
    assert result.page_count == 2
    assert result.metadata["extractor"] == "pptx_text"
    assert result.text == "## Slide 1: A\n\n## Slide 2: B"


def test_empty_bytes_garbage_and_wrong_mime_type_are_extraction_errors():
    with pytest.raises(ExtractionError, match="PPTX file is empty"):
        extract_pptx_text(b"")
    with pytest.raises(ExtractionError, match="Failed to read PPTX content"):
        extract_pptx_text(b"not a presentation")
    with pytest.raises(ExtractionError, match="does not support MIME type"):
        PptxTextExtractor().extract(b"x", mime_type=DOCX_MIME, filename="x.docx")
