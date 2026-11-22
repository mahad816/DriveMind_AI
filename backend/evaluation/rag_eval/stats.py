"""Comparing runs honestly: a paired exact test, bootstrap intervals and repeat stability.

Pure functions over result rows, no dependencies beyond the standard library. Wilson intervals for
single proportions live in ``score.py`` next to the rates they serve.
"""

import random
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from math import comb
from typing import Any

Row = Mapping[str, Any]
Metric = Callable[[Row], bool | None]  # None = this row has no value for the metric


def percentile(sorted_values: Sequence[float], q: float) -> float | None:
    """Nearest-rank percentile of already sorted values (the rule ``summarise`` always used)."""
    if not sorted_values:
        return None
    return float(sorted_values[min(len(sorted_values) - 1, int(q * len(sorted_values)))])


def bootstrap_percentile(
    values: Sequence[float], q: float, *, resamples: int = 2000, seed: int = 0, level: float = 0.95
) -> tuple[float, float] | None:
    """Percentile-bootstrap interval for the q-th percentile. The seed is fixed so a re-run of the same
    rows gives the same interval; with fewer than 2 values there is nothing to resample."""
    if len(values) < 2:
        return None
    rng = random.Random(seed)
    n = len(values)
    estimates = sorted(
        percentile(sorted(rng.choices(values, k=n)), q) or 0.0 for _ in range(resamples)
    )
    tail = (1 - level) / 2
    return (
        estimates[int(tail * resamples)],
        estimates[min(resamples - 1, int((1 - tail) * resamples))],
    )


def exact_sign_test(only_a: int, only_b: int) -> float:
    """Two-sided exact p-value that the cases which differ split evenly (McNemar's exact form)."""
    discordant = only_a + only_b
    if discordant == 0:
        return 1.0
    tail = sum(comb(discordant, i) for i in range(min(only_a, only_b) + 1)) / 2**discordant
    return float(min(1.0, 2 * tail))


def _by_id(rows: Sequence[Row], label: str) -> dict[str, Row]:
    ids = Counter(r["id"] for r in rows)
    repeated = sorted(i for i, n in ids.items() if n > 1)
    if repeated:
        raise ValueError(
            f"run {label} has a case more than once ({repeated[0]}); compare one repeat"
        )
    return {r["id"]: r for r in rows}


def paired_comparison(
    a_rows: Sequence[Row], b_rows: Sequence[Row], metric: Metric
) -> dict[str, Any]:
    """A against B on the same cases. Refuses when the two runs do not hold the same case ids, because a
    paired test on different cases would compare the questions, not the systems. A case whose metric is
    ``None`` in either run (cap-stopped, not applicable) is left out and counted as ``excluded``."""
    a, b = _by_id(a_rows, "A"), _by_id(b_rows, "B")
    if a.keys() != b.keys():
        missing = sorted(a.keys() ^ b.keys())
        raise ValueError(
            f"runs hold different cases ({len(missing)} differ, e.g. {missing[0]}); not comparable"
        )
    both = only_a = only_b = neither = excluded = 0
    for case_id in a:
        x, y = metric(a[case_id]), metric(b[case_id])
        if x is None or y is None:
            excluded += 1
        elif x and y:
            both += 1
        elif x:
            only_a += 1
        elif y:
            only_b += 1
        else:
            neither += 1
    return {
        "cases": len(a),
        "excluded": excluded,
        "both": both,
        "neither": neither,
        "only_a": only_a,
        "only_b": only_b,
        "p_value": round(exact_sign_test(only_a, only_b), 4),
    }


def repeat_stability(runs: Sequence[Sequence[Row]], metric: Metric) -> dict[str, Any]:
    """Several repeats of the same cases: per-case pass rate and flip rate, and the share of flaky cases.

    ``flip_rate`` of a case is the share of consecutive repeat pairs whose outcome differs; a case is flaky
    when it both passed and failed. Cases without a value in some repeat (cap-stopped) are left out."""
    if len(runs) < 2:
        raise ValueError("stability needs at least two repeats")
    tables = [_by_id(run, str(i + 1)) for i, run in enumerate(runs)]
    if any(t.keys() != tables[0].keys() for t in tables):
        raise ValueError("repeats hold different cases; not comparable")
    per_case: dict[str, dict[str, float]] = {}
    for case_id in tables[0]:
        outcomes = [metric(t[case_id]) for t in tables]
        if any(o is None for o in outcomes):
            continue
        passed = sum(bool(o) for o in outcomes)
        flips = sum(x != y for x, y in zip(outcomes, outcomes[1:], strict=False))
        per_case[case_id] = {
            "pass_rate": round(passed / len(outcomes), 3),
            "flip_rate": round(flips / (len(outcomes) - 1), 3),
        }
    flaky = sum(0 < v["pass_rate"] < 1 for v in per_case.values())
    return {
        "repeats": len(runs),
        "cases": len(per_case),
        "flaky_cases": flaky,
        "flaky_share": round(flaky / len(per_case), 3) if per_case else None,
        "per_case": per_case,
    }
