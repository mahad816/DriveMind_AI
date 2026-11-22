"""Aggregate-only reporting for the sealed held-out pool.

The held-out cases are written once, kept outside the repository, and scored once per checkpoint. Anything a
run prints, logs, summarises or commits may show that pool only as a total plus the gate groups, and no cell
with fewer than ``MIN_CELL`` cases, so a small group cannot disclose a single case. ``summarise`` calls
``sealed_summary`` for any row whose pool is held-out, so no caller has to remember to.

    sealed_summary(rows)   the only view of held-out rows a summary, a log or a committed file may carry
    reduce_row(row)        a row without reply, question, queries or snippets (outside-the-repo rows and the
                           committed baseline)
    committed_view(rows)   development and regression rows reduced, held-out rows as the sealed summary only
    leaks(text, ids)       held-out case ids found in a text (a committed output must have none)
    small_cells(value)     cells under MIN_CELL found in a summary (a committed output must have none)

Known limit: the groups overlap and a total is shown, so a reader holding a group's rate and the other groups'
rates could infer something about a cell by subtraction. Cells are suppressed individually, not as a set.
"""

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .score import rates

MIN_CELL = 10
HELD_OUT_POOL = "held_out"
# Keys a reduced row keeps. Strings survive only under these names (identifiers and enum values, never text a
# case author or the model wrote); the lists of strings are file names, gate names and tool names.
KEEP_STRINGS = frozenset(
    {
        "id",
        "category",
        "pool",
        "split",
        "language",
        "expected_behavior",
        "format",
        "status",
        "error",
        "outcome",
        "outcome_group",
        "abstention",
        "primary",
        "path",
        "claim_support",
    }
)
KEEP_STRING_LISTS = frozenset({"cited_files", "gates", "tool_names"})
DROP = frozenset({"reply", "question", "cited", "trace", "agent_queries", "reference_answer"})


def is_held_out(row: Mapping[str, Any]) -> bool:
    return row.get("pool") == HELD_OUT_POOL


def _suppressed() -> dict[str, Any]:
    return {"suppressed": f"fewer than {MIN_CELL} cases"}


def _rate(rows: list[Mapping[str, Any]], key: str, flag: str) -> dict[str, Any]:
    """A rate over the rows where the stage applies; suppressed when fewer than ``MIN_CELL`` rows count (an
    undecided strict verdict leaves a row out, so a rate can rest on fewer cases than its cell holds)."""
    value = rates(rows, key, flag)  # type: ignore[arg-type]
    return value if value["n"] >= MIN_CELL else _suppressed()


def _cell(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    listed = list(rows)
    return {
        "n": len(listed),
        "errors": sum(1 for r in listed if r.get("error")),
        "legacy": _rate(listed, "overall", "pass"),
        "strict": _rate(listed, "strict", "deterministic"),
    }


def sealed_summary(all_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Total plus one cell per gate group, a cell shown only when it holds at least ``MIN_CELL`` cases."""
    rows = [r for r in all_rows if not r.get("cap_stopped")]
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        for name in row.get("gates") or []:
            if name != "total":
                groups[name].append(row)
    return {
        "pool": HELD_OUT_POOL,
        "cases": len(all_rows),
        "cap_stopped": len(all_rows) - len(rows),
        "incomplete": len(all_rows) > len(rows),
        "total": _cell(rows) if len(rows) >= MIN_CELL else _suppressed(),
        "groups": {
            name: _cell(members) if len(members) >= MIN_CELL else _suppressed()
            for name, members in sorted(groups.items())
        },
    }


def _scrub(key: str, value: Any) -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, int | float):
        return value
    if isinstance(value, str):
        return value if key in KEEP_STRINGS else None
    if isinstance(value, dict):
        return {k: _scrub(k, v) for k, v in value.items() if k not in DROP}
    if isinstance(value, list):
        if key in KEEP_STRING_LISTS:
            return [v for v in value if isinstance(v, str)]
        return [_scrub(key, v) for v in value if not isinstance(v, str)]
    return None


def reduce_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """A row with no reply, question, agent query, citation snippet or trace, and no free text: strings survive
    only under ``KEEP_STRINGS``. What remains is outcomes, citations by file name, counts, tokens, cost, latency."""
    return {k: _scrub(k, v) for k, v in row.items() if k not in DROP}


def committed_view(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """What a committed baseline may hold: per-case rows for development and regression, and nothing per case
    for held-out (its sealed summary only)."""
    kept = [reduce_row(r) for r in rows if not is_held_out(r)]
    held = [r for r in rows if is_held_out(r)]
    return {"rows": kept, "held_out": sealed_summary(held) if held else None}


def leaks(text: str, held_out_ids: Iterable[str]) -> list[str]:
    """Held-out case ids that appear in a text, matched as whole tokens."""
    return [
        case_id
        for case_id in held_out_ids
        if re.search(rf"(?<![\w-]){re.escape(case_id)}(?![\w-])", text)
    ]


def small_cells(value: Any, path: str = "") -> list[str]:
    """Paths of cells that report a count from 1 to ``MIN_CELL - 1`` (a suppressed cell has no ``n``)."""
    found: list[str] = []
    if isinstance(value, dict):
        n = value.get("n")
        if isinstance(n, int) and not isinstance(n, bool) and 0 < n < MIN_CELL:
            found.append(path or "<root>")
        for key, child in value.items():
            found += small_cells(child, f"{path}/{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found += small_cells(child, f"{path}[{index}]")
    return found
