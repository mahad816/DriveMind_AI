"""Evaluation-only diagnostics for the runtime claim check (KI-002): draft, statements, evidence, decisions.

The answer-quality pilot could not say why the checker removed a statement: the draft before checking, the
checker's raw reply and the evidence it saw were not kept. This module records them for ONE case at a time.

How it stays out of production
* It wraps the application from outside, the way ``trace.tracing_installed`` already wraps the tool executor:
  ``ToolRagAgentService.__init__`` (to wrap the checker it receives), ``claim_check.find_unsupported`` and
  ``graph.evidence_text``. No application file changes, so no behaviour can change and the application has no code
  that stores a draft.
* It records only for a case whose trace was created with ``claim_detail=True`` (the CLI flag
  ``--trace-claim-check``, off by default, refused for the held-out pool). Without that, every wrapper calls straight
  through.
* The record lives on the in-memory ``CaseTrace`` and is written only into the evaluation result file (Git-ignored
  folder, never an API response, never a log line).
* Retrieved passages are identified by chunk id and character span, not copied. The draft, the statements and the
  user's own messages ARE kept: they are what the checker judged, and they cannot be rebuilt otherwise.

The record states what the checker was given and decided. It does not say whether a decision was right.
"""

import hashlib
from collections import Counter
from collections.abc import Awaitable, Callable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter
from typing import Any

from app.agents.tool_rag import claim_check as claim_module
from app.agents.tool_rag import graph as graph_module
from app.agents.tool_rag.agent_service import ToolRagAgentService
from app.agents.tool_rag.claim_check import ClaimCheckResult
from app.routing.intent_frame.evidence import EvidenceSection

from .trace import CaseTrace, trace_var

# The record being filled while one check runs; the inner wrapper reads it. Separate per task.
_current: ContextVar[dict[str, Any] | None] = ContextVar("claim_check_record", default=None)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _active() -> CaseTrace | None:
    case = trace_var.get()
    return case if case is not None and case.claim_detail else None


def describe_evidence(sections: Sequence[EvidenceSection], text: str) -> dict[str, Any]:
    """Which chunks sit where in the evidence string, and how much of it the checker can receive.

    ``text`` is exactly what ``evidence_text`` returned. The checker is sent ``text[:MAX_EVIDENCE_CHARS]``.
    """
    limit = claim_module.MAX_EVIDENCE_CHARS
    out_sections: list[dict[str, Any]] = []
    offset = 0
    for index, section in enumerate(sections):
        if index:
            offset += 2  # the "\n\n" between sections
        header = claim_module.section_label(section.members[0].filename) + "\n"
        base = offset + len(header)
        by_id = {m.chunk_id: m for m in section.members}
        chunks = []
        for chunk_id, start, end in section.member_ranges:
            first, last = base + start, base + end
            sent = "full" if last <= limit else "none" if first >= limit else "partial"
            chunks.append(
                {
                    "chunk_id": str(chunk_id),
                    "chunk_index": by_id[chunk_id].chunk_index,
                    "start": first,
                    "end": last,
                    "sent": sent,
                }
            )
        end_of_section = base + len(section.combined_text)
        out_sections.append(
            {
                "file": section.members[0].filename,
                "file_id": str(section.members[0].file_id),
                "start": base,
                "end": end_of_section,
                "chunks": chunks,
            }
        )
        offset = end_of_section
    return {
        "chars": len(text),
        "limit_chars": limit,
        "chars_sent": min(len(text), limit),
        "truncated": len(text) > limit,
        "sha256": sha(text),
        "sections": out_sections,
    }


def _model_name(complete: Callable[..., Any]) -> str | None:
    name = getattr(getattr(complete, "__self__", None), "model_name", None)
    return name if isinstance(name, str) else None


def _new_record(case: CaseTrace, answer: str, evidence: str, question: str) -> dict[str, Any]:
    pending, case.pending_evidence = case.pending_evidence, None
    matches = pending is not None and pending["evidence"]["sha256"] == sha(evidence)
    if pending is not None and matches:
        described = dict(pending["evidence"])
    else:  # the evidence string did not come from ``evidence_text``: say so, identify nothing
        described = {
            "chars": len(evidence),
            "limit_chars": claim_module.MAX_EVIDENCE_CHARS,
            "chars_sent": min(len(evidence), claim_module.MAX_EVIDENCE_CHARS),
            "truncated": len(evidence) > claim_module.MAX_EVIDENCE_CHARS,
            "sha256": sha(evidence),
            "sections": [],
        }
    described["matches_sections"] = matches
    record: dict[str, Any] = {
        "index": len(case.claim_checks) + 1,
        "draft_answer": answer,
        "statements": claim_module.split_statements(answer),
        "number_hints": {},
        "context": {"user_messages": question},
        "evidence": described,
        "prompt": {"system_sha256": sha(claim_module.SYSTEM_PROMPT)},
        "checker": {
            "model_called": False,
            "model": None,
            "latency_ms": None,
            "raw_reply": None,
            "error": None,
            "skipped_reason": None,
        },
        "decisions": {"raw_labels": None, "flagged": [], "framing_ignored": []},
        "outcome": {},
    }
    case.claim_checks.append(record)
    return record


def _labels(indexes: Sequence[int]) -> list[str]:
    return [f"S{i + 1}" for i in sorted(indexes)]


def _number_hints(statements: Sequence[str], evidence: str, question: str) -> dict[str, list[str]]:
    given = f"{claim_module.evidence_body(evidence[: claim_module.MAX_EVIDENCE_CHARS])}\n{question}"
    return {
        f"S{i}": missing
        for i, s in enumerate(statements, 1)
        if (missing := claim_module.numbers_missing(s, given))
    }


def _traced_find_unsupported(
    original: Callable[..., Awaitable[frozenset[int] | None]],
) -> Callable[..., Awaitable[frozenset[int] | None]]:
    async def find_unsupported(
        complete_json: claim_module.CompleteJson,
        statements: Sequence[str],
        evidence: str,
        question: str = "",
    ) -> frozenset[int] | None:
        record = _current.get()
        if record is None:
            return await original(complete_json, statements, evidence, question)
        checker, decisions = record["checker"], record["decisions"]
        if not statements:
            checker["skipped_reason"] = "no_statements"
        elif not evidence.strip():
            checker["skipped_reason"] = "no_evidence"
        elif len(statements) > claim_module.MAX_STATEMENTS:
            checker["skipped_reason"] = "too_many_statements"
        else:
            record["number_hints"] = _number_hints(statements, evidence, question)

        async def timed(system: str, user: str) -> str:
            checker.update(model_called=True, model=_model_name(complete_json))
            record["prompt"].update(user_message_chars=len(user), user_message_sha256=sha(user))
            started = perf_counter()
            try:
                raw = await complete_json(system, user)
            except (
                BaseException
            ) as exc:  # a timeout arrives as a cancellation; recorded, then re-raised
                checker["error"] = type(exc).__name__
                raise
            finally:
                checker["latency_ms"] = round((perf_counter() - started) * 1000, 1)
            checker["raw_reply"] = raw
            return raw

        result = await original(timed, statements, evidence, question)
        if checker["error"] == "CancelledError":
            # ``find_unsupported`` returned, so the cancellation was its own timeout, not an outer cancel.
            checker["error"] = "TimeoutError"
        if checker["raw_reply"] is not None:
            raw_indexes = claim_module.parse_unsupported(checker["raw_reply"], len(statements))
            decisions["raw_labels"] = None if raw_indexes is None else _labels(sorted(raw_indexes))
            if raw_indexes is not None and result is not None:
                decisions["framing_ignored"] = _labels(sorted(raw_indexes - result))
        if result is not None:
            decisions["flagged"] = _labels(sorted(result))
        return result

    return find_unsupported


def _fail_open_reason(record: dict[str, Any], answer: str) -> str:
    checker = record["checker"]
    if checker["skipped_reason"]:
        return str(checker["skipped_reason"])
    if checker["error"]:
        return f"call_error:{checker['error']}"
    if checker["raw_reply"] is not None:
        return "bad_reply"
    if claim_module._is_only_markers(answer):
        return "marker_only_answer"
    return "unknown"


def _squash(text: str) -> str:
    return " ".join(text.split())


def attribute_removals(
    draft: str, statements: Sequence[str], flagged: Sequence[str], remaining: str
) -> dict[str, Any]:
    """What happened to each statement, read from the answer text before and after, not from the checker's labels.

    Since KI-035 was fixed, ``enforce_claims`` removes exactly the flagged units, so a non-empty
    ``flagged_not_removed`` or ``collateral_removed`` in a new run means a new defect, except a structural lead-in dropped because every item it introduced was removed (documented in KNOWN_ISSUES SC-5), not normal behaviour (older
    result files can contain them: the old code kept a flagged numbered statement and dropped every copy of a
    flagged text). This function still reads only the text before and after. Each statement is
    judged by how many copies of its text (as a whole statement unit, whitespace squashed) the remaining answer
    holds compared with the draft:

    * all copies gone: ``removed`` when the statement was flagged, ``collateral_removed`` when it was not;
    * no copy gone: ``flagged_not_removed`` when it was flagged;
    * some copies gone: ``uncertain`` (which copy went cannot be told; nothing is claimed).
    If the remaining answer holds a unit the draft never had, the change is not a pure removal: nothing is
    attributed and every statement that vanished is ``uncertain``, with ``unattributed_change`` set.
    """
    before = Counter(_squash(s) for s in statements)
    after = Counter(_squash(u) for u in claim_module.split_statements(remaining))
    novel = bool(after - before)
    flagged_set = set(flagged)
    groups: dict[str, list[tuple[str, str]]] = {}
    for index, statement in enumerate(statements, 1):
        key = _squash(statement)
        if key:
            groups.setdefault(key, []).append((f"S{index}", statement))
    out: dict[str, Any] = {
        "removed": [],
        "flagged_not_removed": [],
        "uncertain": [],
        "collateral_removed": [],
        "unattributed_change": novel,
    }
    for key, members in groups.items():
        gone = before[key] - after[key]
        has_flag = any(label in flagged_set for label, _ in members)
        if gone <= 0:
            for label, text in members:
                if label in flagged_set:
                    out["flagged_not_removed"].append({"label": label, "text": text})
            continue
        if novel or after[key] > 0:
            reason = (
                "the answer changed in a way that is not a pure removal"
                if novel
                else "some copies of this text remain; which one was removed cannot be told"
            )
            for label, text in members:
                if label in flagged_set or not has_flag:
                    out["uncertain"].append({"label": label, "text": text, "reason": reason})
            continue
        for label, text in members:
            target = "removed" if label in flagged_set else "collateral_removed"
            out[target].append({"label": label, "text": text})
    return out


def _finish(record: dict[str, Any], answer: str, result: ClaimCheckResult) -> None:
    """Record what happened to the answer. The checker's decisions are in ``decisions``; this is the observation."""
    flagged = record["decisions"]["flagged"]
    if result.checked:
        seen = attribute_removals(answer, record["statements"], flagged, result.text)
    else:
        seen = {
            "removed": [],
            "flagged_not_removed": [],
            "uncertain": [],
            "collateral_removed": [],
            "unattributed_change": False,
        }
    changed = _squash(answer) != _squash(result.text)
    if not result.checked:
        kind = "unchecked"
    elif result.nothing_left:
        kind = "whole_answer_replaced"
    elif changed:
        kind = "partial_removal"
    elif flagged:
        kind = "flagged_none_removed"  # the checker flagged, the text is exactly as drafted
    else:
        kind = "unchanged"
    observed = len(seen["removed"]) + len(seen["collateral_removed"])
    undecided = bool(seen["uncertain"]) or seen["unattributed_change"]
    record["outcome"] = {
        "result": kind,
        "checked": result.checked,
        "fail_open_reason": None if result.checked else _fail_open_reason(record, answer),
        "removed_statements": seen["removed"],
        "flagged_not_removed": seen["flagged_not_removed"],
        "collateral_removed": seen["collateral_removed"],
        "uncertain": seen["uncertain"],
        "unattributed_change": seen["unattributed_change"],
        "remaining_answer": result.text,
        "replaced_entire_answer": result.nothing_left,
        "replacement_reason": "all_statements_removed" if result.nothing_left else None,
        # ``reported``: the application's own count (it also writes it to the log); ``observed``: removed here.
        "reported_removed_count": result.removed,
        "observed_removed_count": observed,
        "counter_matches_observation": None if undecided else result.removed == observed,
        "checker_exception": None,
    }


def _traced_checker(inner: claim_module.ClaimChecker) -> claim_module.ClaimChecker:
    async def check(answer: str, evidence: str, question: str = "") -> ClaimCheckResult:
        case = _active()
        if case is None:
            return await inner(answer, evidence, question)
        record = _new_record(case, answer, evidence, question)
        token = _current.set(record)
        try:
            result = await inner(answer, evidence, question)
        except Exception as exc:  # the graph treats this as "unchecked"; so does the record
            record["outcome"] = {
                "result": "unchecked",
                "checked": False,
                "fail_open_reason": "checker_exception",
                "removed_statements": [],
                "flagged_not_removed": [],
                "collateral_removed": [],
                "uncertain": [],
                "unattributed_change": False,
                "remaining_answer": answer,
                "replaced_entire_answer": False,
                "replacement_reason": None,
                "reported_removed_count": 0,
                "observed_removed_count": 0,
                "counter_matches_observation": None,
                "checker_exception": type(exc).__name__,
            }
            raise
        finally:
            _current.reset(token)
        _finish(record, answer, result)
        return result

    return check


@contextmanager
def claim_check_tracing() -> Iterator[None]:
    """Install the three wrappers; remove them on exit. Calls straight through unless a case asked for detail."""
    original_init = ToolRagAgentService.__init__
    original_find = claim_module.find_unsupported
    original_evidence = claim_module.evidence_text  # the function graph.py imported by name

    def init(self: ToolRagAgentService, *args: Any, **kwargs: Any) -> None:
        checker = kwargs.get("claim_check")
        if checker is not None:
            kwargs["claim_check"] = _traced_checker(checker)
        original_init(self, *args, **kwargs)

    def evidence_text(sections: Sequence[EvidenceSection]) -> str:
        text = original_evidence(sections)
        case = _active()
        if case is not None:
            case.pending_evidence = {"evidence": describe_evidence(sections, text)}
        return text

    ToolRagAgentService.__init__ = init  # type: ignore[method-assign]
    setattr(claim_module, "find_unsupported", _traced_find_unsupported(original_find))
    setattr(graph_module, "evidence_text", evidence_text)
    try:
        yield
    finally:
        ToolRagAgentService.__init__ = original_init  # type: ignore[method-assign]
        setattr(claim_module, "find_unsupported", original_find)
        setattr(graph_module, "evidence_text", original_evidence)


def attach_metering(trace: CaseTrace, accounting: dict[str, Any] | None) -> None:
    """Add the case's metered claim-check totals (tokens, dollars, model) next to the records.

    The meter counts per case and role, not per call, so these are totals for every check of the case; a case with
    one check (the usual case) has exact figures. Nothing is estimated.
    """
    if not trace.claim_detail or not accounting:
        return
    role = (accounting.get("by_role") or {}).get("claim_check")
    trace.claim_metering = {
        "case_totals_for_role": role,
        "checks_recorded": len(trace.claim_checks),
        "note": "Totals for every claim-check call of this case; per-call figures are not recorded.",
    }
