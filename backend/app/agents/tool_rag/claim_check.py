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
    "You check an assistant's answer against the evidence passages it was given. Statements are "
    "labelled [S1], [S2], and so on; ignore any other numbers. Reply with JSON only: "
    '{"unsupported": ["S3", "S5"]} using those labels, or {"unsupported": []}.\n'
    "Flag a statement when it asserts a specific fact (a number, date, name, quantity, rule) or an "
    "event, decision, cause, relationship or conclusion that is missing from the evidence or "
    "contradicted by it. Check each material assertion in a statement on its own: a detail that is "
    "in the evidence (a name, a date, a document title) does not make an unsupported event, "
    "decision, cause or conclusion in the same statement supported. If any material assertion is "
    "unsupported, flag the statement, even when the rest of it is supported.\n"
    "Do NOT flag a statement for any of these: a paraphrase or summary of the evidence; a "
    "reasonable inference from it that adds no new event, decision or cause; framing, a caveat or a "
    "heading; simple arithmetic on numbers in the evidence; a statement that something is not in "
    "the documents, or that the documents do not establish it; a claim that is qualified the way "
    "the evidence qualifies it (a draft described as a draft, a scheduled decision described as "
    "scheduled); ordinary conversational wording or an explanation of what the evidence does say; "
    "an offer to help; wording that is more or less specific than the evidence but not "
    "contradicted by it.\n"
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


def _line_pieces(line: str) -> list[list[str]]:
    """The statements of one physical line, grouped by the piece they came from.

    A colon before a numbered item ("...the following: 1. Open") starts a new piece. This is the
    single place where statement boundaries are decided: extraction, checking and removal all use it.
    """
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


def is_framing(statement: str) -> bool:
    """A heading, lead-in or word-only fragment ("Key points:", "Biddle.") carries no claim.

    A short fragment that contains a digit ("17 February 2026.") is exactly what a short answer
    looks like, so it is checked like any other statement.
    """
    text = statement.strip()
    return text.endswith(":") or (len(text.split()) < 4 and not re.search(r"\d", text))


def build_user_message(statements: Sequence[str], evidence: str, question: str = "") -> str:
    numbered = "\n".join(f"[S{i}] {s}" for i, s in enumerate(statements, 1))
    given = f"{evidence[:MAX_EVIDENCE_CHARS]}\n{question}"
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
    kept_lines: list[str] = []
    removed = 0
    index = 0  # position of the next statement, in the numbering the checker was shown
    for line in lines:
        pieces = _line_pieces(line)
        count = sum(len(piece) for piece in pieces)
        hits = {i - index for i in flagged if index <= i < index + count}
        if not hits:
            kept_lines.append(line)
        else:
            rebuilt = _rebuild_line(line, pieces, hits)
            if rebuilt:
                kept_lines.append(rebuilt)
            removed += len(hits)
        index += count
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(kept_lines)).strip()
    if _is_only_markers(text):
        text = ""
    logger.info("rag_execution path=claim_check outcome=REMOVED count=%d", removed)
    return ClaimCheckResult(text, removed, True)


_LIST_PREFIX = re.compile(r"^(?:[-*]\s+)?(?:\(?\d{1,2}[.)]\s+)?")


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
    return indent + "\n".join(out) if out else ""


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
    return "\n\n".join(f"[{s.members[0].filename}]\n{s.combined_text}" for s in sections)


def user_text(messages: Sequence[AgentMessage]) -> str:
    """What the user wrote in this conversation: its numbers are given, not claims to verify."""
    return "\n".join(m.text for m in messages if m.role == "USER" and m.text)
