"""XLSX text extraction (also used for Google Sheets, which are exported as XLSX).

Every visible sheet with content becomes a section of light Markdown::

    ## Sheet: Orders

    | Order | Region | Amount |
    | --- | --- | --- |
    | SO-101 | Portugal | 12000 |

The first non-empty row is the header. Values are what Excel last calculated, not formulas, and numbers
are written without float noise (``0.1 + 0.2`` is ``0.3``) and dates as ISO dates. Size limits are in
``tabular.py``; whenever one cuts something, a ``Note:`` line under the table says so.

Deliberate limits: hidden sheets, charts, pivot tables, comments, images and number formats (a percentage
is written as ``0.15``) are not read; a formula that Excel never calculated (a file written by a script)
has no stored value and is left empty; a merged cell keeps its text in its top-left cell only; encrypted
and legacy ``.xls`` files are not supported.
"""

from __future__ import annotations

from io import BytesIO
from zipfile import BadZipFile, ZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from app.connectors.google_drive.constants import XLSX_MIME
from app.ingestion.extractors.base import ExtractionError, ExtractionResult
from app.ingestion.extractors.light_markdown import Block, join_blocks, one_line
from app.ingestion.extractors.plain_text import normalize_extracted_text
from app.ingestion.extractors.registry import register_extractor
from app.ingestion.extractors.tabular import (
    MAX_ROWS_PER_SHEET,
    MAX_ROWS_PER_WORKBOOK,
    MAX_SHEETS,
    build_table,
)

# A workbook larger than this is refused rather than half-read; the unpacked size guards against a small
# file that expands to gigabytes.
MAX_XLSX_BYTES = 30 * 1024 * 1024
MAX_UNPACKED_BYTES = 300 * 1024 * 1024
# Names of sheets left out for size, listed in the closing note.
_MAX_LISTED_SHEETS = 10


def _check_size(data: bytes) -> None:
    if len(data) > MAX_XLSX_BYTES:
        raise ExtractionError(f"XLSX file is too large (over {MAX_XLSX_BYTES // (1024 * 1024)} MB)")
    try:
        with ZipFile(BytesIO(data)) as archive:
            unpacked = sum(info.file_size for info in archive.infolist())
    except BadZipFile as exc:
        raise ExtractionError("Failed to read XLSX content") from exc
    if unpacked > MAX_UNPACKED_BYTES:
        raise ExtractionError("XLSX file is too large once unpacked")


def extract_xlsx_text(data: bytes) -> tuple[str, int]:
    """Light-Markdown text of every visible sheet in XLSX bytes, and the number of visible sheets."""
    if not data:
        raise ExtractionError("XLSX file is empty")
    _check_size(data)

    try:
        workbook = load_workbook(BytesIO(data), read_only=True, data_only=True)
    except (InvalidFileException, BadZipFile, KeyError, ValueError, OSError) as exc:
        raise ExtractionError("Failed to read XLSX content") from exc

    blocks: list[Block] = []
    left_out: list[str] = []
    rows_left = MAX_ROWS_PER_WORKBOOK
    try:
        sheets = [sheet for sheet in workbook.worksheets if sheet.sheet_state == "visible"]
        for index, sheet in enumerate(sheets):
            if index >= MAX_SHEETS or rows_left <= 0:
                left_out.append(one_line(sheet.title))
                continue
            sheet.reset_dimensions()  # some writers store a wrong used range (A1), which hides the rest
            limit = min(MAX_ROWS_PER_SHEET, rows_left)
            table = build_table(sheet.iter_rows(values_only=True), row_limit=limit)
            if not table.markdown:
                continue
            rows_left -= table.markdown.count("\n") - 1  # lines minus header and separator
            blocks.append(("heading", f"## Sheet: {one_line(sheet.title)}"))
            blocks.append(("table", table.markdown))
            if note := table.notes(row_limit=limit):
                blocks.append(("paragraph", note))
        if left_out:
            listed = ", ".join(left_out[:_MAX_LISTED_SHEETS])
            more = len(left_out) - _MAX_LISTED_SHEETS
            suffix = f" and {more} more" if more > 0 else ""
            blocks.append(
                (
                    "paragraph",
                    f"Note: sheets not indexed because of the size limit: {listed}{suffix}.",
                )
            )
    except (BadZipFile, KeyError, ValueError, OSError) as exc:
        raise ExtractionError("Failed to read XLSX content") from exc
    finally:
        workbook.close()
    return normalize_extracted_text(join_blocks(blocks)), len(sheets)


class XlsxTextExtractor:
    """Extract light-Markdown text (one table per visible sheet) from XLSX files."""

    def extract(self, data: bytes, *, mime_type: str, filename: str) -> ExtractionResult:
        if mime_type != XLSX_MIME:
            raise ExtractionError(f"XlsxTextExtractor does not support MIME type: {mime_type}")

        try:
            text, sheet_count = extract_xlsx_text(data)
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError(f"Failed to extract text from XLSX: {filename}") from exc

        return ExtractionResult(
            text=text,
            page_count=sheet_count,
            metadata={
                "extractor": "xlsx_text",
                "source_mime_type": mime_type,
                "filename": filename,
            },
        )


def register_xlsx_extractor() -> None:
    """Register the XLSX text extractor for the Excel MIME type."""
    register_extractor(XLSX_MIME, XlsxTextExtractor())
