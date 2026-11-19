"""Deterministic per-case scoring plus rate summaries with confidence intervals.

Four things are scored separately so one weak stage cannot hide behind another:
  evidence  - did the citations point at the files that hold the answer (and how much noise)?
  answer    - are all required facts present and no forbidden claim asserted (answer cases)?
  refusal   - did it decline / say not found / correct the premise (judge verdict, non-answer cases)?
  clean     - no citation attached to a reply that should have none (chitchat, inventory, refusals)?
"""

from collections import defaultdict
from dataclasses import dataclass
from math import sqrt
from typing import Any

from .text import contains, satisfies

Z95 = 1.96


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
    if case["expected_behavior"] != "answer" or not expected:
        return None
    hits = [f for f in expected if f in seen.cited_files]
    ok = bool(hits) if case.get("citation_mode") == "any" else len(hits) == len(expected)
    extra = [f for f in seen.cited_files if f not in expected]
    return {"found": ok, "expected": len(expected), "hit": len(hits), "noise_files": len(extra)}


def answer_score(case: dict[str, Any], seen: Observed) -> dict[str, Any] | None:
    if case["expected_behavior"] not in {"answer", "inventory", "correct_premise"}:
        return None
    missing = [g for g in case["must_include"] if not satisfies(seen.answer, g)]
    forbidden = [c for c in case["must_not_include"] if contains(seen.answer, c)]
    return {
        "correct": not missing and not forbidden and seen.error is None,
        "missing": [g[0] for g in missing],
        "forbidden_present": forbidden,
    }


def clean_score(case: dict[str, Any], seen: Observed) -> dict[str, Any] | None:
    if case["expected_behavior"] == "answer":
        return None
    forbidden = [c for c in case["must_not_include"] if contains(seen.answer, c)]
    return {
        "clean": not seen.cited_files and not forbidden,
        "citations": len(seen.cited_files),
        "forbidden_present": forbidden,
    }


def rates(rows: list[dict[str, Any]], key: str, flag: str) -> dict[str, Any]:
    """Share of rows where rows[*][key][flag] is true, ignoring rows where the stage does not apply."""
    applicable = [r[key][flag] for r in rows if r.get(key) is not None]
    n, k = len(applicable), sum(applicable)
    lo, hi = wilson(k, n)
    return {
        "n": n,
        "passed": k,
        "rate": round(k / n, 3) if n else None,
        "ci95": [round(lo, 3), round(hi, 3)],
    }


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_cat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_cat[r["category"]].append(r)
    latencies = sorted(r["latency_s"] for r in rows if r.get("latency_s") is not None)

    def pct(q: float) -> float | None:
        return (
            round(latencies[min(len(latencies) - 1, int(q * len(latencies)))], 2)
            if latencies
            else None
        )

    return {
        "cases": len(rows),
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
