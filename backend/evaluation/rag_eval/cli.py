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

from .corpus import CorpusFile, verify
from .dataset import files_to_check, load_many, validate
from .embedding_estimate import estimate_embedding, extract_texts
from .freeze import sha256_of
from .frozen_corpus import FrozenCorpusError, corpus_for, frozen_corpus
from .index_verify import (
    extraction_problems,
    read_db_snapshot,
    read_qdrant_snapshot,
    record_receipt,
    require_verified_index,
    verify_index,
)
from .judge import JUDGE_MODEL
from .manifest import build_manifest
from .meter import (
    BudgetExceeded,
    CostMeter,
    cap_argument,
    estimate_judge,
    estimate_run,
    require_prices,
    refuse_over_cap,
)
from .pools import SPLIT_CHOICES, held_out_path, load_held_out, select
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
from .sealing import reduce_row
from .target import (
    application_defaults,
    ensure_database,
    eval_settings,
    ingest,
    migrate,
    session_factory,
    store_for,
)


def corpus_files(*, with_messy: bool, frozen: bool = False) -> list[CorpusFile]:
    """The evaluation corpus. The generated messy documents (DOCX, PPTX, XLSX, PDF) are added on request:
    a store that holds them gives different answers to the older datasets (five more files to confuse
    with), so they never join a run by accident.

    ``frozen`` selects the complete frozen M1 corpus from the committed manifests (synthetic, messy, v1,
    Google exports and every public PDF); it already contains the messy documents, so it cannot be combined
    with ``with_messy``. A corpus that differs from its manifests is refused with every difference named.
    """
    if frozen and with_messy:
        raise SystemExit("--frozen already includes the messy documents; do not add --with-messy.")
    try:
        return corpus_for(frozen=frozen, with_messy=with_messy)
    except FrozenCorpusError as exc:
        raise SystemExit(f"STOPPED: {exc}") from exc


def selected_files(args: argparse.Namespace) -> list[CorpusFile]:
    """The corpus the command line asks for. The legacy call is unchanged unless --frozen is given."""
    if getattr(args, "frozen", False):
        return corpus_files(with_messy=args.with_messy, frozen=True)
    return corpus_files(with_messy=args.with_messy)


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


def setup_plan(files: list[CorpusFile], texts: dict[str, str], model: str) -> dict[str, Any]:
    """The planned embedding work, priced from the extracted and chunked text (see ``embedding_estimate``)."""
    embedding = estimate_embedding(texts, model)
    return {
        "corpus_files": len(files),
        "calls": {"embedding_batches_at_most": len(files)},
        "embedding": embedding,
        "estimated_usd": embedding["estimated_usd"],
    }


async def setup(args: argparse.Namespace) -> None:
    files = selected_files(args)
    verify(files)
    frozen = getattr(args, "frozen", False)
    store = store_for(frozen=frozen, name=getattr(args, "store", None))
    # Free, local: read every original file the way the index will, and price the chunks that come out.
    # The evaluation always embeds with the application's default model (see target.ANSWER_FIELDS).
    texts = extract_texts(files)
    plan = setup_plan(files, texts, application_defaults()["embedding_model"])
    if frozen:
        plan["store"] = {"database": store.database, "collection": store.collection}
        if broken := extraction_problems(frozen_corpus(), texts):
            raise SystemExit(
                "STOPPED: the files extract differently from the frozen corpus, nothing was embedded:\n  "
                + "\n  ".join(broken)
            )
    if args.plan:
        report_plan(plan, args.cap)
        return
    refuse_over_cap(plan["estimated_usd"], args.cap)
    settings = eval_settings(tool_agent=False, store=store)
    require_prices(settings.embedding_model)
    await ensure_database(store)
    migrate(settings)
    meter = CostMeter(args.cap)
    try:
        with meter.installed():
            counts = await ingest(settings, files, texts=texts, refresh_stale=frozen)
    except BudgetExceeded as exc:
        raise SystemExit(f"STOPPED: {exc}. Ask before spending more.") from exc
    report: dict[str, Any] = {"corpus_files": len(files), **counts, "spend": meter.summary()}
    problems: list[str] = []
    if frozen:
        # Free: read the store back and compare every chunk and vector with the original documents.
        corpus = frozen_corpus()
        verification, db, qdrant = await verify_index(
            settings,
            corpus,
            texts=texts,
            read_db=read_db_snapshot,
            read_qdrant=read_qdrant_snapshot,
        )
        problems = verification.problems
        report |= {
            "store": store.database,
            "index_problems": problems,
            "not_provable": verification.limitations,
        }
        if not problems and db is not None and qdrant is not None:
            report["index_manifest"] = record_receipt(settings, corpus, db, qdrant).name
    print(json.dumps(report, indent=1))
    if problems:
        raise SystemExit(
            f"INDEX DIFFERS FROM THE FROZEN CORPUS: {len(problems)} problem(s), see above. No receipt was written."
        )


async def run_settings(args: argparse.Namespace, *, chat_model: str | None) -> Any:
    """The settings of the store a paid command measures.

    Frozen: the store must first pass verification, and these are the verified store's own settings. Legacy:
    the legacy store, as before.
    """
    store = store_for(frozen=getattr(args, "frozen", False), name=getattr(args, "store", None))
    if getattr(args, "frozen", False):
        return (await require_verified_index(store, chat_model=chat_model)).settings
    return eval_settings(chat_model=chat_model, store=store)


RESULTS = Path(__file__).resolve().parents[1] / "results"
HELD_OUT_RESULTS = "heldout_results"  # a folder next to the sealed file, outside the repository


async def run(args: argparse.Namespace) -> None:
    files = selected_files(args)
    verify(files)
    sealed = args.split == "held_out"
    if sealed and (args.ids or args.category or args.limit or args.repeats != 1):
        raise SystemExit(
            "The held-out pool runs whole and once per checkpoint: no --ids, --category, --limit or --repeats."
        )
    held_file = held_out_path() if sealed else None
    if sealed and held_file is None:
        raise SystemExit(
            "Set DRIVEMIND_EVAL_HELDOUT_FILE to the sealed case file (outside the repository)."
        )
    dataset = load_held_out(held_file) if sealed else load_many(args.dataset)
    problems = validate(dataset, files_to_check(dataset, files))
    if problems and sealed:
        # A held-out problem names a case and quotes it: say how many, nothing more.
        raise SystemExit(f"Held-out file invalid: {len(problems)} problem(s) (details withheld).")
    if problems:
        raise SystemExit("Dataset invalid; refusing to spend money:\n" + "\n".join(problems))
    # "all" is development plus regression, never held-out.
    cases = select(dataset["cases"], args.split)
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
    settings = await run_settings(args, chat_model=args.model)
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
                        datasets=[] if sealed else args.dataset,
                        with_messy=args.with_messy,
                        split=args.split,
                        concurrency=args.concurrency,
                        repeat_index=repeat,
                        repeat_count=args.repeats,
                        cap_usd=args.cap,
                    )
                    manifest["spend"] = meter.summary()
                    if held_file is not None:
                        manifest["dataset"]["held_out_sha256"] = sha256_of(held_file)
                    result.update(
                        manifest=manifest,
                        split=args.split,
                        datasets=[] if sealed else args.dataset,
                        retrieval={
                            "score_threshold": settings.retrieval_score_threshold,
                            "relative_threshold": settings.retrieval_relative_threshold,
                        },
                        spend_so_far=meter.summary(),
                    )
                    tag = f"_{args.tag}" if args.tag else ""
                    again = f"_r{repeat}of{args.repeats}" if args.repeats > 1 else ""
                    name = f"rag_v2_{stamp}_{pipeline}_{settings.chat_model}_{args.split}{again}{tag}.json"
                    if held_file is not None:
                        # Outside the repository, and no reply text: reduced rows plus the sealed summary.
                        result["rows"] = [reduce_row(r) for r in result["rows"]]
                        folder = held_file.parent / HELD_OUT_RESULTS
                        folder.mkdir(exist_ok=True)
                    else:
                        folder = RESULTS
                    path = folder / name
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
    total = len(selected_files(args))  # pass the flag the run used
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
    settings = await run_settings(args, chat_model=data["model"])
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
        lambda: session_factory(settings)(),
        cases,
        rows,
        selected_files(args),
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
    parser.add_argument(
        "--split",
        choices=SPLIT_CHOICES,
        default="dev",
        help="dev = development pool, test/regression = regression pool, all = both (never held-out), "
        "held_out = the sealed pool, only by name and once per checkpoint",
    )
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
        "--frozen",
        action="store_true",
        help="use the complete frozen M1 corpus from the committed manifests (setup, run, rescore); "
        "includes the messy documents, so do not combine with --with-messy",
    )
    parser.add_argument(
        "--store",
        help="with --frozen: the evaluation store (a database and a Qdrant collection of the same name, "
        "e.g. v4); default v3. v2 is the legacy store and is refused",
    )
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
