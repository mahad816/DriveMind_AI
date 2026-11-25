"""PDF text extraction for born-digital PDF files (no OCR fallback).

What the text looks like (the "light Markdown" contract shared by all readers):

* Pages are separated by a line that holds only a form-feed character (``\\f``), so the page of any
  position is the number of form-feed lines before it plus one. Empty pages still count.
* Running headers, footers and bare page numbers are removed (see ``pdf_furniture``).
* Tables drawn with ruling lines become ``| a | b |`` Markdown tables with a header row, but only when
  they pass a strict quality check (see ``pdf_tables``); in the page text they take the place of the
  cell text they replace. Tables drawn without lines stay flowing text.

Deliberate limits: scanned pages have no text (no OCR); multi-column pages are read in the order the PDF
draws them, which is column by column for normally produced PDFs; rotated pages keep their headers.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

import pdfplumber
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.connectors.google_drive.constants import PDF_MIME
from app.ingestion.extractors.base import classify_unexpected, ExtractionError, ExtractionResult
from app.ingestion.extractors.pdf_furniture import (
    BandLine,
    band_lines,
    furniture_keys,
    remove_furniture,
)
from app.ingestion.extractors.pdf_tables import PageTable, find_page_tables
from app.ingestion.extractors.plain_text import normalize_extracted_text
from app.ingestion.extractors.registry import register_extractor

logger = logging.getLogger(__name__)

PAGE_SEPARATOR = "\f"
# Table detection costs about 4 s per 100 pages; pages beyond this count keep flowing text.
MAX_TABLE_PAGES = 400

# The characters of the text a table replaces and the characters of the table must agree this closely
# (both ways); the rest is encoding noise such as ligatures. Below it, the page keeps its flowing text.
MIN_TABLE_AGREEMENT = 0.95

_EXTRA_BLANK_LINES = re.compile(r"\n{3,}")
_EMPTY_PAGE = re.compile(r"\f\n+(?=\f)")
_SPACE = re.compile(r"\s+")


@dataclass
class _Chunk:
    text: str
    x: float
    y: float
    table: int | None = None


@dataclass
class _Page:
    text: str
    chunks: list[_Chunk] = field(default_factory=list)
    bands: list[BandLine] = field(default_factory=list)
    box: tuple[float, float, float, float] | None = None  # left, bottom, width, height


def _read_page(page: Any) -> _Page:
    """Text of one pypdf page with the position of every text chunk."""
    chunks: list[_Chunk] = []

    def visitor(text: str, cm: Sequence[float], tm: Sequence[float], *_: object) -> None:
        if text:
            x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
            y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            chunks.append(_Chunk(text, x, y))

    text = page.extract_text(visitor_text=visitor) or ""
    result = _Page(text=text, chunks=chunks)
    try:
        if page.rotation % 360:
            return result  # coordinates are unreliable on rotated pages: no bands, no tables
        box = page.mediabox
        result.box = (float(box.left), float(box.bottom), float(box.width), float(box.height))
    except (AttributeError, TypeError, ValueError):
        return result
    result.bands = band_lines(
        [(c.y, c.x, c.text) for c in chunks if c.text.strip()],
        bottom=result.box[1],
        height=result.box[3],
    )
    return result


def _letters(text: str) -> Counter[str]:
    return Counter(_SPACE.sub("", text).casefold())


def _same_text(replaced: str, cells: Sequence[str]) -> bool:
    """Whether a table holds (nearly) the same characters as the chunks it would replace.

    Order is ignored on purpose: chunks may arrive cell by cell or line by line, and the table's cell
    order comes from the drawn geometry. What must hold is that nothing is lost and nothing is added.
    """
    old, new = _letters(replaced), _letters("".join(cells))
    shared = sum((old & new).values())
    total_old, total_new = sum(old.values()), sum(new.values())
    return bool(total_old and total_new) and (
        shared >= MIN_TABLE_AGREEMENT * total_old and shared >= MIN_TABLE_AGREEMENT * total_new
    )


def _splice_tables(page: _Page, tables: list[PageTable]) -> str:
    """Page text with each table's cell text replaced by the table, when that is provably lossless."""
    if not tables or "".join(c.text for c in page.chunks) != page.text:
        return page.text
    for chunk in page.chunks:
        if chunk.text.strip():
            chunk.table = next(
                (i for i, table in enumerate(tables) if table.contains(chunk.x, chunk.y)), None
            )
    for index, table in enumerate(tables):
        replaced = "".join(c.text for c in page.chunks if c.table == index)
        if not _same_text(replaced, table.cells):
            for chunk in page.chunks:
                if chunk.table == index:
                    chunk.table = None
    pieces: list[str] = []
    placed: set[int] = set()
    for chunk in page.chunks:
        if chunk.table is None:
            pieces.append(chunk.text)
        elif chunk.table not in placed:
            placed.add(chunk.table)
            pieces.append(f"\n\n{tables[chunk.table].markdown}\n\n")
    return "".join(pieces)


def _page_tables(plumber_pdf: Any, index: int, page: _Page) -> list[PageTable]:
    if plumber_pdf is None or page.box is None or index >= MAX_TABLE_PAGES:
        return []
    left, bottom, width, height = page.box
    try:
        plumber_page = plumber_pdf.pages[index]
        if (
            plumber_page.rotation % 360
            or abs(float(plumber_page.width) - width) > 1
            or abs(float(plumber_page.height) - height) > 1
            or abs(left) > 1
        ):
            return []
        try:
            return find_page_tables(plumber_page, mediabox_top=bottom + height)
        finally:
            plumber_page.flush_cache()
    except Exception:  # noqa: BLE001 - tables are an extra; the page text is extracted without them
        logger.warning("PDF table detection failed on page %d; keeping flowing text", index + 1)
        return []


def _open_plumber(data: bytes) -> Any:
    try:
        return pdfplumber.open(BytesIO(data))
    except Exception:  # noqa: BLE001 - see _page_tables
        logger.warning("PDF table detection unavailable; keeping flowing text")
        return None


def _join_pages(page_texts: list[str]) -> str:
    while page_texts and not page_texts[-1]:
        page_texts.pop()
    joined = f"\n\n{PAGE_SEPARATOR}\n\n".join(page_texts).lstrip("\n")
    # An empty page leaves only its two separators: put them on adjacent lines.
    return _EMPTY_PAGE.sub(f"{PAGE_SEPARATOR}\n", joined)


def extract_pdf_text(data: bytes) -> tuple[str, int]:
    """Extract normalized light-Markdown text and the page count from PDF bytes."""
    if not data:
        raise ExtractionError("PDF file is empty")

    try:
        reader = PdfReader(BytesIO(data))
    except PdfReadError as exc:
        raise ExtractionError("Failed to read PDF content") from exc

    if reader.is_encrypted:
        decrypt_result = reader.decrypt("")
        if decrypt_result == 0:
            raise ExtractionError("PDF is encrypted and cannot be decrypted without a password")

    plumber_pdf = _open_plumber(data)
    try:
        pages = [_read_page(page) for page in reader.pages]
        texts = [
            _splice_tables(page, _page_tables(plumber_pdf, i, page)).replace(PAGE_SEPARATOR, " ")
            for i, page in enumerate(pages)
        ]
    finally:
        if plumber_pdf is not None:
            plumber_pdf.close()

    bands = [page.bands for page in pages]
    repeating, page_numbers = furniture_keys(bands)
    lines = remove_furniture([t.split("\n") for t in texts], bands, repeating, page_numbers)
    page_texts = [_EXTRA_BLANK_LINES.sub("\n\n", "\n".join(page)).strip() for page in lines]
    return normalize_extracted_text(_join_pages(page_texts)), len(reader.pages)


class PdfTextExtractor:
    """Extract text and ruled tables from born-digital PDFs using pypdf and pdfplumber."""

    def extract(self, data: bytes, *, mime_type: str, filename: str) -> ExtractionResult:
        if mime_type != PDF_MIME:
            raise ExtractionError(f"PdfTextExtractor does not support MIME type: {mime_type}")

        try:
            text, page_count = extract_pdf_text(data)
        except ExtractionError:
            raise
        except Exception as exc:
            raise classify_unexpected(exc, f"Failed to extract text from PDF: {filename}") from exc

        return ExtractionResult(
            text=text,
            page_count=page_count,
            metadata={
                "extractor": "pdf_text",
                "source_mime_type": mime_type,
                "filename": filename,
            },
        )


def register_pdf_extractor() -> None:
    """Register the PDF text extractor for application/pdf."""
    register_extractor(PDF_MIME, PdfTextExtractor())
