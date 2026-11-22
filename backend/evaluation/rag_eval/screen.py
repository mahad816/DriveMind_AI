"""Unseen-value screen: values in a reply that appear nowhere in what the reply may draw on.

A SCREEN, not a verdict. It is deliberately over-inclusive: a flag means "a human or the grader should
look", never "invented". It shares no code with the claim checker (``app.agents.tool_rag.claim_check``),
so the two can disagree and their disagreement is information.

It looks for four kinds of value in the reply and checks each against the sources (cited chunk texts, the
question, the history, the cited file names):

* numbers (``1,234``, ``3.5``, ``40%``), compared as numbers, so ``1,300`` equals ``1300``;
* dates, parsed to (year, month, day), so ``March 5`` equals ``5 March`` and ``2026-03-05``;
* identifiers: a word that mixes letters and digits (``INC-204``, ``v2``, ``A100``);
* capitalised words that do not start a sentence (names, products, places).

Allowed on purpose: cited file names, list numbers at the start of a line, number words in a *source*
(``five`` there allows ``5`` in the reply), thousand/million scales and simple unit conversions
(``2 hours`` equals ``120 minutes``), and, for a computed case, every number (the answer is derived).

Blind spots (a clean screen proves nothing about these): a wrong value that also occurs elsewhere in a
cited chunk; a true value attached to the wrong subject; invented spelled-out numbers, lower-case names and
non-Latin script; emails and URLs; a unit swapped for another (`22 weeks` for `22 days`: only the digits are compared); a name that opens a sentence; negations and relations ("not", "before", "because"); quantities rounded or approximated
(flagged, so over-inclusive); kilo/mega taken as 1000 only; months and years as units; claims about files that
were retrieved but not cited (their true values are flagged).
"""

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

MONTHS = {
    name: number
    for number, names in enumerate(
        [
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ],
        1,
    )
    for name in names
}
_MONTH = "|".join(sorted(MONTHS, key=len, reverse=True))
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_SLASH = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_DAY_MONTH = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH})\b\.?(?:,?\s+(\d{{4}}))?", re.I
)
_MONTH_DAY = re.compile(
    rf"\b({_MONTH})\b\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(\d{{4}}))?", re.I
)
_MONTH_YEAR = re.compile(rf"\b({_MONTH})\b\.?,?\s+(\d{{4}})\b", re.I)
_LIST_MARKER = re.compile(r"(?m)^[ \t]*(?:[-*•>]\s+)?\d{1,3}[.)]\s+")
_WORD = re.compile(r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*")
_NUMBER = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)(?:\s?(%|[A-Za-z]+))?")
_MARKER = re.compile(r"\[\d+\]")  # the application's citation markers, never claims
_SOURCES_LINE = re.compile(r"(?m)^Sources consulted:.*$")
_CAPITAL = re.compile(r"\b[A-Z][A-Za-z]*\b")

NUMBER_WORDS = {
    word: value
    for value, word in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
        "fifteen sixteen seventeen eighteen nineteen twenty".split()
    )
} | {
    w: v
    for w, v in zip("thirty forty fifty sixty seventy eighty ninety".split(), range(30, 100, 10))
}
SCALES = {"k": 1e3, "thousand": 1e3, "million": 1e6, "bn": 1e9, "billion": 1e9}
# unit -> (dimension, factor to the dimension's base unit)
UNITS: dict[str, tuple[str, float]] = {
    "%": ("pct", 1),
    "percent": ("pct", 1),
    "second": ("time", 1),
    "seconds": ("time", 1),
    "minute": ("time", 60),
    "minutes": ("time", 60),
    "hour": ("time", 3600),
    "hours": ("time", 3600),
    "day": ("time", 86400),
    "days": ("time", 86400),
    "week": ("time", 604800),
    "weeks": ("time", 604800),
    "kb": ("size", 1e3),
    "mb": ("size", 1e6),
    "gb": ("size", 1e9),
    "tb": ("size", 1e12),
}
IGNORED_CAPITALS = {"i", "google", "drive", "drivemind", "file", "files"}  # "i" and product words
DateKey = tuple[int | None, int, int | None]  # (year or None, month, day or None)


@dataclass(frozen=True)
class Values:
    """What a text contains, for use as a source."""

    numbers: frozenset[str]
    magnitudes: frozenset[tuple[str, float]]
    dates: frozenset[DateKey]
    identifiers: frozenset[str]
    words: frozenset[str]  # lower-case alphabetic words: the vocabulary of the sources


@dataclass(frozen=True)
class Mention:
    """One value a reply asserts."""

    kind: str  # "number" | "date" | "id" | "name"
    shown: str
    date: DateKey | None = None
    magnitude: tuple[str, float] | None = None


def _blank(text: str, spans: Iterable[tuple[int, int]]) -> str:
    chars = list(text)
    for start, end in spans:
        chars[start:end] = " " * (end - start)
    return "".join(chars)


def _plain(value: float) -> str:
    return f"{round(value, 6):g}"


def _dates(text: str) -> tuple[set[DateKey], list[tuple[int, int]]]:
    """Dates in several spellings. A longer spelling wins over a shorter one that overlaps it
    ("5 March 2026" is one date, not also "March 2026")."""
    found: set[DateKey] = set()
    spans: list[tuple[int, int]] = []
    claimed: list[tuple[int, int]] = []  # spans taken by earlier, more specific patterns

    def add(year: str | None, month: int, day: str | None, m: re.Match[str]) -> None:
        start, end = m.span()
        if any(start < b and a < end for a, b in claimed):
            return
        y, d = (int(year) if year else None), (int(day) if day else None)
        if 1 <= month <= 12 and (d is None or 1 <= d <= 31):
            found.add((y, month, d))
            spans.append((start, end))

    def finish() -> None:
        claimed[:] = spans

    for m in _ISO.finditer(text):
        add(m[1], int(m[2]), m[3], m)
    finish()
    for m in _SLASH.finditer(text):  # ambiguous: accept both readings
        add(m[3], int(m[1]), m[2], m)
        add(m[3], int(m[2]), m[1], m)
    finish()
    for m in _DAY_MONTH.finditer(text):
        add(m[3], MONTHS[m[2].lower()], m[1], m)
    finish()
    for m in _MONTH_DAY.finditer(text):
        add(m[3], MONTHS[m[1].lower()], m[2], m)
    finish()
    for m in _MONTH_YEAR.finditer(text):
        add(m[2], MONTHS[m[1].lower()], None, m)
    return found, spans


def _quantities(text: str) -> list[tuple[str, tuple[str, float] | None]]:
    """Numbers as ``(plain value, (dimension, magnitude) or None)``; a unit or scale gives a magnitude."""
    out: list[tuple[str, tuple[str, float] | None]] = []
    for m in _NUMBER.finditer(text):
        try:
            value = float(m[1].replace(",", ""))
        except ValueError:
            continue
        unit = (m[2] or "").lower()
        magnitude = None
        if unit in UNITS:
            dimension, factor = UNITS[unit]
            magnitude = (dimension, round(value * factor, 4))
        elif unit in SCALES:
            magnitude = ("num", round(value * SCALES[unit], 4))
        out.append((_plain(value), magnitude))
    return out


def _prepare(text: str) -> tuple[str, set[DateKey], set[str]]:
    """Text with citation markers, list markers, dates and identifiers blanked out, and what was blanked."""
    text = _MARKER.sub(" ", _SOURCES_LINE.sub(" ", unicodedata.normalize("NFKC", text)))
    text = _LIST_MARKER.sub(" ", text)
    dates, spans = _dates(text)
    text = _blank(text, spans)
    ids: dict[str, tuple[int, int]] = {}
    for m in _WORD.finditer(text):
        if m[0][0].isalpha() and any(ch.isdigit() for ch in m[0]):  # INC-204, v2, A100, not 5GB
            ids[m[0].lower()] = m.span()
    return _blank(text, ids.values()), dates, set(ids)


def _capitals(text: str) -> list[str]:
    """Capitalised words that do not begin a sentence, a line or a list item. Markup and quotes are
    looked through, so ``**Zorbax**`` and ``Vendor: Zorbax`` are seen; a name that opens a sentence is not
    (blind spot)."""
    found: list[str] = []
    for m in _CAPITAL.finditer(text):
        prefix = text[: m.start()].rstrip(" \t*_\"'(\u201c\u2018")
        if not prefix or prefix[-1] in ".!?\n#>-•" or re.search(r"\n\s*\d+[.)]$", prefix):
            continue
        word = m[0].lower()
        if word not in IGNORED_CAPITALS and word not in UNITS and word not in SCALES:
            found.append(word)
    return list(dict.fromkeys(found))


def source_values(text: str) -> Values:
    body, dates, ids = _prepare(text)
    quantities = _quantities(body)
    numbers = {plain for plain, _ in quantities}
    magnitudes = {m for _, m in quantities if m} | {("num", round(float(p), 4)) for p in numbers}
    words = frozenset(re.findall(r"[a-z]+", text.lower()))
    for word, value in NUMBER_WORDS.items():  # five in a source allows 5 in a reply
        if word in words:
            numbers.add(_plain(value))
            magnitudes.add(("num", float(value)))
    return Values(
        frozenset(numbers), frozenset(magnitudes), frozenset(dates), frozenset(ids), words
    )


def mentions(reply: str) -> list[Mention]:
    body, dates, ids = _prepare(reply)
    out = [
        Mention("date", "-".join("?" if p is None else str(p) for p in d), date=d)
        for d in sorted(dates, key=str)
    ]
    out += [Mention("id", i) for i in sorted(ids)]
    out += [Mention("number", p, magnitude=m) for p, m in dict(_quantities(body)).items()]
    out += [Mention("name", w) for w in _capitals(body)]
    return out


@dataclass(frozen=True)
class ScreenResult:
    flagged: tuple[str, ...]  # "number:1300", "date:2026-3-5", "id:inc-204", "name:zorbax"

    @property
    def clean(self) -> bool:
        return not self.flagged


def _date_known(d: DateKey, known: frozenset[DateKey]) -> bool:
    year, month, day = d
    return any(
        (year is None or k[0] is None or k[0] == year)
        and k[1] == month
        and (day is None or k[2] is None or k[2] == day)
        for k in known
    )


def _real_date(d: DateKey) -> bool:
    year, month, day = d
    if year is None or day is None:
        return True
    try:
        date(year, month, day)
    except ValueError:
        return False
    return True


def screen(reply: str, sources: Iterable[str], *, computed: bool = False) -> ScreenResult:
    """Flag every value of ``reply`` that no source contains. ``computed`` allows all numbers."""
    known = [source_values(text) for text in sources]
    flagged: list[str] = []
    for item in mentions(reply):
        if item.kind == "date" and item.date is not None:
            if not _real_date(item.date) or not any(_date_known(item.date, v.dates) for v in known):
                flagged.append(f"date:{item.shown}")
        elif item.kind == "id":
            if not any(item.shown in v.identifiers for v in known):
                flagged.append(f"id:{item.shown}")
        elif item.kind == "name":
            if not any(item.shown in v.words for v in known):
                flagged.append(f"name:{item.shown}")
        elif item.kind == "number" and not computed:
            if not any(
                item.shown in v.numbers
                or (item.magnitude is not None and item.magnitude in v.magnitudes)
                for v in known
            ):
                flagged.append(f"number:{item.shown}")
    return ScreenResult(tuple(flagged))
