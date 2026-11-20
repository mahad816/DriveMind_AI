"""Rows of a spreadsheet or CSV file as a light-Markdown table, with explicit size limits.

A sheet can hold a million rows, but a question is answered from a few of them, and every row becomes
text that is chunked, embedded and searched. So the reader keeps a decent amount and *says* when it
stopped (a ``Note:`` line under the table), so the assistant can tell the user that it only saw part of
a sheet instead of presenting a partial table as the whole.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from app.ingestion.extractors.light_markdown import markdown_table, table_cell

# Per sheet: header row plus this many data rows, and this many columns.
MAX_ROWS_PER_SHEET = 1000
MAX_COLUMNS = 50
# Per workbook: data rows over all sheets, and sheets.
MAX_ROWS_PER_WORKBOOK = 5000
MAX_SHEETS = 25
# Rows read from a sheet (blank ones included) before giving up: formatted-but-empty ranges can be huge.
MAX_SCANNED_ROWS = 50_000
# One cell: longer text (an exported note, a pasted document) is cut.
MAX_CELL_CHARS = 500


def format_value(value: Any) -> str:
    """Text of one cell value: no float noise, dates as ISO, booleans as TRUE / FALSE."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return str(value)
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        return format(value, ".15g")
    if isinstance(value, datetime):
        if value.time() == time(0):
            return value.date().isoformat()
        return value.isoformat(sep=" ", timespec="seconds" if value.second else "minutes")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat(timespec="seconds" if value.second else "minutes")
    if isinstance(value, timedelta):
        return str(value)
    text = table_cell(str(value))
    return text if len(text) <= MAX_CELL_CHARS else text[: MAX_CELL_CHARS - 1].rstrip() + "…"


@dataclass(frozen=True)
class TableText:
    """Markdown of one table and what had to be left out of it."""

    markdown: str
    rows_cut: bool = False
    columns_cut: bool = False
    scan_cut: bool = False

    def notes(self, *, row_limit: int) -> str:
        parts = []
        if self.rows_cut or self.scan_cut:
            parts.append(f"only the first {row_limit} rows are indexed")
        if self.columns_cut:
            parts.append(f"only the first {MAX_COLUMNS} columns are indexed")
        return f"Note: {' and '.join(parts)}." if parts else ""


def build_table(rows: Iterable[Iterable[Any]], *, row_limit: int) -> TableText:
    """Markdown table of the rows: first non-empty row is the header, then up to ``row_limit`` rows.

    Blank rows and columns that are blank in every kept row are dropped; a row longer than
    ``MAX_COLUMNS`` is cut. ``row_limit`` counts data rows (the header is extra).
    """
    kept: list[list[str]] = []
    rows_cut = columns_cut = scan_cut = False
    for scanned, row in enumerate(rows):
        if scanned >= MAX_SCANNED_ROWS:
            scan_cut = True
            break
        cells = [format_value(value) for value in row]
        if len(cells) > MAX_COLUMNS:
            if any(cells[MAX_COLUMNS:]):
                columns_cut = True
            cells = cells[:MAX_COLUMNS]
        if not any(cells):
            continue
        if len(kept) > row_limit:  # header + row_limit rows are kept; this one is one too many
            rows_cut = True
            break
        kept.append(cells)
    if not kept:
        return TableText("")
    width = max(len(row) for row in kept)
    kept = [row + [""] * (width - len(row)) for row in kept]
    used = [c for c in range(width) if any(row[c] for row in kept)]
    return TableText(
        markdown_table([[row[c] for c in used] for row in kept]),
        rows_cut=rows_cut,
        columns_cut=columns_cut,
        scan_cut=scan_cut,
    )
