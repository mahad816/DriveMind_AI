"""CSV text extraction (CSV files, and the CSV export used when a Google Sheet is too large to export).

The file is one table in light Markdown, first non-empty row as the header, with the size limits of
``tabular.py`` (a ``Note:`` line says when rows or columns were cut). The delimiter (comma, semicolon,
tab or pipe) is detected from the start of the file. A Google Sheet exported this way holds its
**first sheet only**.
"""

from __future__ import annotations

import csv
import io

from app.connectors.google_drive.constants import CSV_MIME
from app.ingestion.extractors.base import classify_unexpected, ExtractionError, ExtractionResult
from app.ingestion.extractors.light_markdown import Block, join_blocks
from app.ingestion.extractors.plain_text import decode_plain_text_bytes, normalize_extracted_text
from app.ingestion.extractors.registry import register_extractor
from app.ingestion.extractors.tabular import MAX_ROWS_PER_SHEET, build_table

_DELIMITERS = ",;\t|"
_SNIFF_CHARS = 8192


def _dialect(sample: str) -> type[csv.Dialect] | csv.Dialect:
    try:
        return csv.Sniffer().sniff(sample, delimiters=_DELIMITERS)
    except csv.Error:
        return csv.excel


def extract_csv_text(data: bytes) -> str:
    """Light-Markdown table of CSV bytes (empty string when the file holds no values)."""
    text = decode_plain_text_bytes(data).replace("\x00", "")
    if not text.strip():
        return ""
    try:
        rows = csv.reader(io.StringIO(text, newline=""), _dialect(text[:_SNIFF_CHARS]))
        table = build_table(rows, row_limit=MAX_ROWS_PER_SHEET)
    except csv.Error as exc:
        raise ExtractionError("Failed to read CSV content") from exc
    if not table.markdown:
        return ""
    blocks: list[Block] = [("table", table.markdown)]
    if note := table.notes(row_limit=MAX_ROWS_PER_SHEET):
        blocks.append(("paragraph", note))
    return normalize_extracted_text(join_blocks(blocks))


class CsvTextExtractor:
    """Extract a light-Markdown table from CSV bytes."""

    def extract(self, data: bytes, *, mime_type: str, filename: str) -> ExtractionResult:
        if mime_type != CSV_MIME:
            raise ExtractionError(f"CsvTextExtractor does not support MIME type: {mime_type}")

        try:
            text = extract_csv_text(data)
        except ExtractionError:
            raise
        except Exception as exc:
            raise classify_unexpected(exc, f"Failed to extract text from CSV: {filename}") from exc

        return ExtractionResult(
            text=text,
            page_count=None,
            metadata={
                "extractor": "csv_text",
                "source_mime_type": mime_type,
                "filename": filename,
            },
        )


def register_csv_extractor() -> None:
    """Register the CSV text extractor for the CSV MIME type."""
    register_extractor(CSV_MIME, CsvTextExtractor())
