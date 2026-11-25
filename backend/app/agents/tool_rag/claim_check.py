"""Claim-level grounding check for the final answer (KI-002).

Citation validation proves a ``[source_N]`` marker exists and belongs to the user; it never
asks whether the sentence is actually in that source. This module adds that question as one
small JSON call over the evidence the agent really retrieved:

* the answer is split into numbered statements;
* the model returns only the numbers of statements that assert a fact the evidence does not
  contain (or contradicts);
* those statements are removed; if nothing supported remains the caller answers "not found";
* anything uncertain (error, timeout, malformed output, bad numbers) leaves the answer as it
  was and is logged: this layer improves faithfulness, it must not make answering unavailable.

The model never writes user-visible text here, so the check itself cannot add claims.
"""

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from app.routing.intent_frame.evidence import EvidenceSection

from .agent_models import AgentMessage

logger = logging.getLogger(__name__)

CompleteJson = Callable[[str, str], Awaitable[str]]
CLAIM_CHECK_TIMEOUT_SECONDS = 20.0
MAX_EVIDENCE_CHARS = 24_000
MAX_STATEMENTS = 40

SYSTEM_PROMPT = (
    "You check an assistant's answer against the evidence passages it was given. Each passage is "
    "labelled with its file name in square brackets. Statements are labelled [S1], [S2], and so on; "
    "ignore any other numbers. Reply with JSON only: "
    '{"unsupported": ["S3", "S5"]} using those labels, or {"unsupported": []}.\n'
    "Flag a statement when it asserts a specific fact (a number, date, name, quantity, rule) or an "
    "event, decision, cause, relationship or conclusion that is missing from the evidence or "
    "contradicted by it. Check each material assertion in a statement on its own: a detail that is "
    "in the evidence (a name, a date, a document title) does not make an unsupported event, "
    "decision, cause or conclusion in the same statement supported. If any material assertion is "
    "unsupported, flag the statement, even when the rest of it is supported.\n"
    'Naming a document, file, section or author as the place a fact comes from ("according to the '
    'X", "the X says") is itself a material assertion: it is supported only when the passages '
    "labelled with that document state the fact. A value found only in a different document does not "
    "support it. The file name in a label only tells you where a passage came from; it is never "
    "evidence that a statement is true.\n"
    "What the passages lack is judged differently from what is true. A statement that something is "
    "not stated, not specified or not found in the documents (also with a note on what the retrieved "
    "passages cover and omit) is supported when the evidence does not state it; flag it only if the "
    'evidence does state it. A claim that the thing does not exist or never happened ("there is no '
    'X", "it has never had X") is a claim about the world, not about the passages: flag it unless '
    "the evidence says so.\n"
    "Do NOT flag a statement for any of these: a paraphrase or summary of the evidence; a "
    "reasonable inference from it that adds no new event, decision or cause; a caveat, a heading, or "
    "a lead-in that only introduces what follows (a lead-in that names a source, document, policy or "
    "requirement as the origin of what follows is a claim: check it); simple arithmetic on numbers "
    "in the evidence; a statement that something is not in the documents, or that the documents do "
    "not establish it; a claim that is qualified the way the evidence qualifies it (a draft described "
    "as a draft, a scheduled decision described as scheduled); ordinary conversational wording or an "
    "explanation of what the evidence does say; an offer to help; wording that is more or less "
    "specific than the evidence but not contradicted by it.\n"
    "Judge meaning, not word overlap, and ignore citation markers like [1] or [source_1]. "
    "When in doubt about wording or level of detail, the statement is supported; but never when it "
    "asserts something that happened, was decided or caused something that the evidence does not "
    "state.\n"
    "The user's own messages are given too. Numbers the user wrote are not claims, and arithmetic "
    "on them together with numbers from the evidence is fine. Anything else the user's question "
    "assumes (that an event happened, a decision was made, one thing caused another) is not "
    "evidence: if the answer repeats or builds on such an assumption and the evidence does not "
    "establish it, flag the statement.\n"
    "After the statements there may be a list headed 'Numbers written in a statement that appear "
    "nowhere in the evidence or the user's messages'. Check each one carefully: flag that statement "
    "unless the number is the plain result of arithmetic or a date calculation on numbers or dates "
    "that are in the evidence or the user's messages (a sum, difference, count, or a date a stated "
    "number of days away), or a list number."
)

# A sentence ends at . ! or ? plus any citation markers ("[1]", "[source_2]") that follow it, when the
# next sentence starts with a capital, digit or bullet. Markers stay with the sentence they cite.
_BOUNDARY = re.compile(r"[.!?](?:\s*\[[^\]\n]{1,30}\])*(?=\s+[A-Z0-9*\"'(])")


def sentences(piece: str) -> list[str]:
    parts, start = [], 0
    for match in _BOUNDARY.finditer(piece):
        parts.append(piece[start : match.end()].strip())
        start = match.end()
    parts.append(piece[start:].strip())
    return [p for p in parts if p]


_COLON_BEFORE_LIST = re.compile(
    r"(?<=[:;])\s+(?=\d{1,2}[.)]\s)"
)  # "...the following: 1. Open" -> new unit
_TRAILING_MARKER = re.compile(
    r"(?<=[:.;!?)\]])\s+\d{1,2}[.)]$"
)  # a list number glued to the end of a unit
_LIST_MARKER = re.compile(
    r"^(?:[-*]\s*)?\(?\d{1,2}[.)]$"
)  # a bare "1." left over from a numbered list


# A line that is only protocol or numeric citation markers ("[source_6]", "- [2]", "[1] [2]") cites; it asserts
# nothing. Any other bracketed text ("[TBD]", "- [ ]") is not a citation.
_CITATION_ONLY = re.compile(
    r"^[\s\-*+\u2022>]*(?:\[(?:(?:source|evidence)_[^\]\n]{1,20}|\d{1,3})\][\s,;.]*)+$"
)


def is_citation_only(text: str) -> bool:
    return bool(_CITATION_ONLY.match(text))


def _line_pieces(line: str) -> list[list[str]]:
    """The statements of one physical line, grouped by the piece they came from.

    A colon before a numbered item ("...the following: 1. Open") starts a new piece. This is the
    single place where statement boundaries are decided: extraction, checking and removal all use it.
    """
    if is_citation_only(line):
        return []
    stripped = _COLON_BEFORE_LIST.sub("\n", line.strip())
    return [units for piece in stripped.splitlines() if (units := _merge_markers(sentences(piece)))]


def split_statements(text: str) -> list[str]:
    """Split an answer into statements: one per non-empty line, long lines also per sentence."""
    return [unit for line in text.splitlines() for piece in _line_pieces(line) for unit in piece]


def _merge_markers(parts: list[str]) -> list[str]:
    """Glue a bare list number ("1.") onto the text it introduces; it is not a statement."""
    merged: list[str] = []
    carry = ""
    for part in parts:
        if _LIST_MARKER.match(part):
            carry = (carry + " " + part).strip()
            continue
        merged.append((carry + " " + part).strip() if carry else part)
        carry = ""
    if carry:
        merged.append(carry) if not merged else merged.__setitem__(-1, merged[-1] + " " + carry)
    return merged


_MARKER = re.compile(r"\[[^\]\n]{1,30}\]")
_LEADING_LIST_NUMBER = re.compile(r"^\s*(?:[-*]\s*)?\(?\d{1,2}[.)]\s+")
_NUMBER = re.compile(r"\d[\d,.]*\d|\d")


def numbers_missing(statement: str, evidence: str) -> list[str]:
    """Numbers written in ``statement`` that appear nowhere in ``evidence`` (no model involved).
    Pass the user's question together with the evidence: numbers the user typed are given.

    Whole-number match, thousands separators ignored: 5 does not match 15 or 5.5. Citation markers
    and a leading list number are not part of the claim. Only a hint: an honest calculation also
    produces numbers the text does not contain, so the model decides what to do with the list.
    """
    text = _LEADING_LIST_NUMBER.sub("", _MARKER.sub(" ", statement))
    haystack = re.sub(r"(?<=\d),(?=\d{3}\b)", "", evidence)
    missing: list[str] = []
    for token in _NUMBER.findall(text):
        plain = token.replace(",", "").rstrip(".")
        if (
            plain
            and plain not in missing
            and not re.search(r"(?<![\d.])" + re.escape(plain) + r"(?!\d|\.\d)", haystack)
        ):
            missing.append(plain)
    return missing


_LABEL_MAX_WORDS = 2


def is_framing(statement: str) -> bool:
    """A short label ("Key points:") or word-only fragment ("Biddle.") carries no claim.

    A colon alone does not make a statement framing: "According to the handbook:" asserts where the
    following facts come from. Only a label of at most two words may end with a colon unchecked. A
    short fragment that contains a digit ("17 February 2026.") is exactly what a short answer looks like,
    so it is checked like any other statement.
    """
    text = statement.strip().strip("*_ ")
    if text.endswith(":"):  # a bullet or list number before a label is not one of its words
        return len(text[len(_leading_prefix(text)) :].split()) <= _LABEL_MAX_WORDS
    return len(text.split()) < 4 and not re.search(r"\d", text)


# A label is one line "[file name]" at the start of each passage (see ``section_label``). The name may itself
# contain brackets, so the line is matched whole.
_SECTION_LABEL = re.compile(r"(?:\A|(?<=\n\n))\[[^\n]*\]\n")


def section_label(filename: str) -> str:
    """The line that heads a passage in the evidence text: provenance for the checker, never evidence."""
    return "[" + re.sub(r"[\r\n]+", " ", filename) + "]"


def evidence_body(evidence: str) -> str:
    """The passages' text without the "[file name]" line that heads each one.

    ``evidence_text`` labels every passage with its file name so the checker can judge "the handbook says ..." and
    citations can be mapped. A label is provenance, not evidence: no deterministic check may treat a word or a number
    in a file name as support. The checker still receives the labelled text.
    """
    return _SECTION_LABEL.sub("", evidence)


def build_user_message(statements: Sequence[str], evidence: str, question: str = "") -> str:
    numbered = "\n".join(f"[S{i}] {s}" for i, s in enumerate(statements, 1))
    given = f"{evidence_body(evidence[:MAX_EVIDENCE_CHARS])}\n{question}"
    absent = [
        f"[S{i}] {', '.join(missing)}"
        for i, s in enumerate(statements, 1)
        if (missing := numbers_missing(s, given))
    ]
    hint = (
        "\n\nNumbers written in a statement that appear nowhere in the evidence or the user's "
        "messages:\n" + "\n".join(absent)
        if absent
        else ""
    )
    asked = f"\n\nUser's messages:\n{question}" if question.strip() else ""
    return (
        f"Evidence passages:\n{evidence[:MAX_EVIDENCE_CHARS]}{asked}"
        f"\n\nAnswer statements:\n{numbered}{hint}"
    )


def parse_unsupported(raw: str, count: int) -> frozenset[int] | None:
    """Zero-based indexes of flagged statements, or None if the reply cannot be trusted."""
    try:
        value = json.loads(raw).get("unsupported")
    except Exception:
        return None
    if not isinstance(value, list):
        return None
    indexes: set[int] = set()
    for item in value:
        match = re.fullmatch(r"S?(\d+)", item.strip(), re.I) if isinstance(item, str) else None
        number = (
            int(match.group(1))
            if match
            else item
            if isinstance(item, int) and not isinstance(item, bool)
            else 0
        )
        if not 1 <= number <= count:
            return None
        indexes.add(number - 1)
    return frozenset(indexes)


async def find_unsupported(
    complete_json: CompleteJson, statements: Sequence[str], evidence: str, question: str = ""
) -> frozenset[int] | None:
    """Ask the model which statements are unsupported; None means the check could not be done."""
    if not statements or not evidence.strip() or len(statements) > MAX_STATEMENTS:
        return None
    try:
        async with asyncio.timeout(CLAIM_CHECK_TIMEOUT_SECONDS):
            raw = await complete_json(
                SYSTEM_PROMPT, build_user_message(statements, evidence, question)
            )
    except Exception:
        logger.info("rag_execution path=claim_check outcome=CHECK_ERROR")
        return None
    flagged = parse_unsupported(raw, len(statements))
    if flagged is None:
        logger.info("rag_execution path=claim_check outcome=BAD_REPLY")
        return None
    return frozenset(i for i in flagged if not is_framing(statements[i]))


@dataclass(frozen=True)
class ClaimCheckResult:
    text: str
    removed: int  # statements dropped as unsupported
    checked: bool  # False when the check could not run (answer left untouched)

    @property
    def nothing_left(self) -> bool:
        return self.removed > 0 and not self.text.strip()


async def enforce_claims(
    complete_json: CompleteJson, answer: str, evidence: str, question: str = ""
) -> ClaimCheckResult:
    """Return ``answer`` without the statements the evidence does not support."""
    if _is_only_markers(answer):
        return ClaimCheckResult(answer, 0, False)
    lines = answer.splitlines()
    statements = split_statements(answer)
    flagged = await find_unsupported(complete_json, statements, evidence, question)
    if flagged is None:
        return ClaimCheckResult(answer, 0, False)
    if not flagged:
        return ClaimCheckResult(answer, 0, True)
    new_lines: list[str | None] = []  # per original line: its text after removal, None if gone
    inline_orphans: set[int] = (
        set()
    )  # lines whose lead-in lost the numbered list that followed it on the line
    removed = 0
    index = 0  # position of the next statement, in the numbering the checker was shown
    for line in lines:
        pieces = _line_pieces(line)
        count = sum(len(piece) for piece in pieces)
        hits = {i - index for i in flagged if index <= i < index + count}
        if not hits:
            new_lines.append(line)
        else:
            new_lines.append(_rebuild_line(line, pieces, hits) or None)
            removed += len(hits)
            if _inline_orphan(pieces, hits):
                inline_orphans.add(len(new_lines) - 1)
        index += count
    words = _content_words(evidence_body(evidence[:MAX_EVIDENCE_CHARS]))
    tidied, dropped = _tidy_orphan_lead_ins(lines, new_lines, inline_orphans, words)
    removed += dropped
    _drop_orphan_citation_lines(lines, new_lines, tidied, words)
    text = re.sub(
        r"\n{3,}", "\n\n", "\n".join(line for line in new_lines if line is not None)
    ).strip()
    if _is_only_markers(text) or all(_is_lead_in(u, words) for u in split_statements(text)):
        # Nothing but headings, lead-ins and citation lines is left: no answer. The lead-ins that go with it
        # are statements really dropped, so the count includes them (it always equals what went).
        text = ""
        removed = len(split_statements(answer))
    logger.info("rag_execution path=claim_check outcome=REMOVED count=%d", removed)
    return ClaimCheckResult(text, removed, True)


_LIST_PREFIX = re.compile(r"^(?:>[ \t]*)*(?:[-*+\u2022][ \t]+)?(?:\(?\d{1,2}[.)][ \t]+)?")


def _leading_prefix(statement: str) -> str:
    """The bullet and/or list number a statement starts with ("" if none)."""
    match = _LIST_PREFIX.match(statement)
    return match.group(0) if match else ""


def _rebuild_line(line: str, pieces: list[list[str]], hits: set[int]) -> str:
    """The line without the statements at ``hits`` (line-relative indexes); "" if none survive.

    Statements keep their own text, so a citation marker stays with the sentence it follows. When
    the first statement of a piece goes, its bullet or list number moves to the next survivor.
    """
    indent = line[: len(line) - len(line.lstrip())]
    out: list[str] = []
    offset = 0
    for piece in pieces:
        kept = [u for n, u in enumerate(piece) if offset + n not in hits]
        if kept and offset in hits:  # the piece's first statement went: keep its bullet or number
            lead = _leading_prefix(piece[0])
            if lead and not _leading_prefix(kept[0]):
                kept[0] = lead + kept[0]
        offset += len(piece)
        if kept:
            out.append(" ".join(kept))
    return indent + ("\n" + indent).join(out) if out else ""


_CONTENT_WORD = re.compile(r"[a-z]{5,}|\d+")  # words of five letters or more, and numbers
_TRAILING_MARKERS = re.compile(r"(?:\s*\[[^\]\n]{1,30}\])+$")


def _content_words(text: str) -> set[str]:
    return set(_CONTENT_WORD.findall(text.lower()))


def _is_grounded(text: str, evidence_words: set[str]) -> bool:
    """Most of the statement's longer words and numbers are in the evidence the checker was given."""
    words = _CONTENT_WORD.findall(text.lower())
    hits = sum(word in evidence_words for word in words)
    return hits >= 2 and hits * 2 >= len(words)


def _lead_in_parts(unit: str) -> tuple[str, str]:
    """The unit without its trailing citation markers, and those markers (with their leading space)."""
    text = unit.strip()
    body = _TRAILING_MARKERS.sub("", text).rstrip()
    return body, text[len(body) :]


def _introduces(unit: str) -> bool:
    """Ends with the colon or semicolon that introduces a list (markers and emphasis aside), or is a heading."""
    body = _lead_in_parts(unit)[0]
    return _heading_level(body) > 0 or body.rstrip("*_ ").endswith((":", ";"))


def _is_structural_clause(plain: str, evidence_words: set[str]) -> bool:
    """A short label, or a clause the passages' text does not bear out: it introduces and asserts nothing."""
    return len(plain.split()) <= _LABEL_MAX_WORDS or not _is_grounded(plain, evidence_words)


def _is_lead_in(unit: str, evidence_words: set[str]) -> bool:
    """A statement that only introduces what follows (a *structural* lead-in).

    A heading, a label of at most two words ending in a colon, or a colon-ending clause most of whose longer
    words are not in the evidence ("Here is what I found:"). A colon-ending clause the documents bear out
    ("Refunds take 30 days for these items:") is a real statement and is not a lead-in in this sense.
    """
    body = _lead_in_parts(unit)[0]
    plain = body[len(_leading_prefix(body)) :].strip().rstrip("*_ ")
    if _heading_level(body) or _heading_level(plain):
        return True
    return plain.endswith(":") and _is_structural_clause(plain, evidence_words)


_LIST_ITEM = re.compile(r"^[ \t]*(?:>[ \t]*)*(?:[-*+\u2022]|\(?\d{1,2}[.)])[ \t]+")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


# ATX heading: one to six "#" and then a space (or nothing). "#1 priority" and "#hashtag" are text, not headings.
_HEADING = re.compile(r"[ \t]*(#{1,6})(?:[ \t]+\S|[ \t]*$)")


def _heading_level(text: str) -> int:
    """1 to 6 for a markdown heading, 0 for anything else. The only place a heading is recognised."""
    match = _HEADING.match(text)
    return len(match.group(1)) if match else 0


def _items_of(lines: list[str], i: int) -> list[int]:
    """The lines that line ``i`` introduces, read as markdown structure.

    A heading owns its section: every line up to the next heading of the same or a higher level. Any other lead-in
    owns deeper-indented lines and, when it is not itself a list item, the list items at its own indent; with no
    list at all, a colon or semicolon lead-in owns the plain paragraph after it (``_next_paragraph``). Blank lines
    do not end either run (a blank line before a list, or between the items of a loose list, is ordinary markdown);
    the run ends at the first non-blank line that does not belong, so a plain paragraph after a list is never swept in.
    Citation-only lines are skipped.
    """
    level = _heading_level(lines[i])
    base, parent_is_item = _indent(lines[i]), bool(_LIST_ITEM.match(lines[i]))
    items: list[int] = []
    for j in range(i + 1, len(lines)):
        line = lines[j]
        if not line.strip() or is_citation_only(line):
            continue
        if level:
            if 0 < _heading_level(line) <= level:
                break
        elif not (
            _indent(line) > base
            or (_indent(line) == base and not parent_is_item and bool(_LIST_ITEM.match(line)))
        ):
            break
        items.append(j)
    if not items and not level and _introduces(lines[i]):
        return _next_paragraph(lines, i)
    return items


def _next_paragraph(lines: list[str], i: int) -> list[int]:
    """The plain paragraph a colon or semicolon lead-in introduces when it has no list: the next run of text lines
    (blank lines and citation-only lines before it are skipped; it ends at a blank line). A heading is never part
    of it: the lead-in then introduces nothing."""
    j = i + 1
    while j < len(lines) and (not lines[j].strip() or is_citation_only(lines[j])):
        j += 1
    run: list[int] = []
    while j < len(lines) and lines[j].strip() and not _heading_level(lines[j]):
        if not is_citation_only(lines[j]):
            run.append(j)
        j += 1
    return run


def _inline_orphan(pieces: list[list[str]], hits: set[int]) -> bool:
    """True when statements after the last surviving one on a line were all removed: what a lead-in introduced on
    the same line (a sentence, or a numbered list after a colon, see ``_COLON_BEFORE_LIST``) is gone."""
    count = sum(len(piece) for piece in pieces)
    kept = [k for k in range(count) if k not in hits]
    return bool(kept) and kept[-1] < count - 1


def _tidy_lead_in(unit: str, evidence_words: set[str]) -> str | None:
    """The lead-in as a closed sentence (colon or semicolon to full stop, citation markers kept), or None when it
    is structural (a heading, a short label, or a clause the passages' text does not bear out)."""
    body, markers = _lead_in_parts(unit)
    plain = body[len(_leading_prefix(body)) :].strip().rstrip("*_ ")
    if (
        _heading_level(body)
        or _heading_level(plain)
        or _is_structural_clause(plain, evidence_words)
    ):
        return None
    return re.sub(r"[:;]([*_\s]*)$", r".\1", body) + markers


def _tidy_orphan_lead_ins(
    lines: list[str],
    new_lines: list[str | None],
    inline_orphans: set[int],
    evidence_words: set[str],
) -> tuple[set[int], int]:
    """Close the colon that removal left dangling.

    When every line a lead-in introduced is gone, a meaningful lead-in becomes a sentence and a structural one
    (heading, short label, boilerplate) is dropped. Nothing else is touched: a lead-in that never had items, or
    still has one, keeps its colon. Returns the lines left holding only such a converted lead-in and the number of
    unflagged statements dropped. Children are tidied before their parents.
    """
    only_lead_in: set[int] = set()
    dropped = 0
    for i in reversed(range(len(lines))):
        current = new_lines[i]
        if current is None:
            continue
        items = _items_of(lines, i)
        gone = bool(items) and all(new_lines[j] is None for j in items)
        if not (gone or (i in inline_orphans and not items)):
            continue
        *head, last = current.split("\n")
        units = [u for piece in _line_pieces(last) for u in piece]
        stripped = last.rstrip()
        if not units or not stripped.endswith(units[-1]):
            continue
        unit = units[-1]
        if not _introduces(unit):
            continue
        prefix = stripped[: len(stripped) - len(unit)]
        tidied = _tidy_lead_in(unit, evidence_words)
        if tidied is None:
            dropped += 1
            rest = prefix.rstrip()
        else:
            rest = prefix + tidied
        kept = head + ([rest] if rest.strip() else [])
        new_lines[i] = "\n".join(kept) or None
        if (
            tidied is not None
            and new_lines[i] is not None
            and len(split_statements(new_lines[i] or "")) == 1
        ):
            only_lead_in.add(i)
    return only_lead_in, dropped


def _content_run(lines: list[str], start: int, step: int, skip_blank: bool) -> list[int]:
    """The run of text lines found from ``start`` going up (-1) or down (+1); blank lines are skipped first
    only when ``skip_blank``, and never inside the run."""
    j = start
    while 0 <= j < len(lines) and (
        is_citation_only(lines[j]) or (skip_blank and not lines[j].strip())
    ):
        j += step
    run = []
    while 0 <= j < len(lines) and lines[j].strip() and not is_citation_only(lines[j]):
        run.append(j)
        j += step
    return run


def _drop_orphan_citation_lines(
    lines: list[str],
    new_lines: list[str | None],
    only_lead_in: set[int],
    evidence_words: set[str],
) -> None:
    """Drop a citation-only line whose own text was all removed; keep it while any of that text survives.

    A citation line belongs to the run of text lines above it (the usual style: markers after the text) or,
    when the answer starts with a citation line (markers before their text), to the run below it. Blank lines
    never join two paragraphs. A structural lead-in, or a line left holding only a lead-in that was closed
    because its items went, does not count as surviving support: the marker line cited the items. A citation line
    with no text to belong to is left alone.
    """
    first = next((line for line in lines if line.strip()), "")
    before_text = is_citation_only(first)
    for i, line in enumerate(lines):
        if new_lines[i] is None or not is_citation_only(line):
            continue
        below, above = _content_run(lines, i + 1, 1, True), _content_run(lines, i - 1, -1, True)
        anchors = (below or above) if before_text else (above or below)
        if not anchors:
            continue
        alive = [
            k
            for k in anchors
            if new_lines[k] is not None
            and k not in only_lead_in
            and any(
                not _is_lead_in(u, evidence_words) for u in split_statements(new_lines[k] or "")
            )
        ]
        if not alive:
            new_lines[i] = None


def _is_only_markers(text: str) -> bool:
    return not re.sub(r"\[[^\]]*\]|[\s\-*#>.:;,]", "", text)


def clean_unit(text: str) -> str:
    """Drop a list number that a sentence splitter left glued to the end of a unit ("... TV. 3.")."""
    return _TRAILING_MARKER.sub("", text.strip())


ClaimChecker = Callable[
    [str, str, str], Awaitable[ClaimCheckResult]
]  # (answer, evidence, question)


def evidence_text(sections: Sequence[EvidenceSection]) -> str:
    """The text the agent actually retrieved this turn, labelled by file name."""
    return "\n\n".join(
        f"{section_label(s.members[0].filename)}\n{s.combined_text}" for s in sections
    )


def user_text(messages: Sequence[AgentMessage]) -> str:
    """What the user wrote in this conversation: its numbers are given, not claims to verify."""
    return "\n".join(m.text for m in messages if m.role == "USER" and m.text)
