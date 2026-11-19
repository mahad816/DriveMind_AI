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

logger = logging.getLogger(__name__)

CompleteJson = Callable[[str, str], Awaitable[str]]
CLAIM_CHECK_TIMEOUT_SECONDS = 20.0
MAX_EVIDENCE_CHARS = 24_000
MAX_STATEMENTS = 40

SYSTEM_PROMPT = (
    "You check an assistant's answer against the evidence passages it was given. Statements are "
    "labelled [S1], [S2], and so on; ignore any other numbers. Reply with JSON only: "
    '{"unsupported": ["S3", "S5"]} using those labels, or {"unsupported": []}.\n'
    "Flag a statement ONLY when it states a specific fact (a number, date, name, quantity, rule or "
    "other concrete claim) that is missing from the evidence or contradicted by it.\n"
    "Do NOT flag a statement for any of these: a paraphrase or summary of the evidence; a "
    "reasonable inference from it; framing, a caveat, a conclusion or a heading; simple arithmetic "
    "on numbers in the evidence; a statement that something is not in the documents; an offer to "
    "help; wording that is more or less specific than the evidence but not contradicted by it; "
    "partial support (if most of the statement is in the evidence, it is supported).\n"
    "Judge meaning, not word overlap, and ignore citation markers like [1] or [source_1]. "
    "When in doubt, the statement is supported."
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


def split_statements(text: str) -> list[str]:
    """Split an answer into statements: one per non-empty line, long lines also per sentence."""
    units: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        line = _COLON_BEFORE_LIST.sub("\n", line)
        for piece in line.splitlines():
            units.extend(_merge_markers(sentences(piece)))
    return units


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


def is_framing(statement: str) -> bool:
    """A heading, lead-in or fragment ("Key points:", "Biddle.") carries no claim worth removing."""
    text = statement.strip()
    return text.endswith(":") or len(text.split()) < 4


def build_user_message(statements: Sequence[str], evidence: str) -> str:
    numbered = "\n".join(f"[S{i}] {s}" for i, s in enumerate(statements, 1))
    return f"Evidence passages:\n{evidence[:MAX_EVIDENCE_CHARS]}\n\nAnswer statements:\n{numbered}"


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
    complete_json: CompleteJson, statements: Sequence[str], evidence: str
) -> frozenset[int] | None:
    """Ask the model which statements are unsupported; None means the check could not be done."""
    if not statements or not evidence.strip() or len(statements) > MAX_STATEMENTS:
        return None
    try:
        async with asyncio.timeout(CLAIM_CHECK_TIMEOUT_SECONDS):
            raw = await complete_json(SYSTEM_PROMPT, build_user_message(statements, evidence))
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
    complete_json: CompleteJson, answer: str, evidence: str
) -> ClaimCheckResult:
    """Return ``answer`` without the statements the evidence does not support."""
    if _is_only_markers(answer):
        return ClaimCheckResult(answer, 0, False)
    lines = answer.splitlines()
    statements = split_statements(answer)
    flagged = await find_unsupported(complete_json, statements, evidence)
    if flagged is None:
        return ClaimCheckResult(answer, 0, False)
    if not flagged:
        return ClaimCheckResult(answer, 0, True)
    dropped = {statements[i] for i in flagged}
    kept_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped in dropped:
            continue
        parts = sentences(stripped)
        if len(parts) > 1 and any(p.strip() in dropped for p in parts):
            line = " ".join(p.strip() for p in parts if p.strip() not in dropped)
        kept_lines.append(line)
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(kept_lines)).strip()
    if _is_only_markers(text):
        text = ""
    logger.info("rag_execution path=claim_check outcome=REMOVED count=%d", len(flagged))
    return ClaimCheckResult(text, len(flagged), True)


def _is_only_markers(text: str) -> bool:
    return not re.sub(r"\[[^\]]*\]|[\s\-*#>.:;,]", "", text)


def clean_unit(text: str) -> str:
    """Drop a list number that a sentence splitter left glued to the end of a unit ("... TV. 3.")."""
    return _TRAILING_MARKER.sub("", text.strip())


ClaimChecker = Callable[[str, str], Awaitable[ClaimCheckResult]]  # (answer, evidence) -> result


def evidence_text(sections: Sequence[EvidenceSection]) -> str:
    """The text the agent actually retrieved this turn, labelled by file name."""
    return "\n\n".join(f"[{s.members[0].filename}]\n{s.combined_text}" for s in sections)
