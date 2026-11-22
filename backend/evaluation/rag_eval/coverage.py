"""Coverage of the question set against the minimums in docs/specs/m1-rag-evaluation.md ("Coverage minimums").

    uv run python -m evaluation.rag_eval.coverage [--require-held-out]

Free: it reads case files only. Prints counts per pool (counts, never case ids or results) and exits 1 when a
full-set minimum is unmet. ``--require-held-out`` also enforces the held-out minimums, which ticket 07 must meet.
Held-out counts come from the sealed file when ``DRIVEMIND_EVAL_HELDOUT_FILE`` points at it, otherwise from the
counts recorded in the freeze manifest.
"""

import json
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from .pools import FREEZE_MANIFEST, held_out_path, load_held_out, load_question_set
from .schema_v3 import evidence_files, gate_groups

MIN_INJECTION_DOCUMENTS = 3
MIN_INJECTION_FORMATS = 2
POOL_COLUMNS = ("development", "regression", "held_out")


@dataclass(frozen=True)
class Gate:
    key: str
    label: str
    minimum: int  # whole set
    held_out_minimum: int  # inside the held-out pool (0 = none stated)


GATES = (
    Gate("total", "cases in total", 300, 100),
    Gate("non_answer", "unanswerable + partial + false premise", 80, 30),
    Gate("critical", "tagged Critical failure", 30, 10),
    Gate("multi_file", "multi-file", 25, 8),
    Gate("table", "table lookup", 25, 0),
    Gate("calculation", "calculation", 20, 6),
    Gate("identifier", "identifier", 25, 6),
    Gate("follow_up", "follow-up (history inside the bound)", 15, 5),
    Gate("ambiguous", "ambiguous (clarify)", 10, 4),
    Gate("injection", "prompt injection", 10, 4),
    Gate("format_docx", "evidence in DOCX", 8, 3),
    Gate("format_xlsx", "evidence in XLSX", 8, 3),
    Gate("format_pptx", "evidence in PPTX", 8, 3),
    Gate("format_pdf", "evidence in text PDF", 8, 3),
    Gate("format_md", "evidence in Markdown", 8, 3),
    Gate("format_csv", "evidence in CSV", 8, 3),
    Gate("format_txt", "evidence in TXT", 8, 3),
)
GATE_KEYS = tuple(g.key for g in GATES)


def injection_documents(cases: Iterable[Mapping[str, Any]]) -> list[str]:
    """Corpus files that carry the embedded instruction in the injection cases (sorted, distinct)."""
    found: set[str] = set()
    for case in cases:
        if "injection" in _types(case):
            found.update(
                [case["injection_document"]]
                if case.get("injection_document")
                else evidence_files(case)
            )
    return sorted(found)


def _types(case: Mapping[str, Any]) -> set[str]:
    from .schema_v3 import case_types

    return case_types(case)


def count_cases(cases: Iterable[Mapping[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for case in cases:
        counts.update(gate_groups(case))
    return counts


def pool_counts(committed: Sequence[Mapping[str, Any]]) -> dict[str, Counter[str]]:
    by_pool: dict[str, list[Mapping[str, Any]]] = {name: [] for name in POOL_COLUMNS}
    for case in committed:
        by_pool[case["pool"]].append(case)
    return {name: count_cases(cases) for name, cases in by_pool.items()}


def recorded_held_out() -> dict[str, Any]:
    if not FREEZE_MANIFEST.exists():
        return {}
    held: dict[str, Any] = json.loads(FREEZE_MANIFEST.read_text()).get("held_out") or {}
    return held


def held_out_view() -> tuple[Counter[str], list[str], str]:
    """(counts per gate, injection documents, where the numbers came from)."""
    if held_out_path() is not None:
        cases = load_held_out(require_review=False)["cases"]
        return count_cases(cases), injection_documents(cases), "the sealed file"
    held = recorded_held_out()
    counts = Counter(held.get("gate_group_counts") or {})
    return counts, list(held.get("injection_documents") or []), "the freeze manifest"


def evaluate(
    counts: Mapping[str, Mapping[str, int]],
    injection_docs: Sequence[str],
    *,
    require_held_out: bool = False,
) -> list[str]:
    """Shortfalls, one line each. Full-set minimums always; held-out minimums only on request."""
    short = []
    for gate in GATES:
        total = sum(counts[name][gate.key] for name in POOL_COLUMNS)
        if total < gate.minimum:
            short.append(f"{gate.label}: {total} of {gate.minimum} needed")
        held = counts["held_out"][gate.key]
        if require_held_out and gate.held_out_minimum and held < gate.held_out_minimum:
            short.append(f"{gate.label} (held-out): {held} of {gate.held_out_minimum} needed")
    suffixes = {PurePosixPath(p).suffix for p in injection_docs}
    if len(injection_docs) < MIN_INJECTION_DOCUMENTS:
        short.append(
            f"injection documents: {len(injection_docs)} of {MIN_INJECTION_DOCUMENTS} needed"
        )
    if len(suffixes) < MIN_INJECTION_FORMATS:
        short.append(f"injection formats: {len(suffixes)} of {MIN_INJECTION_FORMATS} needed")
    return short


def render(
    counts: Mapping[str, Mapping[str, int]], injection_docs: Sequence[str], held_source: str
) -> str:
    rows: list[tuple[str, ...]] = [
        ("requirement", "min", "held", "dev", "regr", "held-out", "all", "")
    ]
    for gate in GATES:
        per = [counts[name][gate.key] for name in POOL_COLUMNS]
        total = sum(per)
        status = "" if total >= gate.minimum else "SHORT"
        rows.append(
            (gate.label, str(gate.minimum), str(gate.held_out_minimum or "-"))
            + tuple(str(n) for n in per)
            + (str(total), status)
        )
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    lines = [
        "  ".join(
            cell.ljust(w) if i in {0, 7} else cell.rjust(w)
            for i, (cell, w) in enumerate(zip(r, widths))
        ).rstrip()
        for r in rows
    ]
    suffixes = sorted({PurePosixPath(p).suffix.lstrip(".") for p in injection_docs})
    lines.append(
        f"injection documents: {len(injection_docs)} (need {MIN_INJECTION_DOCUMENTS}), "
        f"formats: {len(suffixes)} {suffixes} (need {MIN_INJECTION_FORMATS})"
    )
    lines.append(f"held-out counts come from {held_source}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    committed = load_question_set()["cases"]
    counts = pool_counts(committed)
    held_counts, held_docs, source = held_out_view()
    counts["held_out"] = held_counts
    docs = sorted({*injection_documents(committed), *held_docs})
    print(render(counts, docs, source))
    enforced = "--require-held-out" in args
    short = evaluate(counts, docs, require_held_out=enforced)
    for line in short:
        print("SHORT:", line)
    if not enforced:
        print(
            "held-out minimums NOT enforced: add --require-held-out for the full milestone requirements"
        )
    return 1 if short else 0


if __name__ == "__main__":
    raise SystemExit(main())
