"""Failure-cause assignment: one primary cause per failed case, in a fixed, documented order.

A case is attributed when it failed: the legacy pass is false, or the deterministic strict pass is false.
Every rule below that matches is recorded; the FIRST in this order is the primary cause and the rest are
secondary flags. The order puts what makes later evidence meaningless first (an error, an index that lacks
the anchor), then the stage of the pipeline, upstream to downstream, then answer-quality causes.

A rule only fires on evidence the row really holds. Without a trace the retrieval rules cannot fire; a row
no rule explains is ``unknown``. It is never forced into a cause.

Causes are *most likely* explanations from recorded facts, not proofs. In particular
``claim_check_removal`` says a removal happened on a case whose fact is missing and whose passage was
retrieved; it cannot show that the removed statement was the correct one.
"""

from collections.abc import Callable, Mapping
from typing import Any

from app.agents.tool_rag.finalization import EMPTY_CONTENT, FILE_NOT_FOUND_TEXT, NO_CONTENT
from app.llm.prompts import DEMO_NO_EVIDENCE_ANSWER, NO_EVIDENCE_ANSWER
from app.services.tool_agent_service import TRUNCATION_NOTICE

from .score import ANSWERABLE

Case = Mapping[str, Any]
Row = Mapping[str, Any]
ENVELOPES = (NO_EVIDENCE_ANSWER, DEMO_NO_EVIDENCE_ANSWER, EMPTY_CONTENT, NO_CONTENT)


def _ex(row: Row) -> Mapping[str, Any]:
    return row.get("execution") or {}


def _facts_missing(case: Case, row: Row) -> bool:
    recall = (row.get("fact_recall") or {}).get("recall")
    return case["expected_behavior"] in ANSWERABLE and recall is not None and recall < 1


def _seen(row: Row) -> bool | None:
    """Was every anchor passage retrieved or read? ``None`` when that cannot be known."""
    return (row.get("retrieval") or {}).get("anchor_seen")


def _searched(row: Row) -> int:
    return int(_ex(row).get("search_count") or 0)


def _read(row: Row) -> int:
    return int(_ex(row).get("whole_file_reads") or 0)


def provider_error(case: Case, row: Row) -> bool:
    return bool(row.get("error")) or _ex(row).get("outcome") in {"TIMEOUT", "INTERNAL_ERROR"}


def extraction(case: Case, row: Row) -> bool:
    return bool((row.get("citation") or {}).get("absent_anchors"))


def intent_gate_short_circuit(case: Case, row: Row) -> bool:
    return _ex(row).get("path") == "intent" and case["expected_behavior"] != "chitchat"


def cycle_limit(case: Case, row: Row) -> bool:
    """The agent hit its limit, and it matters: facts are missing (or this is not an answerable case)."""
    limited = _ex(row).get("outcome") in {"CYCLE_LIMIT", "MESSAGE_LIMIT"}
    return limited and (_facts_missing(case, row) or case["expected_behavior"] not in ANSWERABLE)


def whole_file_read(case: Case, row: Row) -> bool:
    return _facts_missing(case, row) and _searched(row) == 0 and _read(row) > 0


def no_search(case: Case, row: Row) -> bool:
    if _ex(row).get("path") != "tool_agent" or _searched(row) or _read(row):
        return False
    wrong_route = row["reply"].strip() == FILE_NOT_FOUND_TEXT and not case.get("names_a_file")
    return _facts_missing(case, row) or (
        wrong_route and case["expected_behavior"] not in ANSWERABLE
    )


def retrieval_miss(case: Case, row: Row) -> bool:
    return _facts_missing(case, row) and _seen(row) is False and (_searched(row) or _read(row)) > 0


def no_evidence_envelope(case: Case, row: Row) -> bool:
    return _facts_missing(case, row) and any(text in row["reply"] for text in ENVELOPES)


def truncation_notice(case: Case, row: Row) -> bool:
    return _facts_missing(case, row) and TRUNCATION_NOTICE in row["reply"]


def claim_check_removal(case: Case, row: Row) -> bool:
    return (
        _facts_missing(case, row)
        and _seen(row) is True
        and _ex(row).get("claim_check_removed", 0) > 0
    )


def generation_error(case: Case, row: Row) -> bool:
    """A forbidden (wrong) value stated on a plain answer case."""
    answer = row.get("answer") or {}
    return case["expected_behavior"] == "answer" and bool(answer.get("forbidden_present"))


def fabrication(case: Case, row: Row) -> bool:
    return row.get("outcome") == "fabrication"


def grounding(case: Case, row: Row) -> bool:
    """A value in the reply that neither the cited chunks nor the anchor passages contain."""
    screen = row.get("screen")
    return screen is not None and bool(screen["unsupported"])


def citation(case: Case, row: Row) -> bool:
    """The facts are right but the sources are wrong: wrong or missing passage, wrong files, bad chunk."""
    block = row.get("citation") or {}
    integrity = block.get("integrity")
    bad_integrity = integrity is not None and not integrity["ok"]
    if case["expected_behavior"] not in ANSWERABLE:
        return bad_integrity
    evidence = row.get("evidence") or {}
    return (not _facts_missing(case, row)) and (
        bad_integrity
        or block.get("all_anchors_cited") is False
        or evidence.get("found") is False
        or (block.get("unnecessary_files") or 0) > 0
    )


def false_abstention(case: Case, row: Row) -> bool:
    return row.get("outcome") == "false_abstention"


def retrieved_not_used(case: Case, row: Row) -> bool:
    return _facts_missing(case, row) and _seen(row) is True


# Every rule takes (case, row) so the table is uniform, even when a rule ignores one of them.
# Priority order: the first rule that matches is the primary cause.
RULES: tuple[tuple[str, Callable[[Case, Row], bool]], ...] = (
    ("provider_or_timeout_error", provider_error),
    ("extraction", extraction),
    ("intent_gate_short_circuit", intent_gate_short_circuit),
    ("cycle_limit", cycle_limit),
    ("whole_file_read", whole_file_read),
    ("no_search", no_search),
    ("retrieval_miss", retrieval_miss),
    ("no_evidence_envelope", no_evidence_envelope),
    ("truncation_notice", truncation_notice),
    ("claim_check_removal", claim_check_removal),
    ("generation_error", generation_error),
    ("fabrication", fabrication),
    ("grounding", grounding),
    ("citation", citation),
    ("false_abstention", false_abstention),
    ("retrieved_not_used", retrieved_not_used),
)


def failed(row: Row) -> bool:
    return (row.get("overall") or {}).get("pass") is False or row["strict"][
        "deterministic"
    ] is False


def attribute(case: Case, row: Row) -> dict[str, Any] | None:
    """``None`` for a case that did not fail; otherwise the primary cause, the secondary flags and which
    pass failed. ``unknown`` means no rule could explain the failure from the recorded data."""
    if row.get("cap_stopped") or not failed(row):
        return None
    matched = [name for name, rule in RULES if rule(case, row)]
    return {
        "primary": matched[0] if matched else "unknown",
        "secondary": matched[1:],
        "failed": "legacy" if (row.get("overall") or {}).get("pass") is False else "strict",
    }
