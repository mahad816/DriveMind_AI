"""Schema v3: what a case written for the frozen M1 question set must carry, and the shared tag logic.

Cases that declare ``"schema": 3`` get every rule below; the 201 older cases (no ``schema`` key) are never
edited and keep only the older rules, plus the history bound and the ``clarify`` rules, which hold for any case.
``case_types``, ``evidence_formats`` and ``gate_groups`` read old and new cases alike, so the coverage report
and the sealed summaries count the older pools from the fields they already have.

New fields (all optional on older cases):

  schema           3
  provenance       {"session": "m1-06-dev-a", "date": "2026-11-23"}: an author session, never a person
  tags             question-type tags from ``TYPE_TAGS``; each is checked against the case's own fields
  formats          optional; when given it must equal the formats of the evidence files
  critical         true for a case whose failure would be a glossary Critical failure
  critical_kind    which of the four glossary kinds (required when ``critical`` is true)
  injection_document  the corpus file that carries the embedded instruction (injection cases)
  sibling_exempt   values the same field takes elsewhere that a correct reply may mention
"""

import re
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import PurePosixPath
from typing import Any

from .text import contains, norm, satisfies

SCHEMA_VERSION = 3

# The production bound on prior messages. Stated once, here. `app/agents/tool_rag/agent_service.py` hard-codes
# the same two numbers, so `tests/evaluation/test_question_set.py` pins them to the application's behaviour.
HISTORY_MAX_MESSAGES = 6
HISTORY_MAX_CHARS = 6000

TYPE_TAGS = frozenset(
    {
        "multi_file",
        "table",
        "calculation",
        "identifier",
        "follow_up",
        "ambiguous",
        "injection",
        "superseded",
        "roman_urdu",
    }
)
# The four kinds in the glossary entry "Critical failure".
CRITICAL_KINDS = frozenset(
    {
        "fabricated_citation",
        "misattributed_content",
        "wrong_file_as_requested",
        "obeyed_injection",
    }
)
NON_ANSWER = frozenset(
    {"not_found", "partial", "correct_premise"}
)  # unanswerable, partial, false premise
GATE_TYPES = frozenset(
    {"multi_file", "table", "calculation", "identifier", "follow_up", "ambiguous", "injection"}
)
PROMISED_FORMATS = ("docx", "xlsx", "pptx", "pdf", "md", "csv", "txt")
SESSION = re.compile(r"^m\d+-[a-z0-9]+(?:-[a-z0-9]+)*$")
TABLE_CATEGORIES = {"borderless_table", "ruled_table", "second_sheet"}
ONE_QUESTION_MAX_CHARS = 240


def is_v3(case: Mapping[str, Any]) -> bool:
    return case.get("schema") == SCHEMA_VERSION


def evidence_files(case: Mapping[str, Any]) -> list[str]:
    """Files the answer rests on: expected files plus the files of the anchors, in order, without repeats."""
    names = [
        *(case.get("expected_files") or []),
        *(a["file"] for a in case.get("evidence_anchors") or []),
    ]
    return list(dict.fromkeys(names))


def evidence_formats(case: Mapping[str, Any]) -> list[str]:
    """Format names (file suffixes) of the evidence files, sorted. ``[]`` for a case with no evidence."""
    return sorted({PurePosixPath(p).suffix.lstrip(".").lower() for p in evidence_files(case)})


def lists_several_files(case: Mapping[str, Any]) -> bool:
    """An answer that must cite two or more files (``citation_mode: any`` lists alternatives, one suffices)."""
    return (
        case.get("expected_behavior") in {"answer", "partial"}
        and case.get("citation_mode", "all") != "any"
        and len(set(case.get("expected_files") or [])) >= 2
    )


def unanchored_files(case: Mapping[str, Any]) -> list[str]:
    """Expected files that carry no evidence anchor: a file listed but never needed for the answer."""
    anchored = {a["file"] for a in case.get("evidence_anchors") or []}
    return [f for f in dict.fromkeys(case.get("expected_files") or []) if f not in anchored]


def case_types(case: Mapping[str, Any]) -> set[str]:
    """Question-type tags: the explicit ``tags`` plus what the case's own fields already say."""
    behavior = case.get("expected_behavior")
    category = str(case.get("category", ""))
    found = set(case.get("tags") or [])
    found.discard(
        "multi_file"
    )  # a tag is a claim; the fields decide whether the case really is multi-file
    if lists_several_files(case) and not unanchored_files(case):
        found.add("multi_file")
    if category.startswith("table") or category in TABLE_CATEGORIES:
        found.add("table")
    if case.get("computed") or category.startswith("calculation") or category == "table_calc":
        found.add("calculation")
    if category == "identifier_in_question":
        found.add("identifier")
    if case.get("history") and behavior != "chitchat":
        found.add("follow_up")
    if behavior == "clarify":
        found.add("ambiguous")
    if category == "injection":
        found.add("injection")
    if category == "superseded_version":
        found.add("superseded")
    if case.get("language") == "roman_urdu":
        found.add("roman_urdu")
    return found


def gate_groups(case: Mapping[str, Any]) -> set[str]:
    """The coverage rows a case counts toward (``coverage.GATES`` names them)."""
    groups = {"total"} | {t for t in case_types(case) if t in GATE_TYPES}
    if case.get("expected_behavior") in NON_ANSWER:
        groups.add("non_answer")
    if case.get("critical"):
        groups.add("critical")
    groups |= {f"format_{f}" for f in evidence_formats(case) if f in PROMISED_FORMATS}
    return groups


# --- history bound ---------------------------------------------------------------------------------


def history_problems(cid: str, history: Sequence[Mapping[str, Any]]) -> list[str]:
    if not history:
        return []
    if not all(t.get("role") in {"user", "assistant"} and t.get("text") for t in history):
        return [f"{cid}: malformed history"]
    problems = []
    if len(history) > HISTORY_MAX_MESSAGES:
        problems.append(
            f"{cid}: history has {len(history)} messages; the production bound is {HISTORY_MAX_MESSAGES}"
        )
    size = sum(len(t["text"]) for t in history)
    if size > HISTORY_MAX_CHARS:
        problems.append(
            f"{cid}: history is {size} characters; the production bound is {HISTORY_MAX_CHARS}"
        )
    return problems


# --- clarify ----------------------------------------------------------------------------------------


def clarify_problems(case: Mapping[str, Any]) -> list[str]:
    """A "clarify" case is an ambiguous question: the right reply is one short question, not an answer.

    Its evidence anchors are the competing readings (each verbatim in the corpus, checked by the general
    rule); its forbidden claims are the values that committing to a reading would state, so each must occur
    in an anchor quote; no fact is required.
    """
    cid = case["id"]
    problems = []
    if case.get("expected_files"):
        problems.append(
            f"{cid}: clarify cases must not list expected_files (a clarifying reply cites nothing)"
        )
    if case.get("must_include"):
        problems.append(f"{cid}: clarify cases require no fact (must_include must be empty)")
    if case.get("computed"):
        problems.append(f"{cid}: clarify cases cannot be computed")
    reference = str(case.get("reference_answer") or "")
    if reference.count("?") != 1 or len(reference) > ONE_QUESTION_MAX_CHARS:
        problems.append(
            f"{cid}: reference_answer must be one short clarifying question "
            f"(exactly one '?', at most {ONE_QUESTION_MAX_CHARS} characters)"
        )
    quotes = [a["quote"] for a in case.get("evidence_anchors") or []]
    if len({norm(q) for q in quotes}) < 2:
        problems.append(f"{cid}: clarify cases need at least two distinct anchors, one per reading")
    if not case.get("must_not_include"):
        problems.append(f"{cid}: clarify cases need must_not_include (the values of the readings)")
    for claim in case.get("must_not_include") or []:
        if not any(contains(q, claim) for q in quotes):
            problems.append(
                f"{cid}: forbidden value {claim!r} is in no anchor quote (not a reading's value)"
            )
    if not case.get("judge_note"):
        problems.append(f"{cid}: clarify cases need a judge_note naming the readings")
    return problems


# --- the reference answer must pass the case's own deterministic checks -------------------------------


def reference_problems(case: Mapping[str, Any]) -> list[str]:
    """A gold answer that fails its own case would fail every correct reply too (or pass every wrong one).

    The reference must contain each required fact, must not contain a forbidden value, and for a ``clarify``
    case must be accepted as a clarifying question. Messages name the case and the rule only, never a value,
    so the same check can run on the sealed held-out pool without disclosing it.
    """
    from .deep import clarifying  # heavy import (application code), needed only for clarify cases

    cid = case["id"]
    reference = str(case.get("reference_answer") or "")
    problems = []
    if any(not satisfies(reference, group) for group in case.get("must_include") or []):
        problems.append(f"{cid}: reference answer lacks a required fact")
    if any(contains(reference, claim) for claim in case.get("must_not_include") or []):
        problems.append(f"{cid}: reference answer states a forbidden value")
    if case.get("expected_behavior") == "clarify" and clarifying(case, reference) is not True:
        problems.append(f"{cid}: reference answer is not accepted as a clarifying question")
    return problems


# --- anchors unique across near-duplicate and superseded documents -----------------------------------


def anchor_files(quote: str, texts: Mapping[str, str]) -> list[str]:
    """Corpus files whose extracted text contains this quote (normalised)."""
    needle = norm(quote)
    return [path for path, body in texts.items() if needle and needle in norm(body)]


def anchor_uniqueness_problems(case: Mapping[str, Any], texts: Mapping[str, str]) -> list[str]:
    """An anchor must identify one file. A quote that also occurs in a superseded or near-duplicate document
    cannot show which of them a citation should point at, so the quote must be lengthened."""
    problems = []
    for anchor in case.get("evidence_anchors") or []:
        holders = anchor_files(anchor["quote"], texts)
        if len(holders) > 1:
            problems.append(
                f"{case['id']}: anchor {anchor['quote'][:50]!r} occurs in {len(holders)} files "
                f"({', '.join(holders)}); lengthen it until it identifies one"
            )
    return problems


# --- sibling values ----------------------------------------------------------------------------------

_VALUE = re.compile(r"[\w$£€][\w$£€.,:/%-]*")
_SKIP_CELLS = {"", "-", "n/a", "none"}


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _is_separator(line: str) -> bool:
    cells = _cells(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", c) for c in cells)


def _tables(text: str) -> list[tuple[list[str], list[list[str]]]]:
    """(header cells, data rows) for each markdown table block in extracted text. A block with no separator
    line has an empty header."""
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.strip().startswith("|"):
            current.append(line)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    tables = []
    for block in blocks:
        if len(block) > 1 and _is_separator(block[1]):
            tables.append((_cells(block[0]), [_cells(r) for r in block[2:]]))
        else:
            tables.append(([], [_cells(r) for r in block if not _is_separator(r)]))
    return tables


def _column_siblings(value: str, quote: str, source: str, texts: Mapping[str, str]) -> list[str]:
    """Other values of the column that holds ``value`` in the table row the anchor quotes: the rest of that
    column in its own table, and the same-named column in any other table of the corpus."""
    found: list[str] = []
    for header, rows in _tables(source):
        for row in rows:
            if norm(quote) not in norm(" ".join(row)) and norm(quote) not in norm(" | ".join(row)):
                continue
            hits = [i for i, cell in enumerate(row) if contains(cell, value)]
            for i in hits:
                label = norm(header[i]) if i < len(header) else ""
                found += [r[i] for r in rows if i < len(r)]
                if label:
                    for other_header, other_rows in (
                        t for body in texts.values() for t in _tables(body)
                    ):
                        for j, name in enumerate(other_header):
                            if norm(name) == label:
                                found += [r[j] for r in other_rows if j < len(r)]
    return found


def _context_siblings(value: str, quote: str, texts: Mapping[str, str]) -> list[str]:
    """Numbers, dates and identifiers that follow the same few words as ``value`` does in the quote."""
    start = quote.find(value)
    if start <= 0:
        return []
    words = quote[:start].split()[-4:]
    if not words:
        return []
    pattern = re.compile(r"\s+".join(re.escape(w) for w in words) + r"\s*(" + _VALUE.pattern + ")")
    found = []
    for body in texts.values():
        found += [m.group(1).rstrip(".,:") for m in pattern.finditer(body)]
    return [v for v in found if any(ch.isdigit() for ch in v)]


def sibling_values(case: Mapping[str, Any], texts: Mapping[str, str]) -> list[str]:
    """Other values the field a case asks about takes elsewhere in the corpus (same table column, or the
    same words before a number or identifier). A reply that lists many values states these too, so they
    belong in ``must_not_include``. Excludes the case's own answer, anything in its question, history or
    reference answer, and one-character values. Empty for computed cases (the answer is not read off a field).
    """
    if case.get("computed") or case.get("expected_behavior") not in {"answer", "partial"}:
        return []
    own = [alt for group in case.get("must_include") or [] for alt in group]
    echoed = " ".join(
        [
            case.get("question", ""),
            case.get("reference_answer", ""),
            *(t["text"] for t in case.get("history") or []),
        ]
    )
    found: list[str] = []
    for group in case.get("must_include") or []:
        value = group[0]
        for anchor in case.get("evidence_anchors") or []:
            body = texts.get(anchor["file"], "")
            if not contains(anchor["quote"], value):
                continue
            found += _column_siblings(value, anchor["quote"], body, texts)
            found += _context_siblings(value, anchor["quote"], texts)
    result: dict[str, str] = {}
    for sibling in found:
        key = norm(sibling)
        if len(key) < 2 or key in _SKIP_CELLS or key in result:
            continue
        if any(contains(alt, sibling) or contains(sibling, alt) for alt in own) or contains(
            echoed, sibling
        ):
            continue
        result[key] = sibling
    return list(result.values())


def sibling_problems(case: Mapping[str, Any], texts: Mapping[str, str]) -> list[str]:
    covered = [*(case.get("must_not_include") or []), *(case.get("sibling_exempt") or [])]
    return [
        f"{case['id']}: value {sibling!r} is what the same field says elsewhere; add it to must_not_include "
        "(or to sibling_exempt when a correct reply may mention it)"
        for sibling in sibling_values(case, texts)
        if not any(contains(entry, sibling) for entry in covered)
    ]


# --- the v3 field rules ------------------------------------------------------------------------------


def _provenance_problems(cid: str, value: Any) -> list[str]:
    if not isinstance(value, dict) or set(value) != {"session", "date"}:
        return [f"{cid}: provenance must be {{'session': ..., 'date': ...}}"]
    problems = []
    if not isinstance(value["session"], str) or not SESSION.match(value["session"]):
        problems.append(
            f"{cid}: provenance.session must name an author session like 'm1-06-dev-a', not a person"
        )
    try:
        date.fromisoformat(str(value["date"]))
    except ValueError:
        problems.append(f"{cid}: provenance.date must be an ISO date")
    return problems


def v3_field_problems(
    case: Mapping[str, Any], injection_files: Mapping[str, str] | None = None
) -> list[str]:
    """Field rules for one v3 case (``injection_files``: corpus path to its injection kind, from the manifest)."""
    cid = case["id"]
    problems = _provenance_problems(cid, case.get("provenance"))
    tags = case.get("tags", [])
    if not isinstance(tags, list) or not set(tags) <= TYPE_TAGS:
        problems.append(f"{cid}: tags must be a list drawn from {sorted(TYPE_TAGS)}")
        tags = []
    behavior = case["expected_behavior"]
    if "multi_file" in tags and (
        len(set(case["expected_files"])) < 2 or case.get("citation_mode", "all") == "any"
    ):
        problems.append(
            f"{cid}: tag multi_file needs at least two expected_files that must all be cited "
            "(citation_mode all)"
        )
    if ("multi_file" in tags or lists_several_files(case)) and unanchored_files(case):
        problems.append(
            f"{cid}: a multi-file case needs an evidence anchor in every expected file; "
            f"none for {', '.join(unanchored_files(case))}"
        )
    if "follow_up" in tags and not case.get("history"):
        problems.append(f"{cid}: tag follow_up needs a history")
    if case.get("history") and behavior != "chitchat" and "follow_up" not in tags:
        problems.append(f"{cid}: a case with a history needs the tag follow_up")
    if "calculation" in tags and not case.get("computed"):
        problems.append(f"{cid}: tag calculation needs computed: true")
    if ("ambiguous" in tags) != (behavior == "clarify"):
        problems.append(f"{cid}: tag ambiguous and behaviour clarify go together")
    if "formats" in case and sorted(case["formats"]) != evidence_formats(case):
        problems.append(
            f"{cid}: formats {case['formats']} do not match the evidence files {evidence_formats(case)}"
        )
    if case.get("critical") and case.get("critical_kind") not in CRITICAL_KINDS:
        problems.append(f"{cid}: a critical case needs critical_kind from {sorted(CRITICAL_KINDS)}")
    if case.get("critical_kind") and not case.get("critical"):
        problems.append(f"{cid}: critical_kind without critical: true")
    document = case.get("injection_document")
    if "injection" in tags or document:
        if injection_files is None or document not in injection_files:
            problems.append(
                f"{cid}: injection cases need injection_document, a corpus file that carries an injection"
            )
    return problems
