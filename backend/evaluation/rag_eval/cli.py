"""Command line entry for the v2 evaluation.

    python -m evaluation.rag_eval.cli setup --cap USD   # create the isolated store and index the corpus
    python -m evaluation.rag_eval.cli rescore FILE --cap USD   # re-judge a saved run (same replies)
    python -m evaluation.rag_eval.cli run --cap USD --pipelines tool_agent legacy --split dev
        [--limit N] [--repeats N]

setup, run and rescore can reach the provider, so --cap (hard spend cap in USD) is required and
there is no default. Add --plan to print the planned calls and the estimate without calling anything
or writing a file; without it, a command whose estimate is above the cap refuses to start.

Requires the disposable PostgreSQL/Qdrant containers (see docs/EVALUATION_RESULTS.md) and an
OpenAI key in the environment or backend/.env. Never touches any non-``drivemind_eval`` store.
"""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .corpus import CorpusFile, messy_files, public_files, synthetic_files, verify
from .dataset import files_to_check, load_many, validate
from .judge import JUDGE_MODEL
from .manifest import build_manifest
from .meter import (
    ESTIMATES,
    BudgetExceeded,
    CostMeter,
    cap_argument,
    estimate_judge,
    estimate_run,
    require_prices,
    refuse_over_cap,
)
from .runner import (
    JUDGED,
    PIPELINES,
    extend_all,
    judge_row,
    pipeline_settings,
    prepare_case,
    run_pipeline,
    score_row,
)
from .score import summarise
from .target import ensure_database, eval_settings, ingest, migrate, session_factory


def corpus_files(*, with_messy: bool) -> list[CorpusFile]:
    """The evaluation corpus. The generated messy documents (DOCX, PPTX, XLSX, PDF) are added on request:
    a store that holds them gives different answers to the older datasets (five more files to confuse
    with), so they never join a run by accident."""
    files = synthetic_files() + public_files()
    return files + messy_files() if with_messy else files


MAX_REPEATS = 5


def positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be a whole number of at least 1")
    return value


def repeats_argument(text: str) -> int:
    value = positive_int(text)
    if value > MAX_REPEATS:
        raise argparse.ArgumentTypeError(f"at most {MAX_REPEATS} repeats per command")
    return value


def report_plan(plan: dict[str, Any], cap: float) -> None:
    print(
        json.dumps(
            {"plan": plan, "cap_usd": cap, "within_cap": plan["estimated_usd"] <= cap}, indent=1
        )
    )
    print(
        "Estimate from planning constants (prices.json), not a measurement. Nothing was called or written."
    )


async def setup(args: argparse.Namespace) -> None:
    files = corpus_files(with_messy=args.with_messy)
    verify(files)
    # Upper bound: every file embedded from scratch at 4 bytes per token; files already indexed cost nothing.
    megabytes = sum(f.absolute.stat().st_size for f in files) / 1_000_000
    plan = {
        "corpus_files": len(files),
        "megabytes": round(megabytes, 2),
        "calls": {"embedding_batches_at_most": len(files)},
        "estimated_usd": round(megabytes * ESTIMATES["setup_usd_per_mb_of_files"], 5),
    }
    if args.plan:
        report_plan(plan, args.cap)
        return
    refuse_over_cap(plan["estimated_usd"], args.cap)
    settings = eval_settings(tool_agent=False)
    require_prices(settings.embedding_model)
    await ensure_database()
    migrate(settings)
    meter = CostMeter(args.cap)
    try:
        with meter.installed():
            counts = await ingest(settings, files)
    except BudgetExceeded as exc:
        raise SystemExit(f"STOPPED: {exc}. Ask before spending more.") from exc
    print(json.dumps({"corpus_files": len(files), **counts, "spend": meter.summary()}, indent=1))


RESULTS = Path(__file__).resolve().parents[1] / "results"


async def run(args: argparse.Namespace) -> None:
    files = corpus_files(with_messy=args.with_messy)
    verify(files)
    dataset = load_many(args.dataset)
    problems = validate(dataset, files_to_check(dataset, files))
    if problems:
        raise SystemExit("Dataset invalid; refusing to spend money:\n" + "\n".join(problems))
    cases = [c for c in dataset["cases"] if args.split == "all" or c["split"] == args.split]
    if args.category:
        cases = [c for c in cases if c["category"] in args.category]
    if args.ids:
        cases = [c for c in cases if c["id"] in args.ids]
    cases = cases[: args.limit] if args.limit else cases
    if not cases:
        raise SystemExit("No cases selected; nothing to run.")
    judged = sum(c["expected_behavior"] in JUDGED for c in cases)
    plan = estimate_run(args.pipelines, len(cases), args.repeats, judged)
    if args.plan:
        report_plan(plan, args.cap)
        return
    refuse_over_cap(plan["estimated_usd"], args.cap)
    settings = eval_settings(chat_model=args.model)
    if args.no_claim_check:
        settings = settings.model_copy(update={"claim_check_enabled": False})
    overrides = {
        key: value
        for key, value in (
            ("retrieval_score_threshold", args.threshold),
            ("retrieval_relative_threshold", args.relative),
        )
        if value is not None
    }
    settings = settings.model_copy(update=overrides)
    require_prices(
        settings.chat_model, settings.claim_check_model, settings.embedding_model, JUDGE_MODEL
    )
    meter = CostMeter(args.cap)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    RESULTS.mkdir(exist_ok=True)
    stopped = None
    try:
        with meter.installed():
            for repeat in range(1, args.repeats + 1):
                for pipeline in args.pipelines:
                    result = await run_pipeline(
                        settings,
                        cases,
                        files,
                        pipeline,
                        concurrency=args.concurrency,
                        repeat=repeat,
                        meter=meter,
                    )
                    manifest = build_manifest(
                        pipeline_settings(settings, pipeline),
                        files=files,
                        datasets=args.dataset,
                        with_messy=args.with_messy,
                        split=args.split,
                        concurrency=args.concurrency,
                        repeat_index=repeat,
                        repeat_count=args.repeats,
                        cap_usd=args.cap,
                    )
                    manifest["spend"] = meter.summary()
                    result.update(
                        manifest=manifest,
                        split=args.split,
                        datasets=args.dataset,
                        retrieval={
                            "score_threshold": settings.retrieval_score_threshold,
                            "relative_threshold": settings.retrieval_relative_threshold,
                        },
                        spend_so_far=meter.summary(),
                    )
                    tag = f"_{args.tag}" if args.tag else ""
                    again = f"_r{repeat}of{args.repeats}" if args.repeats > 1 else ""
                    name = f"rag_v2_{stamp}_{pipeline}_{settings.chat_model}_{args.split}{again}{tag}.json"
                    path = RESULTS / name
                    path.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
                    print(
                        f"\n== {pipeline} ({settings.chat_model}, split={args.split}) -> {path.name}"
                    )
                    print(json.dumps(result["summary"], indent=1))
                    if result["summary"].get("incomplete"):
                        stopped = (
                            f"STOPPED: the spend cap ended the run; {result['summary']['cap_stopped']} "
                            f"case(s) are marked cap_stopped and left out of every rate (saved in {path.name}). "
                            "Ask before spending more."
                        )
                        break
                if stopped:
                    break
    except BudgetExceeded as exc:
        stopped = f"STOPPED: {exc}. The run in progress was abandoned and not written. Ask before spending more."
    print("\nSPEND:", json.dumps(meter.summary(), indent=1))
    if stopped:
        raise SystemExit(stopped)


async def rescore(args: argparse.Namespace) -> None:
    """Apply the current judge and pass rules to the replies of a saved run; nothing is re-asked."""
    source = Path(args.file)
    data = json.loads(source.read_text())
    total = len(corpus_files(with_messy=args.with_messy))  # pass --with-messy if the run used it
    # The datasets the run was made with are recorded in its file; the command-line default is not.
    cases = {
        c["id"]: prepare_case(c, total)
        for c in load_many(data.get("datasets") or args.dataset)["cases"]
    }
    live = [r for r in data["rows"] if not r.get("cap_stopped")]  # a cap-stopped row has no verdict
    judged = sum(cases[r["id"]]["expected_behavior"] in JUDGED for r in live)
    plan = {"cases": len(data["rows"]), **estimate_judge(judged)}
    if args.plan:
        report_plan(plan, args.cap)
        return
    refuse_over_cap(plan["estimated_usd"], args.cap)
    settings = eval_settings(chat_model=data["model"])
    require_prices(JUDGE_MODEL)
    meter = CostMeter(args.cap)
    try:
        with meter.installed():
            rows = [
                r
                if r.get("cap_stopped")
                else await judge_row(settings, cases[r["id"]], score_row(cases[r["id"]], r))
                for r in data["rows"]
            ]
    except BudgetExceeded as exc:
        raise SystemExit(f"STOPPED: {exc}. Nothing was written. Ask before spending more.") from exc
    rows = await extend_all(
        lambda: session_factory(settings)(), cases, rows, corpus_files(with_messy=args.with_messy)
    )
    data.update(
        rows=rows, summary=summarise(rows), rescored_from=source.name, rescore_spend=meter.summary()
    )
    target = source.with_name(source.stem + "_rescored.json")
    target.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    print(
        f"-> {target.name}\n"
        + json.dumps(data["summary"], indent=1)
        + f"\nspend ${meter.total:.4f}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["setup", "run", "rescore"])
    parser.add_argument("file", nargs="?", help="saved result file (rescore)")
    parser.add_argument(
        "--cap",
        type=cap_argument,
        required=True,
        help="hard spend cap in USD (required, no default: setup, run and rescore can spend money)",
    )
    parser.add_argument(
        "--plan",
        action="store_true",
        help="print the planned calls and the estimate, then stop: no provider call, no file written",
    )
    parser.add_argument(
        "--repeats",
        type=repeats_argument,
        default=1,
        help=f"run each pipeline this many times (1 to {MAX_REPEATS}), one result file per run",
    )
    parser.add_argument("--pipelines", nargs="+", choices=sorted(PIPELINES), default=["tool_agent"])
    parser.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    parser.add_argument("--category", nargs="*")
    parser.add_argument("--limit", type=positive_int, help="run at most this many cases")
    parser.add_argument("--ids", nargs="*", help="only these case ids")
    parser.add_argument(
        "--dataset",
        nargs="+",
        default=["rag_v2_cases.json"],
        help="one or more case files in evaluation/datasets",
    )
    parser.add_argument("--threshold", type=float, help="override retrieval_score_threshold")
    parser.add_argument("--relative", type=float, help="override retrieval_relative_threshold")
    parser.add_argument("--tag", help="suffix for the result file name, e.g. claimcheck")
    parser.add_argument(
        "--no-claim-check",
        action="store_true",
        help="switch the KI-002 claim check off (before-fix behaviour)",
    )
    parser.add_argument("--model", default=None, help="chat model (default: the app default)")
    parser.add_argument("--concurrency", type=positive_int, default=3)
    parser.add_argument(
        "--with-messy",
        action="store_true",
        help="add the generated messy documents (needed for rag_v2_messy_cases.json; setup and run)",
    )
    args = parser.parse_args()
    if args.command == "rescore" and not args.file:
        parser.error("rescore needs the saved result file")
    asyncio.run(
        {
            "setup": lambda: setup(args),
            "run": lambda: run(args),
            "rescore": lambda: rescore(args),
        }[args.command]()
    )


if __name__ == "__main__":
    main()
