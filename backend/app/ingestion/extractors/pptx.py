"""PPTX text extraction (also used for Google Slides, which are exported as PPTX).

Each slide with content becomes a section of light Markdown::

    ## Slide 4: Decisions

    - first bullet
    - second bullet

    | Region | Clinics |
    | --- | --- |
    | Portugal | 4 |

    Notes: what the presenter wrote in the speaker notes

Speaker notes are included because decisions and numbers are often only written there. Footer, date and
slide-number placeholders are skipped (they repeat on every slide). Hidden slides are read and marked.

Deliberate limits: charts, SmartArt, pictures and embedded objects are not read (no OCR); animations and
comments are ignored; a table cell with a merged region keeps its text once.
"""

from __future__ import annotations

from collections.abc import Iterable
from io import BytesIO
from typing import Any, cast
from zipfile import BadZipFile

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER
from pptx.exc import PackageNotFoundError
from pptx.oxml.ns import qn
from pptx.slide import Slide
from pptx.text.text import _Paragraph  # noqa: PLC2701

from app.connectors.google_drive.constants import PPTX_MIME
from app.ingestion.extractors.base import classify_unexpected, ExtractionError, ExtractionResult
from app.ingestion.extractors.light_markdown import (
    Block,
    join_blocks,
    markdown_table,
    one_line,
    table_cell,
)
from app.ingestion.extractors.plain_text import normalize_extracted_text
from app.ingestion.extractors.registry import register_extractor

# Shapes whose tops differ by less than this (0.3 inch, in EMU) count as one row, so two side-by-side
# text boxes are read left to right even when one sits slightly lower.
_ROW_BAND = 274_320

_REPEATED_PLACEHOLDERS = frozenset(
    {PP_PLACEHOLDER.FOOTER, PP_PLACEHOLDER.DATE, PP_PLACEHOLDER.SLIDE_NUMBER}
)
_BULLETED_PLACEHOLDERS = frozenset({PP_PLACEHOLDER.BODY, PP_PLACEHOLDER.OBJECT})
_EXPLICIT_BULLET = (qn("a:buChar"), qn("a:buAutoNum"), qn("a:buBlip"))
_LINE_BREAK = "\x0b"  # python-pptx reads <a:br/> as a vertical tab


def _placeholder_type(shape: Any) -> PP_PLACEHOLDER | None:
    if not getattr(shape, "is_placeholder", False):
        return None
    return cast("PP_PLACEHOLDER | None", shape.placeholder_format.type)


def _reading_order(shapes: Iterable[Any]) -> list[Any]:
    def key(shape: Any) -> tuple[int, int]:
        top, left = shape.top, shape.left
        return (top // _ROW_BAND if top is not None else 10**9, left if left is not None else 0)

    return sorted(shapes, key=key)


def _paragraph_text(paragraph: _Paragraph) -> str:
    return one_line(paragraph.text.replace(_LINE_BREAK, " "))


def _is_bullet(
    paragraph: _Paragraph, placeholder: PP_PLACEHOLDER | None, in_placeholder: bool
) -> bool:
    properties = paragraph._p.pPr  # noqa: SLF001
    if properties is not None:
        if properties.find(qn("a:buNone")) is not None:
            return False
        if any(properties.find(tag) is not None for tag in _EXPLICIT_BULLET):
            return True
    return in_placeholder and (placeholder is None or placeholder in _BULLETED_PLACEHOLDERS)


def _text_blocks(shape: Any) -> list[Block]:
    placeholder = _placeholder_type(shape)
    in_placeholder = getattr(shape, "is_placeholder", False)
    blocks: list[Block] = []
    for paragraph in shape.text_frame.paragraphs:
        text = _paragraph_text(paragraph)
        if not text:
            continue
        if _is_bullet(paragraph, placeholder, in_placeholder):
            blocks.append(("list", f"{'  ' * min(paragraph.level, 5)}- {text}"))
        else:
            blocks.append(("paragraph", text))
    return blocks


def _table_blocks(shape: Any) -> list[Block]:
    rows = [
        ["" if cell.is_spanned else table_cell(cell.text) for cell in row.cells]
        for row in shape.table.rows
    ]
    markdown = markdown_table(rows)
    return [("table", markdown)] if markdown else []


def _shape_blocks(shapes: Iterable[Any], title_id: int | None) -> list[Block]:
    blocks: list[Block] = []
    for shape in _reading_order(shapes):
        if shape.shape_id == title_id or _placeholder_type(shape) in _REPEATED_PLACEHOLDERS:
            continue
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            blocks += _shape_blocks(shape.shapes, title_id)
        elif getattr(shape, "has_table", False) and shape.has_table:
            blocks += _table_blocks(shape)
        elif shape.has_text_frame:
            blocks += _text_blocks(shape)
    return blocks


def _is_hidden(slide: Slide) -> bool:
    return bool(slide._element.get("show") == "0")  # noqa: SLF001


def _notes(slide: Slide) -> str:
    if not slide.has_notes_slide:
        return ""
    frame = slide.notes_slide.notes_text_frame
    if frame is None:
        return ""
    return one_line(" ".join(_paragraph_text(p) for p in frame.paragraphs))


def _slide_blocks(number: int, slide: Slide) -> list[Block]:
    title_shape = slide.shapes.title
    title = one_line(title_shape.text_frame.text.replace(_LINE_BREAK, " ")) if title_shape else ""
    body = _shape_blocks(slide.shapes, title_shape.shape_id if title_shape else None)
    notes = _notes(slide)
    if not (title or body or notes):
        return []
    heading = f"## Slide {number}: {title}" if title else f"## Slide {number}"
    if _is_hidden(slide):
        heading += " (hidden)"
    blocks: list[Block] = [("heading", heading), *body]
    if notes:
        blocks.append(("paragraph", f"Notes: {notes}"))
    return blocks


def extract_pptx_text(data: bytes) -> tuple[str, int]:
    """Light-Markdown text of every slide in PPTX bytes, and the number of slides."""
    if not data:
        raise ExtractionError("PPTX file is empty")

    try:
        presentation = Presentation(BytesIO(data))
    except (PackageNotFoundError, BadZipFile, KeyError, ValueError) as exc:
        raise ExtractionError("Failed to read PPTX content") from exc

    blocks: list[Block] = []
    slides = list(presentation.slides)
    for number, slide in enumerate(slides, start=1):
        blocks += _slide_blocks(number, slide)
    return normalize_extracted_text(join_blocks(blocks)), len(slides)


class PptxTextExtractor:
    """Extract light-Markdown text (slides, tables, speaker notes) from PPTX files."""

    def extract(self, data: bytes, *, mime_type: str, filename: str) -> ExtractionResult:
        if mime_type != PPTX_MIME:
            raise ExtractionError(f"PptxTextExtractor does not support MIME type: {mime_type}")

        try:
            text, slide_count = extract_pptx_text(data)
        except ExtractionError:
            raise
        except Exception as exc:
            raise classify_unexpected(exc, f"Failed to extract text from PPTX: {filename}") from exc

        return ExtractionResult(
            text=text,
            page_count=slide_count,
            metadata={
                "extractor": "pptx_text",
                "source_mime_type": mime_type,
                "filename": filename,
            },
        )


def register_pptx_extractor() -> None:
    """Register the PPTX text extractor for the PowerPoint MIME type."""
    register_extractor(PPTX_MIME, PptxTextExtractor())
