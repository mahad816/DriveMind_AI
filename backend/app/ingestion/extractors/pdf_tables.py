"""Ruled tables in PDFs, turned into light-Markdown tables.

pdfplumber finds tables by their drawn lines. Taken as they come, most of what it finds is not a table
(single rows and columns are rule lines, boxes round callouts, a whole page can be one "table"), so a
detected table is used only if it passes the strict checks in :func:`accept_table`. Tables drawn without
lines are not detected: that text stays as flowing text, which is a documented limit, not a bug.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.ingestion.extractors.light_markdown import markdown_table, one_line, table_cell

# A table needs this many rows and columns (after empty ones are dropped) ...
MIN_ROWS = 2
MIN_COLUMNS = 2
# ... at least this share of its cells filled and containing a letter or digit ...
MIN_FILLED_SHARE = 0.6
# ... and is not a layout box: a table larger than this share of the page in both directions is the
# page itself, and cells with this many characters on average are paragraphs inside boxes.
MAX_PAGE_SHARE = 0.9
MAX_AVERAGE_CELL_CHARS = 120


@dataclass(frozen=True)
class PageTable:
    """A table accepted for one page: its box in PDF coordinates and its Markdown."""

    left: float
    bottom: float
    right: float
    top: float
    cells: tuple[str, ...]
    markdown: str

    def contains(self, x: float, y: float, margin: float = 2.0) -> bool:
        return (
            self.left - margin <= x <= self.right + margin
            and self.bottom - margin <= y <= self.top + margin
        )


def clean_rows(raw: list[list[str | None]]) -> list[list[str]]:
    """Cell texts on one line each, with rows and columns that are entirely empty removed."""
    rows = [[one_line(cell or "") for cell in row] for row in raw]
    rows = [row for row in rows if any(row)]
    if not rows:
        return []
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    keep = [c for c in range(width) if any(row[c] for row in rows)]
    return [[row[c] for c in keep] for row in rows]


def accept_table(
    rows: list[list[str]],
    *,
    box_width: float,
    box_height: float,
    page_width: float,
    page_height: float,
) -> bool:
    """Whether cleaned rows are a data table worth showing as one (see the module docstring)."""
    if len(rows) < MIN_ROWS or not rows[0] or len(rows[0]) < MIN_COLUMNS:
        return False
    cells = [cell for row in rows for cell in row]
    substantive = [cell for cell in cells if any(ch.isalnum() for ch in cell)]
    if len(substantive) / len(cells) < MIN_FILLED_SHARE:
        return False
    if box_width > MAX_PAGE_SHARE * page_width and box_height > MAX_PAGE_SHARE * page_height:
        return False
    return sum(len(cell) for cell in substantive) / len(substantive) <= MAX_AVERAGE_CELL_CHARS


def find_page_tables(page: Any, *, mediabox_top: float) -> list[PageTable]:
    """Accepted ruled tables of one pdfplumber page, with boxes in PDF (bottom-left) coordinates.

    ``mediabox_top`` is the page's top edge in PDF coordinates; pdfplumber measures downwards from it.
    """
    result = []
    for table in page.find_tables():
        rows = clean_rows(table.extract())
        left, top, right, bottom = table.bbox
        if not accept_table(
            rows,
            box_width=right - left,
            box_height=bottom - top,
            page_width=float(page.width),
            page_height=float(page.height),
        ):
            continue
        result.append(
            PageTable(
                left=left,
                bottom=mediabox_top - bottom,
                right=right,
                top=mediabox_top - top,
                cells=tuple(cell for row in rows for cell in row if cell),
                markdown=markdown_table([[table_cell(cell) for cell in row] for row in rows]),
            )
        )
    return result
