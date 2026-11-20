"""Running headers, footers and page numbers in PDFs.

These lines repeat on every page ("ACME - ANNUAL REPORT 2025", "Page 3 of 12"). Left in the text they end
up inside every chunk, add the same words to every page's keyword score and bury the real content.

Detection uses where text sits on the page, not where it appears in the extracted text (PDF producers
often draw the header or footer first or last): text in the top or bottom band of the page is a
candidate, and a candidate is *furniture* when

* it is a bare page number ("3", "Page 3", "Page 3 of 12", "- 3 -"), on any document, or
* the same line (digits ignored, so "Page 3" and "Page 4" match) is in the bands of at least 40% of the
  pages of a document of at least 5 pages. The first copy is kept, because it is usually the document
  title and the user may ask for it; the repeats are removed.

Only band lines are ever removed, only as many times as they were seen on that page, so body text that
happens to repeat a header is kept.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

# Share of the page height, measured from the top and from the bottom, that counts as header / footer.
BAND_FRACTION = 0.08
# A repeating line must be in the bands of at least this share of the pages ...
MIN_PAGE_SHARE = 0.4
# ... of a document with at least this many pages (two or three pages prove nothing).
MIN_PAGES_FOR_REPEATS = 5
# Fragments whose baselines differ by less than this many points belong to the same line.
_LINE_TOLERANCE = 2.5
# A header that pypdf splits over several text lines is matched by joining up to this many of them.
_MAX_SPLIT_LINES = 4

_DIGITS = re.compile(r"\d+")
_SPACE = re.compile(r"\s+")
_PAGE_NUMBER_KEYS = re.compile(r"^(?:page)?#(?:of#)?$|^#/#$|^-#-$|^\(#\)$|^\[#\]$")

# (baseline y, x, text) of one piece of text, in PDF coordinates (origin bottom left).
Fragment = tuple[float, float, str]


def line_key(text: str) -> str:
    """Comparison form of a line: digits collapsed to ``#``, no whitespace, case folded."""
    return _SPACE.sub("", _DIGITS.sub("#", text)).casefold()


def is_page_number(key: str) -> bool:
    return bool(_PAGE_NUMBER_KEYS.match(key))


@dataclass(frozen=True)
class BandLine:
    """A line of text found in the header or footer band of one page."""

    text: str
    key: str


def band_lines(fragments: Sequence[Fragment], *, bottom: float, height: float) -> list[BandLine]:
    """The lines whose baseline is in the top or bottom band of a page of this size, top to bottom."""
    if height <= 0:
        return []
    top_edge = bottom + height * (1 - BAND_FRACTION)
    bottom_edge = bottom + height * BAND_FRACTION
    in_band = sorted(
        (f for f in fragments if f[2].strip() and (f[0] >= top_edge or f[0] <= bottom_edge)),
        key=lambda f: (-f[0], f[1]),
    )
    lines: list[list[Fragment]] = []
    for fragment in in_band:
        if lines and abs(lines[-1][0][0] - fragment[0]) <= _LINE_TOLERANCE:
            lines[-1].append(fragment)
        else:
            lines.append([fragment])
    result = []
    for line in lines:
        text = _SPACE.sub(" ", " ".join(f[2] for f in sorted(line, key=lambda f: f[1]))).strip()
        if text:
            result.append(BandLine(text=text, key=line_key(text)))
    return result


def furniture_keys(bands: Sequence[Sequence[BandLine]]) -> tuple[frozenset[str], frozenset[str]]:
    """``(repeating, page_numbers)``: keys of lines that repeat across pages, and of bare page numbers."""
    seen: dict[str, int] = {}
    for page_bands in bands:
        for key in {line.key for line in page_bands}:
            seen[key] = seen.get(key, 0) + 1
    page_numbers = frozenset(key for key in seen if is_page_number(key))
    pages = len(bands)
    if pages < MIN_PAGES_FOR_REPEATS:
        return frozenset(), page_numbers
    needed = math.ceil(MIN_PAGE_SHARE * pages)
    repeating = frozenset(key for key, count in seen.items() if count >= needed)
    return repeating - page_numbers, page_numbers


def remove_furniture(
    page_lines: Sequence[Sequence[str]],
    bands: Sequence[Sequence[BandLine]],
    repeating: frozenset[str],
    page_numbers: frozenset[str],
) -> list[list[str]]:
    """The text lines of every page without the furniture seen in that page's bands."""
    kept_first: set[str] = set()
    cleaned: list[list[str]] = []
    for lines, page_bands in zip(page_lines, bands, strict=True):
        budget: dict[str, int] = {}
        for band in page_bands:
            if band.key in page_numbers:
                budget[band.key] = budget.get(band.key, 0) + 1
            elif band.key in repeating:
                if band.key in kept_first:
                    budget[band.key] = budget.get(band.key, 0) + 1
                else:
                    kept_first.add(band.key)
        result: list[str] = []
        i = 0
        while i < len(lines):
            taken = _matching_run(lines, i, budget)
            if taken:
                i += taken[0]
                budget[taken[1]] -= 1
            else:
                result.append(lines[i])
                i += 1
        cleaned.append(result)
    return cleaned


def _matching_run(
    lines: Sequence[str], start: int, budget: dict[str, int]
) -> tuple[int, str] | None:
    """``(number of lines, key)`` of the furniture entry the lines from ``start`` spell, if any."""
    joined = ""
    for count in range(1, _MAX_SPLIT_LINES + 1):
        if start + count > len(lines):
            break
        joined += line_key(lines[start + count - 1])
        if budget.get(joined, 0) > 0:
            return count, joined
    return None
