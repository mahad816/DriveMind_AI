"""First-step test: which tool does the model call first, and does the query it writes find the file?

    python -m evaluation.rag_eval.first_step_probe [--split dev|test|all] [--repeats 2] [--tag NAME]

The agent's first model call decides most outcomes: a content question sent to the file-listing tool
is answered with a file name instead of a fact, and a vague search query misses the right file. This
probe sends each question to the real model with the agent's real policy and tool descriptions
(``initial_messages`` + the registry), records the first tool call, and, when it is a search, runs the
query the model wrote through the real retriever and checks that the expected file comes back.

It stops after the first model call, so it costs a small fraction of a full agent run, and it measures
exactly what the tool wording can change. It does not measure answers; ``cli run`` does.

* Questions that are chit-chat are skipped (the intent gate answers them before the agent runs).
* Inventory questions legitimately use the listing tool, so they are reported but never counted wrong.
* The model is not perfectly deterministic even at temperature 0, so each question runs ``--repeats``
  times and the counts are over all runs.
"""

import argparse
import asyncio
import json
import statistics
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.agents.tool_rag.agent_models import AgentMessage, AgentStepResult, ToolDefinition
from app.agents.tool_rag.agent_service import initial_messages
from app.agents.tool_rag.registry import ToolRegistry
from app.core.config import Settings
from app.llm.openai_agent_service import OpenAIAgentChatService
from app.retrieval.hybrid import HybridRetriever
from app.services.tool_agent_service import bounded_agent_history

from .corpus import verify
from .dataset import files_to_check, load_cases, validate
from .frozen_corpus import FrozenCorpusError, corpus_for
from .meter import BudgetExceeded, CostMeter, cap_argument
from .retrieval_probe import (
    DATASETS,
    MESSY_DATASETS,
    RESULTS,
    Hit,
    expected_names,
    make_search,
    measure,
)
from .runner import prepare_case
from .score import wilson
from .target import eval_settings, session_factory

Step = Callable[[Sequence[AgentMessage]], Awaitable[AgentStepResult]]
Search = Callable[[str], Awaitable[list[Hit]]]

SKIPPED_CATEGORIES = {"chitchat"}
INVENTORY_CATEGORIES = {"inventory"}
SEARCH_TOOLS = {"search_knowledge", "resolve_file", "file_evidence"}


@dataclass(frozen=True)
class FirstCall:
    tool: str | None  # first tool the model called; None: it answered without a tool
    queries: tuple[
        str, ...
    ]  # every search_knowledge query of that first step (it may send several)


def first_call(step: AgentStepResult) -> FirstCall:
    """The first model step, reduced to what the probe judges."""
    if not step.tool_calls:
        return FirstCall(None, ())
    queries = tuple(
        q
        for call in step.tool_calls
        if call.tool_name == "search_knowledge"
        and isinstance(q := call.arguments.get("query"), str)
    )
    return FirstCall(step.tool_calls[0].tool_name, queries)


def case_kind(case: dict[str, Any]) -> str:
    return "inventory" if case["category"] in INVENTORY_CATEGORIES else "content"


def history_messages(case: dict[str, Any]) -> tuple[AgentMessage, ...]:
    return bounded_agent_history(case.get("history") or ())


async def probe_case(
    step: Step, search: Search, case: dict[str, Any], repeats: int
) -> list[dict[str, Any]]:
    """Run one case ``repeats`` times: first call, then the retrieval of the query it wrote."""
    history = history_messages(case)
    messages = initial_messages(case["question"], history, history_window_complete=bool(history))
    names = expected_names(case)
    rows: list[dict[str, Any]] = []
    for _ in range(repeats):
        call = first_call(await step(messages))
        row: dict[str, Any] = {
            "id": case["id"],
            "split": case["split"],
            "kind": case_kind(case),
            "tool": call.tool,
            "queries": list(call.queries),
            "expected": names,
        }
        if call.queries and names:
            # Everything the model searched for in its first step, in the order it asked.
            hits = [h for query in call.queries for h in await search(query)]
            row |= {k: v for k, v in measure(hits, names).items() if k != "files"}
        rows.append(row)
    return rows


def summarise(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    content = [r for r in rows if r["kind"] == "content"]
    inventory = [r for r in rows if r["kind"] == "inventory"]
    searched = [r for r in content if r["queries"] and r["expected"]]
    found = sum(r["found"] for r in searched)
    low, high = wilson(found, len(searched)) if searched else (0.0, 0.0)
    multi = [r for r in searched if len(r["expected"]) > 1]
    queries = [len(q.split()) for r in content for q in r["queries"]]
    return {
        "content_runs": len(content),
        "first_tool": dict(Counter(r["tool"] or "(no tool)" for r in content)),
        "wrong_tool": sum(r["tool"] == "files_query" for r in content),
        "no_tool": sum(r["tool"] is None for r in content),
        "search_runs_with_expected_file": len(searched),
        "search_found_expected_file": found,
        "search_found_ci95_pct": [round(100 * low, 1), round(100 * high, 1)],
        "search_ranked_first": sum(r["rank"] == 1 for r in searched),
        "multi_file_runs": len(multi),
        "multi_file_all_found": sum(r["found_all"] for r in multi),
        "multi_file_missed_ids": sorted({r["id"] for r in multi if not r["found_all"]}),
        "runs_with_several_searches": sum(len(r["queries"]) > 1 for r in content),
        "median_query_words": statistics.median(queries) if queries else None,
        "inventory_first_tool": dict(Counter(r["tool"] or "(no tool)" for r in inventory)),
        "wrong_tool_ids": sorted({r["id"] for r in content if r["tool"] == "files_query"}),
        "missed_ids": sorted({r["id"] for r in searched if not r["found"]}),
    }


async def run_probe(
    step: Step, search: Search, cases: Sequence[dict[str, Any]], repeats: int
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        if case["category"] not in SKIPPED_CATEGORIES:
            rows += await probe_case(step, search, case, repeats)
    return rows


async def run(args: argparse.Namespace) -> None:
    names = args.dataset or (list(MESSY_DATASETS) if args.messy else list(DATASETS))
    try:
        # Legacy: the store must hold the messy documents too (cli setup --with-messy). Frozen: it holds them already.
        files = corpus_for(frozen=args.frozen, with_messy=args.messy or args.with_messy)
    except FrozenCorpusError as exc:
        raise SystemExit(f"STOPPED: {exc}") from exc
    verify(files)
    cases: list[dict[str, Any]] = []
    for name in names:
        dataset = load_cases(name)
        problems = validate(dataset, files_to_check(dataset, files))
        if problems:
            raise SystemExit(f"{name} is invalid:\n" + "\n".join(problems))
        cases += [prepare_case(c, len(files)) for c in dataset["cases"]]
    if args.split != "all":
        cases = [c for c in cases if c["split"] == args.split]
    if args.ids:
        cases = [c for c in cases if c["id"] in set(args.ids)]

    settings: Settings = eval_settings(tool_agent=True)
    chat = OpenAIAgentChatService(settings)
    tools = tuple(ToolDefinition.model_validate(d) for d in ToolRegistry().definitions())

    async def step(messages: Sequence[AgentMessage]) -> AgentStepResult:
        return await chat.step(messages=messages, tools=tools)

    meter = CostMeter(args.cap)
    sessions = session_factory(settings)
    try:
        with meter.installed():
            async with sessions() as db:
                rows = await run_probe(
                    step, make_search(HybridRetriever(db, settings)), cases, args.repeats
                )
    except BudgetExceeded as exc:
        raise SystemExit(f"STOPPED: {exc}") from exc
    report = {
        "summary": summarise(rows),
        "rows": rows,
        "settings": {"split": args.split, "repeats": args.repeats, "model": chat.model_name},
        "spend": meter.summary(),
    }
    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    path = RESULTS / f"first_step_{stamp}{'_' + args.tag if args.tag else ''}.json"
    path.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print_report(report, path.name)


def print_report(report: dict[str, Any], filename: str) -> None:
    s, c = report["summary"], report["settings"]
    print(
        f"first-step probe  split={c['split']}  repeats={c['repeats']}  model={c['model']}  -> {filename}\n"
    )
    print(f"content-question runs:       {s['content_runs']}")
    print(f"  first tool called:         {s['first_tool']}")
    print(f"  listing tool (wrong):      {s['wrong_tool']}   {s['wrong_tool_ids']}")
    print(f"  no tool at all:            {s['no_tool']}")
    print(
        f"  search found right file:   {s['search_found_expected_file']} of "
        f"{s['search_runs_with_expected_file']}  (ranked first: {s['search_ranked_first']})  "
        f"missed: {s['missed_ids']}"
    )
    print(
        f"  all expected files found:  {s['multi_file_all_found']} of {s['multi_file_runs']} "
        f"multi-file runs  missed: {s['multi_file_missed_ids']}"
    )
    print(f"  runs with several searches in the first step: {s['runs_with_several_searches']}")
    print(f"  median query length:       {s['median_query_words']} words")
    print(f"inventory questions, first tool: {s['inventory_first_tool']}")
    print("spend:", report["spend"]["estimated_total_usd"], "USD")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    parser.add_argument("--ids", nargs="+", help="only these case ids")
    parser.add_argument(
        "--messy",
        action="store_true",
        help="use the messy question set instead (the store needs cli setup --with-messy)",
    )
    parser.add_argument(
        "--dataset",
        nargs="+",
        help="case files in evaluation/datasets (default: the v2 sets); add --with-messy if they use the messy files",
    )
    parser.add_argument(
        "--with-messy", action="store_true", help="the store holds the messy documents"
    )
    parser.add_argument(
        "--frozen",
        action="store_true",
        help="the store holds the complete frozen M1 corpus (cli setup --frozen)",
    )
    parser.add_argument("--repeats", type=int, default=2)
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
