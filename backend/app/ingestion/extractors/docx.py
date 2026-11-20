"""DOCX text extraction (also used for Google Docs, which are exported as DOCX).

The output is "light Markdown" so structure survives as plain text: headings as ``#``, list items as
``- ``, tables as ``| a | b |`` rows with a header row. Blocks are separated by a blank line, which is
what the chunker prefers to cut at.

Deliberate limits: headers, footers, text boxes, footnotes, comments and images are not read; a nested
table is flattened into the text of the cell that contains it; numbered lists become ``- `` items.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from io import BytesIO
from typing import cast
from zipfile import BadZipFile

from docx import Document
from docx.document import Document as DocumentType
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.ns import qn
from docx.oxml.numbering import CT_NumPr
from docx.oxml.xmlchemy import BaseOxmlElement
from docx.oxml.table import CT_Tbl
from docx.oxml.text.parfmt import CT_PPr
from docx.oxml.text.paragraph import CT_P
from docx.text.paragraph import Paragraph

from app.connectors.google_drive.constants import DOCX_MIME
from app.ingestion.extractors.base import ExtractionError, ExtractionResult
from app.ingestion.extractors.light_markdown import (
    Block,
    join_blocks,
    markdown_table,
    one_line,
    table_cell,
)
from app.ingestion.extractors.plain_text import normalize_extracted_text
from app.ingestion.extractors.registry import register_extractor

_HEADING_STYLE = re.compile(r"^heading\s*(\d)$", re.IGNORECASE)
_MAX_HEADING_LEVEL = 6


def _body_elements(parent: BaseOxmlElement) -> Iterator[CT_P | CT_Tbl]:
    """Paragraphs and tables in document order, looking inside content controls (``w:sdt``)."""
    for child in parent.iterchildren():
        if isinstance(child, CT_P | CT_Tbl):
            yield child
        elif child.tag == qn("w:sdt"):
            content = child.find(qn("w:sdtContent"))
            if content is not None:
                yield from _body_elements(content)


def _heading_level(paragraph: Paragraph) -> int | None:
    style = paragraph.style
    name = (style.name if style is not None else "") or ""
    if name.lower() == "title":
        return 1
    match = _HEADING_STYLE.match(name.strip())
    if match:
        return min(max(int(match.group(1)), 1), _MAX_HEADING_LEVEL)
    return None


_LIST_STYLE = re.compile(r"^list\s+(?:bullet|number)(?:\s+(\d))?$", re.IGNORECASE)


_NUMBERING_OFF = -1


def _numbering_level(properties: CT_PPr | None) -> int | None:
    """Level from a ``numPr`` block; ``None`` when absent, ``_NUMBERING_OFF`` when switched off (id 0)."""
    numbering = cast("CT_NumPr | None", properties.numPr if properties is not None else None)
    if numbering is None:
        return None
    if getattr(numbering.numId, "val", None) == 0:
        return _NUMBERING_OFF
    return int(getattr(numbering.ilvl, "val", None) or 0)


def _list_level(paragraph: Paragraph) -> int | None:
    """Nesting level (0, 1, ...) when the paragraph is a list item, else ``None``.

    Word stores list membership either on the paragraph or in its style ("List Bullet" and similar),
    so the style and the styles it is based on are checked as well. Numbering switched off on the
    paragraph itself wins over the style.
    """
    direct = _numbering_level(paragraph._p.pPr)  # noqa: SLF001
    if direct is not None:
        return None if direct == _NUMBERING_OFF else direct
    style = paragraph.style
    named = _LIST_STYLE.match((style.name if style is not None else "") or "")
    if named:
        return max(int(named.group(1) or 1) - 1, 0)
    while style is not None:
        level = _numbering_level(style.element.pPr)
        if level is not None:
            return None if level == _NUMBERING_OFF else level
        style = getattr(style, "base_style", None)
    return None


def _cell_text(cell: BaseOxmlElement) -> str:
    """Text of a table cell on one line; a nested table is flattened into it."""
    parts: list[str] = []
    for element in _body_elements(cell):
        if isinstance(element, CT_P):
            parts.append(Paragraph(element, None).text)  # type: ignore[arg-type]
        else:
            for row in element.tr_lst:
                parts.extend(_cell_text(tc) for tc in row.tc_lst)
    return table_cell(" ".join(part for part in parts if part.strip()))


def _table_rows(table: CT_Tbl) -> list[list[str]]:
    """Rows of cell texts. A merged cell keeps its text once; the cells it covers are empty."""
    rows: list[list[str]] = []
    for row in table.tr_lst:
        cells: list[str] = []
        for tc in row.tc_lst:
            continuation = tc.vMerge == "continue"
            cells.append("" if continuation else _cell_text(tc))
            cells.extend([""] * (tc.grid_span - 1))
        rows.append(cells)
    return rows


def _blocks(document: DocumentType) -> list[Block]:
    blocks: list[Block] = []
    for element in _body_elements(document.element.body):
        if isinstance(element, CT_Tbl):
            markdown = markdown_table(_table_rows(element))
            if markdown:
                blocks.append(("table", markdown))
            continue
        paragraph = Paragraph(element, document)
        text = paragraph.text.strip()
        if not text:
            continue
        level = _heading_level(paragraph)
        if level is not None:
            blocks.append(("heading", f"{'#' * level} {one_line(text)}"))
            continue
        item_level = _list_level(paragraph)
        if item_level is not None:
            blocks.append(("list", f"{'  ' * item_level}- {one_line(text)}"))
        else:
            blocks.append(("paragraph", text))
    return blocks


def extract_docx_text(data: bytes) -> str:
    """Extract light-Markdown text from DOCX bytes (paragraphs, headings, lists and tables in order)."""
    if not data:
        raise ExtractionError("DOCX file is empty")

    try:
        document = Document(BytesIO(data))
    except (PackageNotFoundError, BadZipFile, ValueError) as exc:
        raise ExtractionError("Failed to read DOCX content") from exc

    text = join_blocks(_blocks(document))
    return normalize_extracted_text(text)


class DocxTextExtractor:
    """Extract light-Markdown text from DOCX files using python-docx."""

    def extract(self, data: bytes, *, mime_type: str, filename: str) -> ExtractionResult:
        if mime_type != DOCX_MIME:
            raise ExtractionError(f"DocxTextExtractor does not support MIME type: {mime_type}")

        try:
            text = extract_docx_text(data)
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError(f"Failed to extract text from DOCX: {filename}") from exc

        return ExtractionResult(
            text=text,
            page_count=None,
            metadata={
                "extractor": "docx_text",
                "source_mime_type": mime_type,
                "filename": filename,
            },
        )


def register_docx_extractor() -> None:
    """Register the DOCX text extractor for Word document MIME type."""
    register_extractor(DOCX_MIME, DocxTextExtractor())
