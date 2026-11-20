"""Command line entry for the v2 evaluation.

    python -m evaluation.rag_eval.cli setup     # create the isolated store and index the corpus
    python -m evaluation.rag_eval.cli rescore FILE      # re-judge a saved run (same replies, current rubric)
    python -m evaluation.rag_eval.cli run --pipelines tool_agent legacy --split dev [--limit N]

Requires the disposable PostgreSQL/Qdrant containers (see docs/EVALUATION_RESULTS.md) and an
OpenAI key in the environment or backend/.env. Never touches any non-``drivemind_eval`` store.
"""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from .corpus import CorpusFile, messy_files, public_files, synthetic_files, verify
from .dataset import load_many, validate
from .meter import BudgetExceeded, CostMeter
from .runner import PIPELINES, judge_row, prepare_case, run_pipeline, score_row
from .score import summarise
from .target import ensure_database, eval_settings, ingest, migrate


def corpus_files(*, with_messy: bool) -> list[CorpusFile]:
    """The evaluation corpus. The generated messy documents (DOCX, PPTX, XLSX, PDF) are added on request:
    a store that holds them gives different answers to the older datasets (five more files to confuse
    with), so they never join a run by accident."""
    files = synthetic_files() + public_files()
    return files + messy_files() if with_messy else files


async def setup(cap: float, *, with_messy: bool = False) -> None:
    files = corpus_files(with_messy=with_messy)
    verify(files)
    settings = eval_settings(tool_agent=False)
    await ensure_database()
    migrate(settings)
    meter = CostMeter(cap)
    with meter.installed():
        counts = await ingest(settings, files)
    print(json.dumps({"corpus_files": len(files), **counts, "spend": meter.summary()}, indent=1))


RESULTS = Path(__file__).resolve().parents[1] / "results"


async def run(args: argparse.Namespace) -> None:
    files = corpus_files(with_messy=args.with_messy)
    verify(files)
    dataset = load_many(args.dataset)
    problems = validate(dataset, files)
    if problems:
        raise SystemExit("Dataset invalid; refusing to spend money:\n" + "\n".join(problems))
    cases = [c for c in dataset["cases"] if args.split == "all" or c["split"] == args.split]
    if args.category:
        cases = [c for c in cases if c["category"] in args.category]
    if args.ids:
        cases = [c for c in cases if c["id"] in args.ids]
    cases = cases[: args.limit] if args.limit else cases
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
    meter = CostMeter(args.cap)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    RESULTS.mkdir(exist_ok=True)
    with meter.installed():
        for pipeline in args.pipelines:
            try:
                result = await run_pipeline(
                    settings, cases, files, pipeline, concurrency=args.concurrency
                )
            except BudgetExceeded as exc:
                print(f"STOPPED: {exc}. Ask before spending more.")
                break
            result.update(
                split=args.split,
                datasets=args.dataset,
                retrieval={
                    "score_threshold": settings.retrieval_score_threshold,
                    "relative_threshold": settings.retrieval_relative_threshold,
                },
                spend_so_far=meter.summary(),
            )
            tag = f"_{args.tag}" if args.tag else ""
            path = (
                RESULTS / f"rag_v2_{stamp}_{pipeline}_{settings.chat_model}_{args.split}{tag}.json"
            )
            path.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
            print(f"\n== {pipeline} ({settings.chat_model}, split={args.split}) -> {path.name}")
            print(json.dumps(result["summary"], indent=1))
    print("\nSPEND:", json.dumps(meter.summary(), indent=1))


async def rescore(args: argparse.Namespace) -> None:
    """Apply the current judge and pass rules to the replies of a saved run; nothing is re-asked."""
    source = Path(args.file)
    data = json.loads(source.read_text())
    total = len(synthetic_files() + public_files())
    cases = {c["id"]: prepare_case(c, total) for c in load_many(args.dataset)["cases"]}
    settings = eval_settings(chat_model=data["model"])
    meter = CostMeter(args.cap)
    with meter.installed():
        rows = [
            await judge_row(settings, cases[r["id"]], score_row(cases[r["id"]], r))
            for r in data["rows"]
        ]
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
    parser.add_argument("--cap", type=float, default=3.0, help="hard spend cap in USD")
    parser.add_argument("--pipelines", nargs="+", choices=sorted(PIPELINES), default=["tool_agent"])
    parser.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    parser.add_argument("--category", nargs="*")
    parser.add_argument("--limit", type=int)
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
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument(
        "--with-messy",
        action="store_true",
        help="add the generated messy documents (needed for rag_v2_messy_cases.json; setup and run)",
    )
    args = parser.parse_args()
    asyncio.run(
        {
            "setup": lambda: setup(args.cap, with_messy=args.with_messy),
            "run": lambda: run(args),
            "rescore": lambda: rescore(args),
        }[args.command]()
    )


if __name__ == "__main__":
    main()
