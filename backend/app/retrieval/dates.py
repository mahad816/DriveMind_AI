"""Calendar-date equivalence for bounded PostgreSQL content matching."""

import calendar
import re
from datetime import date

_MONTHS = {
    name.lower(): number
    for number in range(1, 13)
    for name in (calendar.month_name[number], calendar.month_abbr[number])
}
_MONTH_NAMES = "|".join(sorted(_MONTHS, key=len, reverse=True))


def date_patterns(question: str) -> list[str]:
    """Match ISO and named calendar dates; preserve a year when explicitly supplied."""
    values: set[tuple[int, int, int | None]] = set()
    for match in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", question):
        values.add((int(match[2]), int(match[3]), int(match[1])))
    for match in re.finditer(
        rf"\b({_MONTH_NAMES})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b", question, re.I
    ):
        values.add((_MONTHS[match[1].lower()], int(match[2]), int(match[3]) if match[3] else None))
    for match in re.finditer(
        rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_NAMES})\.?(?:\s+(\d{{4}}))?\b", question, re.I
    ):
        values.add((_MONTHS[match[2].lower()], int(match[1]), int(match[3]) if match[3] else None))
    patterns: list[str] = []
    for month, day, year in sorted(values, key=lambda v: (v[0], v[1], v[2] or 0)):
        try:
            date(year or 2000, month, day)
        except ValueError:
            continue
        month_name = f"(?:{calendar.month_name[month]}|{calendar.month_abbr[month]}[.]?)"
        year_suffix = f",?[[:space:]]+{year}" if year else ""
        iso_year = str(year) if year else "[0-9]{4}"
        patterns.append(
            f"(^|[^[:alnum:]])(?:{iso_year}-0?{month}-0?{day}"
            f"|{month_name}[[:space:]]+0?{day}(?:st|nd|rd|th)?{year_suffix}"
            f"|0?{day}(?:st|nd|rd|th)?[[:space:]]+{month_name}{year_suffix})([^[:alnum:]]|$)"
        )
    return patterns


def ordered_date_context(question: str, source_texts: list[str]) -> str:
    """Structure explicit dated lines for ordering; never infer years or event links.

    Source membership remains a generation task: this is chronological evidence,
    not a maximum across every unrelated milestone in the retrieved passages.
    """
    if not (
        re.search(r"\b(?:latest|earliest|first|last|order\w*|before|after)\b", question, re.I)
        and re.search(r"\b(?:date\w*|deadline\w*|schedul\w*|chronolog\w*)\b", question, re.I)
    ):
        return ""
    pattern = re.compile(
        rf"\b(?:(?P<iso>\d{{4}}-\d{{2}}-\d{{2}})"
        rf"|(?P<month>{_MONTH_NAMES})\.?\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?[,]?\s+(?P<year>\d{{4}})"
        rf"|(?P<reverse_day>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<reverse_month>{_MONTH_NAMES})\.?\s+(?P<reverse_year>\d{{4}}))\b",
        re.I,
    )
    facts: set[tuple[date, str, int]] = set()
    for source_index, text in enumerate(source_texts, start=1):
        for line in text.splitlines():
            line = line.strip()
            if not line or re.match(r"(?:updated|modified|created)\s*:", line, re.I):
                continue
            matches = list(pattern.finditer(line))
            # Multiple dates in a line need relationship interpretation; leave it to the original source.
            if len(matches) != 1 or len(line) > 500:
                continue
            match = matches[0]
            try:
                if match["iso"]:
                    value = date.fromisoformat(match["iso"])
                else:
                    value = date(
                        int(match["year"] or match["reverse_year"]),
                        _MONTHS[(match["month"] or match["reverse_month"]).lower()],
                        int(match["day"] or match["reverse_day"]),
                    )
            except ValueError:
                continue
            facts.add((value, line, source_index))
    if not facts or len(facts) > 24:
        return ""
    rows = [f"- {value.isoformat()} | {line} [{index}]" for value, line, index in sorted(facts)]
    return (
        "Dated source facts, sorted earliest to latest (not the answer):\n"
        "Filter to ALL members of the requested set first; exclude unrelated milestones. "
        "A scheduled task belongs in that set even without the word 'deadline'. "
        "For latest/earliest, use the last/first matching row, not the last-mentioned activity. "
        "Missing years or ambiguous multi-date lines are not included; consult original passages.\n"
        + "\n".join(rows)
    )
