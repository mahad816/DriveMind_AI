"""Pool selection, the held-out gate and the free cost plan for the retrieval probe (M1-08-D).

The probe used to read two legacy case files. For the frozen corpus it now selects the named pools through the
loaders that already exist in ``pools.py`` and keeps every sealed-pool rule in one place:

    check_probe_mode      refuses a prohibited combination before anything is read or called
    select_probe_cases    development / regression / all from the committed set; held_out only through
                          ``pools.load_held_out`` (the Owner's review attestation, checked before the file is read)
    plan_probe            the free estimate: the exact queries, priced at the configured embedding model
    sealed_probe_report   the only view of held-out results: totals and gate groups, small cells suppressed
    write_sealed_report   writes it beside the sealed file, outside the repository

Nothing here calls the provider. The held-out pool is never tuned on: wordings, passage metrics and threshold
overrides are refused for it, and its per-case rows never leave memory.
"""

import json
import math
import statistics
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .cli import HELD_OUT_RESULTS
from .corpus import CorpusFile
from .dataset import HELD_OUT_SPLIT, files_to_check, validate
from .embedding_estimate import BYTES_PER_TOKEN, SAFETY_MARGIN
from .meter import PRICE_TABLE_DATE, price_for, require_prices
from .pools import (
    HELD_OUT_ENV,
    SPLIT_CHOICES,
    held_out_path,
    injection_files,
    load_held_out,
    load_question_set,
    select,
)
from .review_gate import ReviewRequired
from .runner import prepare_case
from .schema_v3 import gate_groups
from .score import wilson
from .sealing import MIN_CELL

POOL_SPLITS = {"regression", HELD_OUT_SPLIT}  # splits that exist only for the frozen corpus


def check_probe_mode(
    split: str,
    *,
    frozen: bool,
    messy: bool = False,
    phrasings: bool = False,
    passage: bool = False,
    overrides: Sequence[str] = (),
) -> None:
    """Exit with a plain reason when the combination is not allowed. Free; reads nothing."""
    if split not in SPLIT_CHOICES:
        raise SystemExit(
            f"STOPPED: unknown split {split!r}; choose one of {', '.join(SPLIT_CHOICES)}."
        )
    if split in POOL_SPLITS and not frozen:
        raise SystemExit(
            f"STOPPED: --split {split} needs --frozen (the pools exist only for the frozen corpus)."
        )
    if frozen and messy:
        raise SystemExit(
            "STOPPED: --frozen cannot be combined with --messy. The frozen corpus already holds the "
            "messy documents, and a frozen run probes the selected pool (--split), not the messy "
            "questions alone. Drop --messy, or drop --frozen for the legacy messy-only probe."
        )
    if split != HELD_OUT_SPLIT:
        return
    refused = [
        flag
        for flag, on in (("--phrasings", phrasings), ("--passage", passage), ("--messy", messy))
        if on
    ] + list(overrides)
    if refused:
        raise SystemExit(
            f"STOPPED: the held-out pool is measured once, with the plain question, at the settings "
            f"under test; it is never combined with {', '.join(refused)}."
        )


def _withheld(what: str, exc: BaseException) -> str:
    """A held-out failure reduced to what happened and its exception class; never the exception's text."""
    return f"STOPPED: {what} ({type(exc).__name__}); details withheld."


def select_probe_cases(
    split: str, files: Sequence[CorpusFile]
) -> tuple[list[dict[str, Any]], Path | None]:
    """The cases of ``split`` and, for the held-out pool, the sealed file they came from.

    ``all`` is development plus regression and never held-out. A held-out problem is counted, never described.
    """
    if split == HELD_OUT_SPLIT:
        # Only the fixed, content-free messages of the path and attestation checks are shown. Anything raised
        # while reading, validating or preparing the sealed cases may quote a case, so it is reduced to its
        # class name and chained to nothing.
        try:
            sealed = held_out_path()
        except (ValueError, FileNotFoundError) as exc:  # fixed messages: no case content
            raise SystemExit(f"STOPPED: {exc}") from None
        if sealed is None:
            raise SystemExit(
                f"STOPPED: set {HELD_OUT_ENV} to the sealed case file (outside the repository)."
            )
        try:
            dataset = load_held_out(sealed)  # the attestation is checked before the file is read
        except ReviewRequired as exc:  # fixed messages: no case content
            raise SystemExit(f"STOPPED: {exc}") from None
        except Exception as exc:
            raise SystemExit(_withheld("the held-out file could not be read", exc)) from None
        try:
            problems = validate(
                dataset, files_to_check(dataset, files), injection_files=injection_files()
            )
        except Exception as exc:
            raise SystemExit(_withheld("held-out validation failed", exc)) from None
        if problems:
            raise SystemExit(
                f"Held-out file invalid: {len(problems)} problem(s) (details withheld)."
            )
    else:
        sealed = None
        dataset = load_question_set()
        problems = validate(
            dataset, files_to_check(dataset, files), injection_files=injection_files()
        )
        if problems:
            raise SystemExit("The question set is invalid:\n" + "\n".join(problems))
    try:
        cases = [prepare_case(c, len(files)) for c in dataset["cases"]]
    except Exception as exc:
        if split != HELD_OUT_SPLIT:
            raise
        raise SystemExit(_withheld("the held-out cases could not be prepared", exc)) from None
    return select(cases, split), sealed


def plan_probe(queries: Sequence[str], model: str, *, cap: float, split: str) -> dict[str, Any]:
    """Free estimate: one embedding call per query, priced from the queries' own UTF-8 bytes (an upper bound,
    see ``embedding_estimate``) at the recorded input price of ``model``. Never edits the price table."""
    require_prices(model)
    price = price_for(model)["input"]
    raw = math.ceil(sum(len(q.encode()) for q in queries) / BYTES_PER_TOKEN)
    tokens = math.ceil(raw * SAFETY_MARGIN)
    usd = tokens * price / 1_000_000  # full precision: this is what the cap is compared with
    return {
        "split": split,
        "model": model,
        "embedding_calls": len(queries),
        "chat_calls": 0,
        "estimated_tokens": tokens,
        "price_usd_per_million_tokens": price,
        "price_table_date": PRICE_TABLE_DATE,
        "estimated_usd": usd,
        "within_cap": usd <= cap,
        "assumptions": [
            "one embedding call per search and no chat call (the probe stops before the model)",
            f"tokens are an upper bound of UTF-8 bytes / {BYTES_PER_TOKEN}, times {SAFETY_MARGIN}",
            f"input price of {model} from prices.json (checked {PRICE_TABLE_DATE}); the file is not edited",
        ],
    }


# ---- the sealed report ----------------------------------------------------------------------------------


def _suppressed() -> dict[str, Any]:
    return {"suppressed": f"fewer than {MIN_CELL} cases"}


def _cell(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    if n < MIN_CELL:
        return _suppressed()
    found = sum(bool(r["found"]) for r in rows)
    low, high = wilson(found, n)
    return {
        "n": n,
        "found": found,
        "found_pct": round(100 * found / n, 1),
        "found_ci95_pct": [round(100 * low, 1), round(100 * high, 1)],
        "ranked_first": sum(r["rank"] == 1 for r in rows),
        "mrr": round(sum(1 / r["rank"] for r in rows if r["rank"]) / n, 3),
    }


def _refusal_cell(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if len(rows) < MIN_CELL:
        return _suppressed()
    scores = [r["top_vector_score"] for r in rows if r["top_vector_score"] is not None]
    return {
        "n": len(rows),
        "with_any_result": sum(r["chunks"] > 0 for r in rows),
        "top_vector_score_median": round(statistics.median(scores), 3) if scores else None,
        "top_vector_score_max": max(scores) if scores else None,
    }


def sealed_probe_report(
    rows: Sequence[Mapping[str, Any]],
    refusal_rows: Sequence[Mapping[str, Any]],
    cases: Sequence[Mapping[str, Any]],
    *,
    skipped_history: int,
) -> dict[str, Any]:
    """Plain-question retrieval over the held-out pool as a total and one cell per gate group. A cell under
    ``MIN_CELL`` cases is suppressed. No id, question, file name or per-case value is carried."""
    by_id = {str(c["id"]): c for c in cases}
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        for name in gate_groups(by_id[str(row["id"])]) - {"total"}:
            groups.setdefault(name, []).append(row)
    return {
        "pool": HELD_OUT_SPLIT,
        "wording": "plain",
        "query": "the question text itself (an upper bound; the agent writes its own query)",
        "answerable": {
            "total": _cell(rows),
            "groups": {name: _cell(members) for name, members in sorted(groups.items())},
        },
        "refusal": _refusal_cell(refusal_rows),
        "skipped_history": skipped_history,
    }


def write_sealed_report(report: Mapping[str, Any], sealed: Path, stamp: str) -> Path:
    """Beside the sealed file (outside the repository), owner-readable only."""
    folder = sealed.parent / HELD_OUT_RESULTS
    folder.mkdir(exist_ok=True)
    path = folder / f"retrieval_probe_{stamp}_held_out.json"
    path.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    path.chmod(0o600)
    return path


def print_sealed(report: Mapping[str, Any], filename: str) -> None:
    held = report["held_out"]
    print(
        f"retrieval probe  pool=held_out  plain question  -> {filename} (outside the repository)\n"
    )
    total = held["answerable"]["total"]
    if "suppressed" in total:
        print(f"answerable: {total['suppressed']}")
    else:
        print(
            f"answerable: n={total['n']} found {total['found']} ({total['found_pct']}%) "
            f"ranked first {total['ranked_first']} MRR {total['mrr']}"
        )
    for name, cell in held["answerable"]["groups"].items():
        shown = (
            cell["suppressed"]
            if "suppressed" in cell
            else f"n={cell['n']} found {cell['found_pct']}%"
        )
        print(f"  {name:14s} {shown}")
    print("spend:", report["spend"]["estimated_total_usd"], "USD")
