"""A against C2: the model's query alone against the model's query plus the user's own question, round-robin.

    python -m evaluation.rag_eval.dual_query_probe --plan [--split dev|regression|all] [--from-results NAME ...]
    python -m evaluation.rag_eval.dual_query_probe --cap USD [--split ...] [--passage] [--tag NAME]

Ticket: docs/tickets/hybrid-retrieval-comparison/01-fusion-and-query-source-comparison.md. No chat model is called.
The only paid calls are query embeddings, and the run refuses to start above ``--cap``.

* Query source: the model-written queries already stored in frozen first-step result files (read only, never
  changed). For each case the first query of the lowest repeat that searched; nothing is generated here.
* Cases: English, answerable, no earlier turn (``baseline_eligible``), development and/or regression. Roman Urdu and
  held-out cases never enter. A case whose stored runs never searched is a **routing failure**: listed apart, in
  neither arm's denominator. A case with no stored run is listed as ``no_stored_run``. Both arms score the same
  ``searched`` cases.
* Arm A runs the control, ``HybridRetriever.retrieve`` with the model's query. Arm C2 runs ``retrieve_dual`` with the
  same request and the case question. Their order alternates by case so neither always runs on a warmer cache.
  Each arm's latency is measured on its own call. Embedding calls are derived, not read from the provider: 1 for A,
  and ``retrieve_dual``'s own count (one per search) for C2; the meter's run total is the only measured cost.
* Reported per pool: recall at 1 and at 8, file-level MRR (``summarise_answerable``), passage recall with
  ``--passage``, every case that flips between hit and miss (by id), rank changes, top-8 overlap, latency, embedding
  calls and cost.
"""

import argparse
import asyncio
import json
import statistics
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.types import RetrievedChunk
from app.routing.intent_frame.execution import RetrievalRequest
from app.routing.intent_frame.scope import EligibleCollectionScope

from .cli import report_plan
from .corpus import verify
from .first_step_probe import (
    SKIPPED_CATEGORIES,
    baseline_eligible,
    case_kind,
    unique_path,
    write_json_atomic,
)
from .frozen_corpus import FrozenCorpusError, corpus_for
from .index_verify import require_verified_index
from .manifest import git_state
from .meter import BudgetExceeded, CostMeter, cap_argument, refuse_over_cap
from .pools import pool_of
from .probe_pools import check_first_step_mode, plan_probe, select_probe_cases
from .retrieval_probe import (
    CANDIDATE_LIMIT,
    RESULTS,
    Hit,
    expected_names,
    measure,
    summarise_answerable,
)
from .review_gate import sha256_file
from .stats import paired_comparison
from .target import EVAL_USER_ID, application_defaults, session_factory, store_for

# The two frozen first-step runs of M1-08-G (development, regression). Read only.
DEFAULT_RESULT_FILES = (
    "first_step_20261123_170220_G_dev.json",
    "first_step_20261123_171737_G_regression.json",
)
SPLITS = ("dev", "regression", "all")


@dataclass(frozen=True)
class StoredQuery:
    query: str
    source: str  # result file name
    repeat: int


def load_stored_queries(
    paths: Sequence[Path],
) -> tuple[dict[str, StoredQuery], list[str]]:
    """Case id -> the stored model query, and the ids whose stored runs never searched (routing failures).

    The query of a case is the first query of its lowest repeat whose first tool was ``search_knowledge``.
    Only complete first-step files are used. A case is a routing failure when it has stored model rows and none
    of them searched.
    """
    queries: dict[str, StoredQuery] = {}
    seen: set[str] = set()
    for path in paths:
        report = json.loads(path.read_text(encoding="utf-8"))
        if report.get("status") != "complete" or not report.get("complete"):
            raise SystemExit(f"STOPPED: {path.name} is not a complete first-step result; not used.")
        for row in sorted(report.get("rows", []), key=lambda r: (r["id"], r["repeat"])):
            seen.add(row["id"])
            if row["id"] in queries or row.get("tool") != "search_knowledge" or not row["queries"]:
                continue
            queries[row["id"]] = StoredQuery(row["queries"][0], path.name, row["repeat"])
    return queries, sorted(seen - queries.keys())


def result_paths(names: Sequence[str]) -> list[Path]:
    """Result files by bare name inside the results folder only: no path, no sealed or other location."""
    paths = []
    for name in names:
        if Path(name).name != name or not name.endswith(".json"):
            raise SystemExit(f"STOPPED: --from-results takes bare result file names, got {name!r}.")
        path = RESULTS / name
        if not path.is_file():
            raise SystemExit(f"STOPPED: {name} does not exist in the results folder.")
        paths.append(path)
    return paths


def ineligible_reason(case: Mapping[str, Any]) -> str | None:
    """Why an English case is not searched with its own question, or None if it is eligible.

    Mirrors ``baseline_eligible`` (the established rule); a test pins the two together."""
    if case["category"] in SKIPPED_CATEGORIES:
        return "chitchat"
    if case_kind(dict(case)) != "content":
        return "inventory_question"
    if case.get("history"):
        return "earlier_turns"
    if not expected_names(dict(case)):
        return "no_expected_file"
    return None


def partition_cases(
    cases: Sequence[dict[str, Any]],
    queries: Mapping[str, StoredQuery],
    routing_failures: Sequence[str],
) -> dict[str, Any]:
    """Every selected case in exactly one partition: scored, routing failure, no stored run, unsupported language
    or ineligible (with its reason). Raises if an id repeats or a case is lost."""
    ids = [c["id"] for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case ids in the selected pools")
    english = [c for c in cases if c.get("language") == "en"]
    eligible = [c for c in english if baseline_eligible(c)]
    failed = set(routing_failures)
    searched = [c for c in eligible if c["id"] in queries]
    parts: dict[str, Any] = {
        "searched": searched,
        # Scored, but their query comes from a repeat after the first (the first step of repeat 1 did not search).
        # The earlier standalone experiment took repeat 1 only, so these are the cases it counted as routing failures.
        "queries_from_later_repeat": sorted(
            c["id"] for c in searched if queries[c["id"]].repeat != 1
        ),
        "routing_failures": sorted(c["id"] for c in eligible if c["id"] in failed),
        "no_stored_run": sorted(
            c["id"] for c in eligible if c["id"] not in queries and c["id"] not in failed
        ),
        "excluded_unsupported_language": sorted(
            c["id"] for c in cases if c.get("language") != "en"
        ),
        "excluded_ineligible": {
            c["id"]: ineligible_reason(c) or "eligible"
            for c in sorted(english, key=lambda c: c["id"])
            if not baseline_eligible(c)
        },
    }
    check_accounting(cases, parts)
    return parts


def check_accounting(cases: Sequence[Mapping[str, Any]], parts: Mapping[str, Any]) -> None:
    """Refuse unless every selected case is in exactly one partition."""
    flat = [
        *(c["id"] for c in parts["searched"]),
        *parts["routing_failures"],
        *parts["no_stored_run"],
        *parts["excluded_unsupported_language"],
        *parts["excluded_ineligible"],
    ]
    if len(flat) != len(set(flat)) or sorted(flat) != sorted(c["id"] for c in cases):
        raise ValueError("selected cases are not each accounted for exactly once")


def accounting_summary(parts: Mapping[str, Any], selected: int) -> dict[str, Any]:
    """Counts per partition; they add up to ``selected``."""
    reasons: dict[str, int] = {}
    for reason in parts["excluded_ineligible"].values():
        reasons[reason] = reasons.get(reason, 0) + 1
    return {
        "selected_cases": selected,
        "scored": len(parts["searched"]),
        "routing_failures": len(parts["routing_failures"]),
        "no_stored_run": len(parts["no_stored_run"]),
        "excluded_unsupported_language": len(parts["excluded_unsupported_language"]),
        "excluded_ineligible": dict(sorted(reasons.items())),
    }


def hits_of(chunks: Sequence[RetrievedChunk]) -> list[Hit]:
    return [Hit(c.filename, c.source_scores.get("vector"), str(c.chunk_id)) for c in chunks]


def arm_row(
    case: Mapping[str, Any], hits: Sequence[Hit], *, latency_ms: float, embeddings: int
) -> dict[str, Any]:
    names = expected_names(dict(case))
    files = list(dict.fromkeys(h.filename for h in hits))
    return {
        "id": case["id"],
        "pool": pool_of(case),
        "expected": names,
        **{k: v for k, v in measure(hits, names).items() if k != "files"},
        "files": files,
        "chunk_ids": [h.chunk_id for h in hits],
        "chunk_files": [h.filename for h in hits],
        "latency_ms": round(latency_ms, 2),
        "embedding_calls": embeddings,
    }


def top8_overlap(a_ids: Sequence[str | None], c2_ids: Sequence[str | None]) -> float:
    """Share of A's chunks that C2 also returns (1.0 when A returned nothing and neither did C2)."""
    if not a_ids:
        return 1.0 if not c2_ids else 0.0
    return len(set(a_ids) & set(c2_ids)) / len(set(a_ids))


def compare_arms(
    a_rows: Sequence[dict[str, Any]], c2_rows: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    """Per-case movement of C2 against A on the same case ids (raises when the ids differ)."""
    paired = paired_comparison(a_rows, c2_rows, lambda r: bool(r["found"]))
    a = {r["id"]: r for r in a_rows}
    b = {r["id"]: r for r in c2_rows}
    gained = sorted(i for i in a if not a[i]["found"] and b[i]["found"])
    lost = sorted(i for i in a if a[i]["found"] and not b[i]["found"])
    up, down = [], []
    for i in a:
        ra, rb = a[i]["rank"], b[i]["rank"]
        if ra and rb and rb < ra:
            up.append(i)
        elif ra and rb and rb > ra:
            down.append(i)
    overlaps = [top8_overlap(a[i]["chunk_ids"], b[i]["chunk_ids"]) for i in a]
    return {
        "cases": len(a),
        "paired_hit_at_8": paired,
        "gained_by_c2": gained,
        "lost_by_c2": lost,
        "rank_improved_ids": sorted(up),
        "rank_worsened_ids": sorted(down),
        "top8_overlap_mean": round(statistics.fmean(overlaps), 3) if overlaps else None,
        "top8_a_fully_retained_cases": sum(o == 1.0 for o in overlaps),
    }


def arm_summary(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    out = summarise_answerable(list(rows))
    if rows:
        latencies = sorted(r["latency_ms"] for r in rows)
        out |= {
            "latency_ms_mean": round(statistics.fmean(latencies), 1),
            "latency_ms_median": round(statistics.median(latencies), 1),
            "latency_ms_max": latencies[-1],
            "embedding_calls": sum(r["embedding_calls"] for r in rows),
        }
    return out


def pool_reports(
    a_rows: Sequence[dict[str, Any]], c2_rows: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    """Per pool: both arms' summaries and the case-by-case comparison, over the rows given."""
    out: dict[str, Any] = {}
    for pool in sorted({r["pool"] for r in a_rows}):
        a_pool = [r for r in a_rows if r["pool"] == pool]
        c_pool = [r for r in c2_rows if r["pool"] == pool]
        out[pool] = {
            "A": arm_summary(a_pool),
            "C2": arm_summary(c_pool),
            "comparison": compare_arms(a_pool, c_pool),
        }
    return out


def plan_dual(
    searched: Sequence[dict[str, Any]],
    queries: Mapping[str, StoredQuery],
    *,
    embedding_model: str,
    cap: float,
    split: str,
) -> dict[str, Any]:
    """Free estimate. Arm A embeds the model query; C2 embeds the question and the model query (once when equal)."""
    texts: list[str] = []
    for case in searched:
        model_query = queries[case["id"]].query
        texts.append(model_query)  # arm A
        texts.append(model_query)  # arm C2, primary
        if case["question"].strip() != model_query.strip():
            texts.append(case["question"])  # arm C2, original question
    return plan_probe(texts, embedding_model, cap=cap, split=split) | {"cases": len(searched)}


def timed(started: float) -> float:
    return (time.perf_counter() - started) * 1000


async def measure_case(
    retriever: HybridRetriever, case: Mapping[str, Any], model_query: str, *, a_first: bool
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    request = RetrievalRequest(
        user_id=EVAL_USER_ID,
        query=model_query,
        scope=EligibleCollectionScope(),
        candidate_limit=CANDIDATE_LIMIT,
    )

    async def arm_a() -> tuple[list[RetrievedChunk], float]:
        started = time.perf_counter()
        chunks = await retriever.retrieve(request)
        return chunks, timed(started)

    async def arm_c2() -> tuple[Any, float]:
        started = time.perf_counter()
        found = await retriever.retrieve_dual(request, case["question"])
        return found, timed(started)

    if a_first:
        a_chunks, a_ms = await arm_a()
        dual, c2_ms = await arm_c2()
    else:
        dual, c2_ms = await arm_c2()
        a_chunks, a_ms = await arm_a()
    a_row = arm_row(case, hits_of(a_chunks), latency_ms=a_ms, embeddings=1)
    c2_row = arm_row(
        case, hits_of(dual.chunks), latency_ms=c2_ms, embeddings=dual.embedding_calls
    ) | {"degraded_reason": dual.degraded_reason, "skipped_reason": dual.skipped_reason}
    # The model list C2 used should equal what arm A just returned; a difference is non-determinism, reported.
    same = [c.chunk_id for c in dual.model_chunks] == [c.chunk_id for c in a_chunks]
    return a_row, c2_row, same


def settings_record(
    settings: Settings, args: argparse.Namespace, manifest: str, store: str
) -> dict[str, Any]:
    return {
        "split": args.split,
        "store": store,
        "index_manifest": manifest,
        "embedding_model": settings.embedding_model,
        "candidate_limit": CANDIDATE_LIMIT,
        "retrieval_top_k": settings.retrieval_top_k,
        "retrieval_score_threshold": settings.retrieval_score_threshold,
        "retrieval_relative_threshold": settings.retrieval_relative_threshold,
        "retrieval_max_chunks_per_file": settings.retrieval_max_chunks_per_file,
        "hybrid_weights": [
            settings.hybrid_weight_vector,
            settings.hybrid_weight_keyword,
            settings.hybrid_weight_metadata,
        ],
        "hybrid_rrf_k": settings.hybrid_rrf_k,
        "evidence_min_fusion_score": settings.evidence_min_fusion_score,
        "strategies": {
            "A": "retrieve(model query)",
            "C2": "retrieve_dual(model query, case question): round-robin, original question first",
        },
        "query_source": "stored model-written first-step queries (frozen result files)",
        "chat_model_called": False,
    }


async def run(args: argparse.Namespace) -> None:
    check_first_step_mode(args.split, frozen=True, mode="baseline", repeats=1)  # refuses held-out
    paths = result_paths(args.from_results)
    queries, routing_failures = load_stored_queries(paths)
    try:
        files = corpus_for(frozen=True, with_messy=False)
    except FrozenCorpusError as exc:
        raise SystemExit(f"STOPPED: {exc}") from exc
    verify(files)
    cases, _sealed = select_probe_cases(args.split, files)
    parts = partition_cases(cases, queries, routing_failures)
    searched = parts["searched"]
    defaults = application_defaults()
    plan = plan_dual(
        searched,
        queries,
        embedding_model=defaults["embedding_model"],
        cap=args.cap,
        split=args.split,
    ) | {k: len(v) for k, v in parts.items() if k != "searched"}
    accounting = accounting_summary(parts, len(cases))
    plan["accounting"] = accounting
    if args.plan:
        report_plan(plan, args.cap)
        print(
            "Left out (listed by id in the report): routing failures "
            f"{parts['routing_failures']}; no stored run {parts['no_stored_run']}; "
            f"unsupported language {parts['excluded_unsupported_language']}."
        )
        print(
            f"Not eligible (English, listed by id with reason in the report): {accounting['excluded_ineligible']}."
        )
        print(f"Accounting: {accounting}")
        by_pool_count: dict[str, int] = {}
        for case in searched:
            by_pool_count[pool_of(case)] = by_pool_count.get(pool_of(case), 0) + 1
        print(
            f"Scored cases by pool: {by_pool_count}. Query taken from a later repeat (counted as a routing "
            f"failure by the earlier experiment, which used repeat 1 only): {parts['queries_from_later_repeat']}."
        )
        return
    refuse_over_cap(plan["estimated_usd"], args.cap)

    store = store_for(frozen=True, name=args.store)
    verified = await require_verified_index(store, tool_agent=True)
    settings = verified.settings
    meter = CostMeter(args.cap)
    sessions = session_factory(settings)
    a_rows: list[dict[str, Any]] = []
    c2_rows: list[dict[str, Any]] = []
    model_list_differs: list[str] = []
    header = {
        "git": git_state(),
        "settings": settings_record(settings, args, verified.manifest, store.database),
        "query_source_files": {p.name: sha256_file(p) for p in paths},
        "plan": plan,
        "cases": {
            "searched_ids": [c["id"] for c in searched],
            **{k: v for k, v in parts.items() if k != "searched"},
        },
    }
    RESULTS.mkdir(exist_ok=True)
    stem = f"dual_query_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}{'_' + args.tag if args.tag else ''}"
    try:
        with meter.installed():
            async with sessions() as db:
                retriever = HybridRetriever(db, settings)
                for index, case in enumerate(searched):
                    a_row, c2_row, same = await measure_case(
                        retriever, case, queries[case["id"]].query, a_first=index % 2 == 0
                    )
                    a_row["query_repeat"] = c2_row["query_repeat"] = queries[case["id"]].repeat
                    a_rows.append(a_row)
                    c2_rows.append(c2_row)
                    if not same:
                        model_list_differs.append(case["id"])
    except (Exception, BudgetExceeded, KeyboardInterrupt, asyncio.CancelledError) as exc:
        saved = unique_path(RESULTS, stem + "_incomplete")
        write_json_atomic(
            saved,
            {
                **header,
                "status": "incomplete",
                "complete": False,
                "reason": type(exc).__name__,
                "spend": meter.summary(),
                "a_rows": a_rows,
                "c2_rows": c2_rows,
            },
        )
        print(
            f"STOPPED ({type(exc).__name__}): rows so far saved in {saved.name}; not a result.",
            file=sys.stderr,
        )
        raise
    report: dict[str, Any] = {
        **header,
        "status": "rows_only",
        "complete": False,
        "spend": meter.summary(),
        "a_rows": a_rows,
        "c2_rows": c2_rows,
        "model_list_differs_from_arm_a": model_list_differs,
    }
    path = unique_path(RESULTS, stem)
    write_json_atomic(path, report)
    by_pool = pool_reports(a_rows, c2_rows)
    report["by_pool"] = by_pool
    if parts["queries_from_later_repeat"]:
        # The same comparison without the later-repeat cases: the denominator of the earlier standalone experiment.
        first_repeat = [r["query_repeat"] == 1 for r in a_rows]
        report["by_pool_repeat1_only"] = pool_reports(
            [r for r, keep in zip(a_rows, first_repeat, strict=True) if keep],
            [r for r, keep in zip(c2_rows, first_repeat, strict=True) if keep],
        )
    if args.passage:
        from .passage_metrics import passage_section

        report["passage"] = {
            arm: await passage_section(
                sessions,
                searched,
                files,
                {
                    r["id"]: [
                        Hit(f, None, cid)
                        for f, cid in zip(r["chunk_files"], r["chunk_ids"], strict=True)
                    ]
                    for r in rows
                },
                top_k=settings.retrieval_top_k,
                query=f"arm {arm}",
            )
            for arm, rows in (("A", a_rows), ("C2", c2_rows))
        }
    report["status"], report["complete"] = "complete", True
    write_json_atomic(path, report)
    print(json.dumps({"saved": path.name, "spend": report["spend"], "by_pool": by_pool}, indent=1))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--split", choices=SPLITS, default="all")
    parser.add_argument(
        "--from-results", nargs="+", default=list(DEFAULT_RESULT_FILES), metavar="NAME"
    )
    parser.add_argument("--store", default=None, help="frozen store name (default: v3)")
    parser.add_argument("--cap", type=cap_argument, required=True, help="spending cap in USD")
    parser.add_argument("--plan", action="store_true", help="free: print the plan and stop")
    parser.add_argument(
        "--passage", action="store_true", help="also report passage recall at 8 (free DB reads)"
    )
    parser.add_argument("--tag", default=None)
    return parser


def main() -> None:
    asyncio.run(run(build_parser().parse_args()))


if __name__ == "__main__":
    main()
