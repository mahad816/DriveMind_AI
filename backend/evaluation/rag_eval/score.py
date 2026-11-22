"""Deterministic per-case scoring plus rate summaries with confidence intervals.

Four things are scored separately so one weak stage cannot hide behind another:
  evidence  - did the citations point at the files that hold the answer (and how much noise)?
  answer    - are all required facts present and no forbidden claim asserted (answer cases)?
  refusal   - did it decline / say not found / correct the premise (judge verdict, non-answer cases)?
  clean     - no citation attached to a reply that should have none (chitchat, inventory, refusals)?
"""

from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from math import sqrt
from typing import Any

from .stats import bootstrap_percentile, percentile
from .text import contains, satisfies

Z95 = 1.96
SUMMARY_VERSION = 2
ANSWERED = {"answer", "partial", "inventory", "correct_premise"}  # behaviours scored for facts
ANSWERABLE = {"answer", "partial"}  # the files hold (some of) the answer
REFUSALS = {"not_found", "decline_or_not_found", "correct_premise"}
MAX_EXTRA_FILES = 1  # strict pass: cited files outside the expected set, at most this many
ROLLUPS = ("category", "format", "split", "language", "expected_behavior", "critical_tag")


def wilson(successes: int, total: int) -> tuple[float, float]:
    """95% Wilson score interval for a proportion (honest about small samples)."""
    if total == 0:
        return (0.0, 0.0)
    p = successes / total
    denom = 1 + Z95**2 / total
    centre = (p + Z95**2 / (2 * total)) / denom
    half = Z95 * sqrt(p * (1 - p) / total + Z95**2 / (4 * total**2)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


@dataclass(frozen=True)
class Observed:
    answer: str
    cited_files: tuple[str, ...]  # corpus-relative paths, deduplicated, order kept
    error: str | None = None


def evidence_score(case: dict[str, Any], seen: Observed) -> dict[str, Any] | None:
    expected = case["expected_files"]
    if case["expected_behavior"] not in {"answer", "partial"} or not expected:
        return None
    hits = [f for f in expected if f in seen.cited_files]
    ok = bool(hits) if case.get("citation_mode") == "any" else len(hits) == len(expected)
    extra = [f for f in seen.cited_files if f not in expected]
    return {"found": ok, "expected": len(expected), "hit": len(hits), "noise_files": len(extra)}


def answer_score(case: dict[str, Any], seen: Observed) -> dict[str, Any] | None:
    if case["expected_behavior"] not in ANSWERED:
        return None
    missing = [g for g in case["must_include"] if not satisfies(seen.answer, g)]
    forbidden = [c for c in case["must_not_include"] if contains(seen.answer, c)]
    return {
        "correct": not missing and not forbidden and seen.error is None,
        "missing": [g[0] for g in missing],
        "forbidden_present": forbidden,
    }


def fact_recall(case: Mapping[str, Any], seen: Observed) -> dict[str, Any] | None:
    """Required fact groups present over required: partial credit next to the all-or-nothing ``correct``."""
    if case["expected_behavior"] not in ANSWERED:
        return None
    groups = case["must_include"]
    present = sum(satisfies(seen.answer, g) for g in groups)
    return {
        "required": len(groups),
        "present": present,
        "recall": round(present / len(groups), 3) if groups else None,
    }


def clean_score(case: dict[str, Any], seen: Observed) -> dict[str, Any] | None:
    if case["expected_behavior"] in {"answer", "partial"}:
        return None
    forbidden = [c for c in case["must_not_include"] if contains(seen.answer, c)]
    return {
        "clean": not seen.cited_files and not forbidden,
        "citations": len(seen.cited_files),
        "forbidden_present": forbidden,
    }


def rates(rows: list[dict[str, Any]], key: str, flag: str) -> dict[str, Any]:
    """Share of rows where rows[*][key][flag] is true, ignoring rows where the stage does not apply."""
    return rate_of(
        [r[key][flag] for r in rows if r.get(key) is not None and r[key][flag] is not None]
    )


def rate_of(flags: list[bool]) -> dict[str, Any]:
    n, k = len(flags), sum(flags)
    lo, hi = wilson(k, n)
    return {
        "n": n,
        "passed": k,
        "rate": round(k / n, 3) if n else None,
        "ci95": [round(lo, 3), round(hi, 3)],
    }


def summarise(all_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Rates over the cases that really ran. Cases the spend cap ended are counted, never scored."""
    rows = [r for r in all_rows if not r.get("cap_stopped")]
    stopped = len(all_rows) - len(rows)
    by_cat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_cat[r["category"]].append(r)
    latencies = sorted(r["latency_s"] for r in rows if r.get("latency_s") is not None)

    def pct(q: float) -> float | None:
        value = percentile(latencies, q)
        return None if value is None else round(value, 2)

    summary = {
        "cases": len(all_rows),
        "cap_stopped": stopped,
        "incomplete": stopped > 0,
        "errors": sum(1 for r in rows if r.get("error")),
        "evidence_found": rates(rows, "evidence", "found"),
        "answer_correct": rates(rows, "answer", "correct"),
        "refusal_ok": rates(rows, "refusal", "ok"),
        "clean": rates(rows, "clean", "clean"),
        "overall_pass": rates(rows, "overall", "pass"),
        "latency_s": {
            "p50": pct(0.5),
            "p90": pct(0.9),
            "max": latencies[-1] if latencies else None,
        },
        "by_category": {c: rates(v, "overall", "pass") for c, v in sorted(by_cat.items())},
    }
    return summary | summary_v2(all_rows, rows, latencies)


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def summary_v2(
    all_rows: list[dict[str, Any]], rows: list[dict[str, Any]], latencies: list[float]
) -> dict[str, Any]:
    """Version 2 additions. Every figure comes from fields ``deep.extend_row`` wrote; rows without them
    (older result files) simply do not count, and ``n`` says how many did."""

    def nested(*path: str) -> list[bool]:
        values = []
        for r in rows:
            node: Any = r
            for step in path:
                node = node.get(step) if isinstance(node, dict) else None
            if isinstance(node, bool):
                values.append(node)
        return values

    def counted(key: str) -> dict[str, int]:
        return dict(sorted(Counter(r[key] for r in rows if r.get(key)).items()))

    outcomes: dict[str, dict[str, int]] = {}
    for group in ("answerable", "non_answer", "other"):
        tally = Counter(r["outcome"] for r in rows if r.get("outcome_group") == group)
        if tally:
            outcomes[group] = dict(sorted(tally.items()))
    recalls = [
        r["fact_recall"]["recall"]
        for r in rows
        if (r.get("fact_recall") or {}).get("recall") is not None
    ]
    ranks = [
        r["retrieval"]["best_rank"] for r in rows if (r.get("retrieval") or {}).get("best_rank")
    ]
    causes = Counter((r.get("cause") or {}).get("primary") for r in rows if r.get("cause"))
    unrated = [r for r in rows if r.get("strict") and r["strict"].get("deterministic") is None]
    return {
        "schema_version": SUMMARY_VERSION,
        "row_status": dict(sorted(Counter(r.get("status", "unscored") for r in all_rows).items())),
        "strict_deterministic": rates(rows, "strict", "deterministic"),
        "strict_deterministic_undecided": len(unrated),
        "strict_graded": rates(
            rows, "strict", "graded"
        ),  # empty until the grader exists (ticket 09)
        "fact_recall_mean": _mean(recalls),
        "citation": {
            "anchors_cited": rate_of(nested("citation", "all_anchors_cited")),
            "integrity": rate_of(nested("citation", "integrity", "ok")),
            "precision_mean": _mean(
                [
                    r["citation"]["precision"]
                    for r in rows
                    if (r.get("citation") or {}).get("precision") is not None
                ]
            ),
        },
        "retrieval": {
            "anchor_retrieved": rate_of(nested("retrieval", "anchor_retrieved")),
            "file_retrieved": rate_of(nested("retrieval", "file_retrieved")),
            "best_rank_median": percentile(sorted(ranks), 0.5),
        },
        "unseen_value_screen_clean": rates(rows, "screen", "clean"),
        "outcomes": outcomes,
        "failure_causes": dict(sorted(causes.items())),
        "critical_candidates": sum(1 for r in rows if r.get("critical_candidates")),
        "needs_review": sum(1 for r in rows if r.get("review")),
        "latency_p50_ci95": bootstrap_percentile(latencies, 0.5),
        "latency_p90_ci95": bootstrap_percentile(latencies, 0.9),
        "rollups": {dim: _rollup(rows, dim) for dim in ROLLUPS if any(dim in r for r in rows)},
    }


def _rollup(rows: list[dict[str, Any]], dimension: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[str(r.get(dimension))].append(r)
    return {
        value: {
            "legacy": rates(members, "overall", "pass"),
            "strict": rates(members, "strict", "deterministic"),
        }
        for value, members in sorted(groups.items())
    }
