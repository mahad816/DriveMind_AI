"""Shared pieces of the "light Markdown" text that the Office readers produce.

Headings are ``#``, list items ``- ``, tables ``| a | b |`` rows with a header row. Blocks are separated
by a blank line (list items by a single newline), which is what the chunker prefers to cut at.
"""

from __future__ import annotations

import re
from typing import Literal

BlockKind = Literal["heading", "list", "paragraph", "table"]
Block = tuple[BlockKind, str]

_SPACES = re.compile(r"\s+")


def one_line(text: str) -> str:
    """Collapse every run of whitespace (including line breaks) to one space."""
    return _SPACES.sub(" ", text).strip()


def table_cell(text: str) -> str:
    """Text of one table cell on a single line, with ``|`` escaped so it cannot split the row."""
    return one_line(text).replace("|", "\\|")


def markdown_table(rows: list[list[str]]) -> str:
    """Rows of cell texts as a Markdown table whose first row is the header.

    Rows are padded to the widest row. A table without any text gives an empty string.
    """
    width = max((len(row) for row in rows), default=0)
    if not width or not any(cell for row in rows for cell in row):
        return ""
    padded = [row + [""] * (width - len(row)) for row in rows]
    lines = ["| " + " | ".join(row) + " |" for row in padded]
    lines.insert(1, "| " + " | ".join(["---"] * width) + " |")
    return "\n".join(lines)


def join_blocks(blocks: list[Block]) -> str:
    """Blocks separated by a blank line, except consecutive list items (one newline)."""
    pieces: list[str] = []
    previous: BlockKind | None = None
    for kind, text in blocks:
        if previous is not None:
            pieces.append("\n" if previous == kind == "list" else "\n\n")
        pieces.append(text)
        previous = kind
    return "".join(pieces)
