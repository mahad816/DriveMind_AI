"""Retrieval-only test: does the search put the right file in front of the model? No chat model.

    python -m evaluation.rag_eval.retrieval_probe [--split dev|test|all] [--phrasings] [--tag NAME]
                                                  [--threshold 0.2] [--top-k 8]

It runs the same call the agent's ``search_knowledge`` tool makes (``HybridRetriever.retrieve`` with
``candidate_limit=20``, one evidence section per returned chunk) against the isolated evaluation
store and reports, per case, whether a file the case expects is among the results and at which rank.
The only paid calls are query embeddings (a fraction of a cent for the whole set); a spend cap stops
it anyway.

What it measures, and what it does not:

* The query is the question text itself. The real agent writes its own query, so this is the best
  case for retrieval; the agent-level run (``cli run``) measures the rest.
* Cases with earlier turns (``history``) are skipped: their question is meaningless on its own.
* ``--phrasings`` repeats every English answerable question inside three common lead-ins, because
  real users do not phrase questions like the dataset does. A search whose ranking collapses under
  a lead-in is fragile, whatever its plain-question score.
* "Not in the files" cases cannot be scored by retrieval (something is always returned); they are
  reported for information, with the raw vector score, to show why no score cut-off can decide
  refusal.
"""

import argparse
import asyncio
import json
import statistics
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.retrieval.hybrid import HybridRetriever
from app.routing.intent_frame.execution import RetrievalRequest
from app.routing.intent_frame.scope import EligibleCollectionScope

from .corpus import messy_files, verify
from .dataset import files_to_check, load_cases, validate
from .frozen_corpus import FrozenCorpusError, corpus_for
from .index_verify import require_verified_index
from .meter import BudgetExceeded, CostMeter, cap_argument
from .runner import prepare_case
from .score import wilson
from .target import EVAL_USER_ID, eval_settings, session_factory, store_for

CANDIDATE_LIMIT = 20  # the search_knowledge tool's default
DATASETS = ("rag_v2_cases.json", "rag_v2_trap_cases.json")
MESSY_DATASETS = ("rag_v2_messy_cases.json",)
RESULTS = Path(__file__).resolve().parents[1] / "results"
ANSWERABLE = {"answer", "partial"}
REFUSAL = {"not_found", "decline_or_not_found", "correct_premise"}


@dataclass(frozen=True)
class Hit:
    """One retrieved chunk as the model would receive it."""

    filename: str
    vector_score: (
        float | None
    )  # raw cosine score, None when the chunk came from keyword/metadata only
    chunk_id: str | None = None  # the PostgreSQL chunk UUID: what passage-level metrics match on


Search = Callable[[str], Awaitable[list[Hit]]]


# ---- wording variants -----------------------------------------------------------------------------


def lower_first(question: str) -> str:
    """Lower-case the first word unless it is a name or acronym ("SMSGate", "INC-204", "I")."""
    head, _, rest = question.partition(" ")
    if len(head) > 1 and head[0].isupper() and head[1:].islower():
        return head.lower() + (" " + rest if rest else "")
    return question


PHRASINGS: dict[str, Callable[[str], str]] = {
    "plain": lambda q: q,
    "policy_document": lambda q: "In the company policy document, " + lower_first(q),
    "according_report": lambda q: "According to the report, " + lower_first(q),
    "which_file": lambda q: "Which file says this: " + q,
}


# ---- measuring (pure) -----------------------------------------------------------------------------


def measure(hits: Sequence[Hit], expected_names: Sequence[str]) -> dict[str, Any]:
    """Where do the expected files appear among the retrieved chunks?"""
    files = list(dict.fromkeys(h.filename for h in hits))  # distinct, in rank order
    wanted = set(expected_names)
    ranks = [files.index(name) + 1 for name in wanted if name in files]
    vector = [h.vector_score for h in hits if h.vector_score is not None]
    return {
        "chunks": len(hits),
        "distinct_files": len(files),
        "found": bool(ranks),
        "rank": min(ranks) if ranks else None,  # rank of the best expected file, 1 = first
        "found_all": bool(wanted) and len(ranks) == len(wanted),
        "top_vector_score": round(max(vector), 3) if vector else None,
        "files": files,
    }


def summarise_answerable(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {"n": 0}
    found = sum(r["found"] for r in rows)
    first = sum(r["rank"] == 1 for r in rows)
    low, high = wilson(found, n)
    multi = [r for r in rows if len(r["expected"]) > 1]
    return {
        "n": n,
        "found_in_results": found,
        "found_pct": round(100 * found / n, 1),
        "found_ci95_pct": [round(100 * low, 1), round(100 * high, 1)],
        "ranked_first": first,
        "mrr": round(sum(1 / r["rank"] for r in rows if r["rank"]) / n, 3),
        "multi_file_cases": len(multi),
        "multi_file_all_found": sum(r["found_all"] for r in multi),
        "mean_distinct_files": round(statistics.fmean(r["distinct_files"] for r in rows), 2),
        "single_file_results": sum(r["distinct_files"] == 1 and r["chunks"] > 1 for r in rows),
        "missed": sorted(r["id"] for r in rows if not r["found"]),
    }


def summarise_refusal(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    scores = [r["top_vector_score"] for r in rows if r["top_vector_score"] is not None]
    return {
        "n": len(rows),
        "with_any_result": sum(r["chunks"] > 0 for r in rows),
        "top_vector_score_median": round(statistics.median(scores), 3) if scores else None,
        "top_vector_score_max": max(scores) if scores else None,
    }


# ---- running --------------------------------------------------------------------------------------


def split_cases(
    cases: Sequence[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(answerable, refusal) cases that can be tested on the question alone."""
    usable = [c for c in cases if not c.get("history")]
    answerable = [c for c in usable if c["expected_behavior"] in ANSWERABLE and c["expected_files"]]
    refusal = [c for c in usable if c["expected_behavior"] in REFUSAL]
    return answerable, refusal


def expected_names(case: dict[str, Any]) -> list[str]:
    return [path.rsplit("/", 1)[-1] for path in case["expected_files"]]


async def probe(
    search: Search,
    cases: Sequence[dict[str, Any]],
    phrasings: Sequence[str],
    plain_hits: dict[str, list[Hit]] | None = None,
) -> dict[str, Any]:
    """``plain_hits``, when given, receives the chunks of every plain-question search by case id (answerable
    and refusal cases), so passage metrics need no second search and no second embedding call."""
    answerable, refusal = split_cases(cases)
    rows: dict[str, list[dict[str, Any]]] = {name: [] for name in phrasings}
    for name in phrasings:
        for case in answerable:
            if name != "plain" and case.get("language", "en") != "en":
                continue  # the lead-ins are English
            hits = await search(PHRASINGS[name](case["question"]))
            if plain_hits is not None and name == "plain":
                plain_hits[case["id"]] = hits
            rows[name].append(
                {
                    "id": case["id"],
                    "split": case["split"],
                    "expected": expected_names(case),
                    **measure(hits, expected_names(case)),
                }
            )
    refusal_rows = []
    for c in refusal:
        hits = await search(c["question"])
        if plain_hits is not None:
            plain_hits[c["id"]] = hits
        refusal_rows.append({"id": c["id"], **measure(hits, [])})
    return {
        "answerable": {name: summarise_answerable(r) for name, r in rows.items()},
        "refusal_cases": summarise_refusal(refusal_rows),
        "rows": rows,
        "refusal_rows": refusal_rows,
    }


def make_search(retriever: HybridRetriever) -> Search:
    async def search(query: str) -> list[Hit]:
        request = RetrievalRequest(
            user_id=EVAL_USER_ID,
            query=query,
            scope=EligibleCollectionScope(),
            candidate_limit=CANDIDATE_LIMIT,
        )
        chunks = await retriever.retrieve(request)
        return [Hit(c.filename, c.source_scores.get("vector"), str(c.chunk_id)) for c in chunks]

    return search


async def run(args: argparse.Namespace) -> None:
    try:
        # Legacy: the store must hold the messy documents too (cli setup --with-messy). Frozen: it holds them already.
        files = corpus_for(frozen=args.frozen, with_messy=args.messy)
    except FrozenCorpusError as exc:
        raise SystemExit(f"STOPPED: {exc}") from exc
    verify(files)
    total = len(files)
    # The messy questions only name messy documents; checking them against those alone avoids reading
    # (and slowly extracting) every public PDF just to validate.
    checked = messy_files() if args.messy else files
    cases: list[dict[str, Any]] = []
    for name in MESSY_DATASETS if args.messy else DATASETS:
        dataset = load_cases(name)
        # The frozen corpus has 33 public PDFs: read only the ones a case points at.
        problems = validate(dataset, files_to_check(dataset, files) if args.frozen else checked)
        if problems:
            raise SystemExit(f"{name} is invalid:\n" + "\n".join(problems))
        cases += [prepare_case(c, total) for c in dataset["cases"]]
    if args.split != "all":
        cases = [c for c in cases if c["split"] == args.split]

    updates: dict[str, Any] = {}
    if args.threshold is not None:
        updates["retrieval_score_threshold"] = args.threshold
    if args.relative is not None:
        updates["retrieval_relative_threshold"] = args.relative
    if args.top_k is not None:
        updates["retrieval_top_k"] = args.top_k
    store = store_for(frozen=args.frozen, name=args.store)
    if args.frozen:
        # Before any embedding call: the store must hold exactly the verified frozen corpus.
        base = (await require_verified_index(store, tool_agent=True)).settings
    else:
        base = eval_settings(tool_agent=True, store=store)
    settings: Settings = base.model_copy(update=updates)
    names = list(PHRASINGS) if args.phrasings else ["plain"]
    meter = CostMeter(args.cap)
    sessions = session_factory(settings)
    plain_hits: dict[str, list[Hit]] = {}
    try:
        with meter.installed():
            async with sessions() as db:
                report = await probe(
                    make_search(HybridRetriever(db, settings)), cases, names, plain_hits
                )
    except BudgetExceeded as exc:
        raise SystemExit(f"STOPPED: {exc}") from exc
    if args.passage:
        # Free: database reads only. The hits are the plain-question searches already made above.
        from .passage_metrics import passage_section  # late: that module imports this one

        report["passage"] = await passage_section(
            sessions, cases, files, plain_hits, top_k=settings.retrieval_top_k
        )
    report["settings"] = {
        "retrieval_score_threshold": settings.retrieval_score_threshold,
        "retrieval_top_k": settings.retrieval_top_k,
        "retrieval_relative_threshold": settings.retrieval_relative_threshold,
        "split": args.split,
        "candidate_limit": CANDIDATE_LIMIT,
    }
    report["spend"] = meter.summary()
    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    path = RESULTS / f"retrieval_probe_{stamp}{'_' + args.tag if args.tag else ''}.json"
    path.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print_report(report, path.name)


def print_report(report: dict[str, Any], filename: str) -> None:
    s = report["settings"]
    print(
        f"retrieval probe  split={s['split']}  cut-off={s['retrieval_score_threshold']}  "
        f"relative={s['retrieval_relative_threshold']}  top-k={s['retrieval_top_k']}  -> {filename}"
    )
    print("(query = the question text; the real agent writes its own)\n")
    header = f"{'wording':18s} {'cases':>5s} {'found':>11s} {'ranked 1st':>11s} {'MRR':>6s} {'files/res':>9s}"
    print(header)
    for name, a in report["answerable"].items():
        if not a["n"]:
            continue
        print(
            f"{name:18s} {a['n']:5d} {a['found_in_results']:4d} ({a['found_pct']:4.1f}%) "
            f"{a['ranked_first']:11d} {a['mrr']:6.2f} {a['mean_distinct_files']:9.2f}"
        )
        if a["missed"]:
            print(f"{'':18s} missed: {', '.join(a['missed'])}")
    r = report["refusal_cases"]
    print(
        f"\nnot-in-the-files cases: {r['n']}, {r['with_any_result']} still return chunks; "
        f"top vector score median {r['top_vector_score_median']}, max {r['top_vector_score_max']}"
    )
    if "passage" in report:
        from .passage_metrics import print_passage

        print_passage(report["passage"])
    print("spend:", report["spend"]["estimated_total_usd"], "USD")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--split", choices=["dev", "test", "all"], default="all")
    parser.add_argument(
        "--messy",
        action="store_true",
        help="probe the messy question set instead (the store needs cli setup --with-messy)",
    )
    parser.add_argument(
        "--frozen",
        action="store_true",
        help="the store holds the complete frozen M1 corpus (cli setup --frozen)",
    )
    parser.add_argument(
        "--store",
        help="with --frozen: the evaluation store to measure (default v3; it must verify)",
    )
    parser.add_argument(
        "--phrasings", action="store_true", help="also test the three lead-in wordings"
    )
    parser.add_argument(
        "--passage",
        action="store_true",
        help="also report passage-level metrics (anchor-chunk recall, rank, MRR) from the same searches; "
        "development and regression pools only, never held-out",
    )
    parser.add_argument("--threshold", type=float, help="override retrieval_score_threshold")
    parser.add_argument(
        "--relative",
        type=float,
        help="override retrieval_relative_threshold (fraction of best hit)",
    )
    parser.add_argument("--top-k", type=int, help="override retrieval_top_k")
    parser.add_argument("--tag", help="suffix for the result file name")
    parser.add_argument(
        "--cap",
        type=cap_argument,
        required=True,
        help="hard spend cap in USD (required, no default)",
    )
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
