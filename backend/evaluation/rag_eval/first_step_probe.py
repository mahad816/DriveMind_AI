"""First-step test: which tool does the model call first, and does the query it writes find the file?

    python -m evaluation.rag_eval.first_step_probe --cap USD [--plan] [--mode model|baseline|both]
                                                   [--split dev|test|regression|all] [--repeats 2] [--passage, only with --mode both]
                                                   [--frozen [--store v3]] [--tag NAME]

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
  times (1 to ``MAX_REPEATS``, default 2) and the counts are over all runs.

M1-08-E adds, without changing what the default invocation measures:

* ``--mode model`` (default, the legacy behaviour), ``baseline`` (the question itself is the query: embeddings
  only, no chat call) or ``both``, which also reports a paired comparison over the same cases.
* With ``--frozen`` and no ``--messy``/``--dataset`` the cases come from the named pools (development,
  regression) through the shared loaders; ``--frozen --messy`` still probes the messy question set. The sealed
  held-out pool is refused before anything is read or called.
* A free ``--plan`` (chat calls, embedding calls, tokens, dollars at the recorded prices), a refusal when the
  estimate is above ``--cap``, and the run-time ``CostMeter`` as in the other paid probes.
"""

import argparse
import asyncio
import hashlib
import json
import math
import statistics
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.agents.tool_rag.agent_models import AgentMessage, AgentStepResult, ToolDefinition
from app.agents.tool_rag.agent_service import initial_messages
from app.agents.tool_rag.prompts import AGENT_SYSTEM_PROMPT
from app.agents.tool_rag.registry import ToolRegistry
from app.core.config import Settings
from app.llm.openai_agent_service import OpenAIAgentChatService
from app.retrieval.hybrid import HybridRetriever
from app.services.tool_agent_service import bounded_agent_history

from .cli import report_plan
from .corpus import CorpusFile, verify
from .dataset import HELD_OUT_SPLIT, files_to_check, load_cases, validate
from .embedding_estimate import BYTES_PER_TOKEN, SAFETY_MARGIN
from .frozen_corpus import FrozenCorpusError, corpus_for
from .index_verify import require_verified_index
from .meter import (
    PRICE_TABLE_DATE,
    BudgetExceeded,
    CostMeter,
    cap_argument,
    price_for,
    refuse_over_cap,
    require_prices,
)
from .pools import select
from .probe_pools import MAX_REPEATS, MODES, check_first_step_mode, select_probe_cases
from .retrieval_probe import (
    DATASETS,
    MESSY_DATASETS,
    RESULTS,
    Hit,
    expected_names,
    make_search,
    measure,
    summarise_answerable,
)
from .runner import prepare_case
from .score import wilson
from .target import application_defaults, eval_settings, session_factory, store_for

Step = Callable[[Sequence[AgentMessage]], Awaitable[AgentStepResult]]
Search = Callable[[str], Awaitable[list[Hit]]]

SKIPPED_CATEGORIES = {"chitchat"}
INVENTORY_CATEGORIES = {"inventory"}
SEARCH_TOOLS = {"search_knowledge", "resolve_file", "file_evidence"}

# Planning assumptions of --plan: not measurements and not guaranteed upper bounds (the request sets no output
# limit); the meter records the real figures.
# One first model step: a tool call of up to three short queries (about 150 tokens), a 2x margin.
# No reasoning tokens are modelled (the request sets no output limit).
OUTPUT_TOKENS_PER_STEP = 300
MAX_QUERIES_PER_STEP = 3  # search_knowledge queries one first step may carry
# A model-written query is assumed to be as long as the question, but never shorter than this many bytes.
QUERY_BYTES_FLOOR = 200
DEFAULT_REPEATS = 2
SDK_DEFAULT_RETRIES = (
    2  # openai 2.44.0 DEFAULT_MAX_RETRIES; the agent's non-streaming step uses the default client
)


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
    step: Step,
    search: Search,
    case: dict[str, Any],
    repeats: int,
    *,
    collect: dict[int, dict[str, list[list[Hit]]]] | None = None,
) -> list[dict[str, Any]]:
    """Run one case ``repeats`` times: first call, then the retrieval of the query it wrote.

    ``collect``, when given, receives per repeat (1-based) and case id the chunks of every search the model made,
    one list per search and uncut, for the passage metrics. It is filled for every case the baseline can also score
    (``baseline_eligible``) and for every repeat: a run that made no search is recorded as ``[]``, an empty
    retrieval, never left out. Other cases (inventory, follow-ups, no expected file) are not collected.
    """
    history = history_messages(case)
    messages = initial_messages(case["question"], history, history_window_complete=bool(history))
    names = expected_names(case)
    rows: list[dict[str, Any]] = []
    for repeat in range(1, repeats + 1):
        result = await step(messages)
        call = first_call(result)
        row: dict[str, Any] = {
            "id": case["id"],
            "split": case["split"],
            "kind": case_kind(case),
            "mode": "model",
            "repeat": repeat,
            "tool": call.tool,
            "queries": list(call.queries),
            "expected": names,
            "returned_model": result.returned_model,
        }
        per_query: list[list[Hit]] = []
        if call.queries and names:
            # Everything the model searched for in its first step, in the order it asked.
            per_query = [await search(query) for query in call.queries]
            hits = [h for found in per_query for h in found]
            row |= {k: v for k, v in measure(hits, names).items() if k != "files"}
        if collect is not None and baseline_eligible(case):
            collect.setdefault(repeat, {})[case["id"]] = per_query
        rows.append(row)
    return rows


def baseline_eligible(case: dict[str, Any]) -> bool:
    """Cases the question itself can be searched for: content questions with expected files and no earlier turn
    (a follow-up is meaningless alone), the same rule ``retrieval_probe`` applies."""
    return (
        case["category"] not in SKIPPED_CATEGORIES
        and case_kind(case) == "content"
        and not case.get("history")
        and bool(expected_names(case))
    )


async def baseline_rows(
    search: Search, cases: Sequence[dict[str, Any]], *, collect: dict[str, list[Hit]] | None = None
) -> list[dict[str, Any]]:
    """The question text as the query, one search per eligible case (embedding only; no chat model)."""
    rows: list[dict[str, Any]] = []
    for case in cases:
        if not baseline_eligible(case):
            continue
        hits = await search(case["question"])
        if collect is not None:
            collect[case["id"]] = hits
        rows.append(
            {
                "id": case["id"],
                "split": case["split"],
                "kind": "content",
                "mode": "baseline",
                "repeat": 0,
                "queries": [case["question"]],
                "expected": expected_names(case),
                **{k: v for k, v in measure(hits, expected_names(case)).items() if k != "files"},
            }
        )
    return rows


def compare(baseline: Sequence[dict[str, Any]], model: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Question-as-query against model-written queries on the same cases, pair by pair.

    Only cases present in ``baseline`` (content, no history, expected files) are compared, and a case counts only
    when the model has every repeat (1..R) for it; a case without all of them is listed in ``unpaired_ids`` and
    left out, never paired partly. A model run that wrote no search counts as a miss, so the figure is what the
    agent's first step delivers; the runs that did search are reported separately. Every (case, repeat) pair is
    one comparison.
    """
    by_id: dict[str, list[dict[str, Any]]] = {}
    for r in model:
        by_id.setdefault(r["id"], []).append(r)
    repeats = max((r["repeat"] for r in model), default=0)
    wanted = set(range(1, repeats + 1))
    pairs = both = base_only = model_only = neither = 0
    searched_runs = searched_found = 0
    base_rr = model_rr = 0.0
    unstable: list[str] = []
    unpaired: list[str] = []
    cases = 0
    for b in baseline if repeats else ():
        runs = by_id.get(b["id"], [])
        if {r["repeat"] for r in runs} != wanted or len(runs) != repeats:
            unpaired.append(b["id"])
            continue
        cases += 1
        outcomes = [bool(r.get("found")) for r in runs]
        if len(set(outcomes)) > 1:
            unstable.append(b["id"])
        for r in runs:
            pairs += 1
            hit = bool(r.get("found"))
            both += b["found"] and hit
            base_only += b["found"] and not hit
            model_only += hit and not b["found"]
            neither += not b["found"] and not hit
            base_rr += 1 / b["rank"] if b["rank"] else 0.0
            model_rr += 1 / r["rank"] if r.get("rank") else 0.0
            if r["queries"]:
                searched_runs += 1
                searched_found += hit
    base_found = both + base_only
    model_found = both + model_only
    return {
        "cases": cases,
        "repeats_per_case": repeats,
        "unpaired_ids": sorted(unpaired),
        "pairs": pairs,
        "baseline_found": base_found,
        "model_found": model_found,
        "baseline_found_pct": round(100 * base_found / pairs, 1) if pairs else None,
        "model_found_pct": round(100 * model_found / pairs, 1) if pairs else None,
        "both_found": both,
        "baseline_only": base_only,
        "model_only": model_only,
        "neither": neither,
        "baseline_mrr": round(base_rr / pairs, 3) if pairs else None,
        "model_mrr": round(model_rr / pairs, 3) if pairs else None,
        "model_runs_that_searched": searched_runs,
        "model_found_when_searched": searched_found,
        "unstable_ids": sorted(unstable),
        "note": "file-level, over the candidate list of each search; a model run without a search counts as "
        "not found; pairs = cases x repeats. The model may make several searches and the baseline makes one, "
        "so this is not a budget-matched comparison: see the equal-budget passage view.",
    }


# ---- passage comparison: the same cases, the same denominator, two labelled retrieval budgets -----------


def passage_cases(cases: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """The one set of cases both sides are scored on at passage level: exactly the baseline-eligible cases."""
    return [c for c in cases if baseline_eligible(c)]


def equal_budget_hits(per_search: Sequence[Sequence[Hit]], top_k: int) -> list[Hit]:
    """The model's searches reduced to the baseline's budget of ``top_k`` chunks in total.

    The searches take turns, each giving its best chunk not yet taken, until ``top_k`` chunks are taken or every
    search is used up. No search is favoured by outcome. With one search this is its first ``top_k`` distinct chunks,
    which is how the baseline's single search is scored; with none it is empty.
    """
    taken: list[Hit] = []
    seen: set[str] = set()
    cursors = [0] * len(per_search)
    progressed = True
    while len(taken) < top_k and progressed:
        progressed = False
        for n, found in enumerate(per_search):
            while cursors[n] < len(found):
                hit = found[cursors[n]]
                cursors[n] += 1
                key = hit.chunk_id if hit.chunk_id is not None else f"no-id:{n}:{cursors[n]}"
                if key in seen:
                    continue
                seen.add(key)
                taken.append(hit)
                progressed = True
                break
            if len(taken) >= top_k:
                break
    return taken


def real_budget_hits(per_search: Sequence[Sequence[Hit]], top_k: int) -> list[Hit]:
    """What the agent really receives: each search cut to its first ``top_k`` chunks, all of them together (up to
    ``top_k`` times the number of searches). Not an equal budget with the baseline."""
    return [h for found in per_search for h in found[:top_k]]


def budget_summary(collect: dict[int, dict[str, list[list[Hit]]]], top_k: int) -> dict[str, Any]:
    """How much retrieval the model used, run by run, so the cost of extra searches is visible."""
    runs = [per_search for per_case in collect.values() for per_search in per_case.values()]
    chunks = [len({h.chunk_id for h in real_budget_hits(r, top_k)}) for r in runs]
    return {
        "baseline_chunks_at_most": top_k,
        "model_runs": len(runs),
        "model_runs_without_search": sum(not r for r in runs),
        "model_searches_mean": round(statistics.fmean(len(r) for r in runs), 3) if runs else None,
        "model_chunks_mean_real_budget": round(statistics.fmean(chunks), 3) if runs else None,
    }


def same_cases(first: dict[str, Any], second: dict[str, Any]) -> bool:
    """True when two passage sections scored exactly the same case ids (and both were computed)."""
    if first.get("status", "ok") != "ok" or second.get("status", "ok") != "ok":
        return False

    def ids(section: dict[str, Any]) -> list[str]:
        return sorted(r["id"] for r in section.get("rows", []))

    return ids(first) == ids(second)


PASSAGE_LABELS = {
    "baseline": "the question text as the query; one search, first top-k chunks",
    "model_equal_budget": "the model's searches, reduced to the same total of top-k chunks as the baseline "
    "(the primary passage comparison); a run without a search is an empty retrieval, a miss",
    "model_real_budget": "the model's searches, each at top-k, all together: not an equal budget (up to top-k per "
    "search); shows what the agent really receives, with the cost of extra searches in 'budget'",
}


async def passage_comparison(
    sessions: Any,
    cases: Sequence[dict[str, Any]],
    files: Sequence[CorpusFile],
    base_hits: dict[str, list[Hit]],
    collect: dict[int, dict[str, list[list[Hit]]]],
    *,
    top_k: int,
) -> dict[str, Any]:
    """Passage metrics of the baseline and of every model repeat over ONE case set (``passage_cases``).

    A case the model did not search, or that a repeat did not record, enters as an empty retrieval, so every view has
    the same denominator. ``same_cases`` is checked on the result and reported, not assumed.
    """
    from .passage_metrics import passage_section  # late: that module imports retrieval_probe

    eligible = passage_cases(cases)
    baseline = await passage_section(
        sessions,
        eligible,
        files,
        {c["id"]: base_hits.get(c["id"], []) for c in eligible},
        top_k=top_k,
        query=PASSAGE_LABELS["baseline"],
    )
    equal: dict[str, Any] = {}
    real: dict[str, Any] = {}
    for repeat in sorted(collect):
        per_case = collect[repeat]
        searches = {c["id"]: per_case.get(c["id"], []) for c in eligible}
        equal[f"repeat_{repeat}"] = await passage_section(
            sessions,
            eligible,
            files,
            {i: equal_budget_hits(s, top_k) for i, s in searches.items()},
            top_k=top_k,
            query=PASSAGE_LABELS["model_equal_budget"],
        )
        real[f"repeat_{repeat}"] = await passage_section(
            sessions,
            eligible,
            files,
            {i: real_budget_hits(s, top_k) for i, s in searches.items()},
            top_k=None,  # every search is already cut to top-k
            query=PASSAGE_LABELS["model_real_budget"],
        )
    return {
        "cases": len(eligible),
        "same_cases": all(same_cases(baseline, s) for s in [*equal.values(), *real.values()]),
        "labels": PASSAGE_LABELS,
        "budget": budget_summary(collect, top_k),
        "baseline": baseline,
        "model_equal_budget": equal,
        "model_real_budget": real,
    }


def prompt_id(tools: Sequence[ToolDefinition]) -> str:
    """A stable identifier of the agent's policy text and tool descriptions: what the model is shown."""
    payload = json.dumps(
        {"system": AGENT_SYSTEM_PROMPT, "tools": [t.model_dump(mode="json") for t in tools]},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _tokens(total_bytes: int) -> int:
    """The upper bound the other plans use: UTF-8 bytes / BYTES_PER_TOKEN, times SAFETY_MARGIN."""
    return math.ceil(math.ceil(total_bytes / BYTES_PER_TOKEN) * SAFETY_MARGIN)


def plan_first_step(
    cases: Sequence[dict[str, Any]],
    *,
    mode: str,
    repeats: int,
    chat_model: str,
    embedding_model: str,
    tools: Sequence[ToolDefinition],
    cap: float,
    split: str,
) -> dict[str, Any]:
    """Free estimate of a run: exact messages for the chat calls, bounded sizes for the queries it will embed.

    Nothing is called. The dollars are full precision and are what the cap is compared with. Cached-input
    discounts are not assumed. Tokens are upper bounds (see ``embedding_estimate``); output is a fixed
    assumption per step, because the agent's request sets no output limit.
    """
    do_model = mode in {"model", "both"}
    do_baseline = mode in {"baseline", "both"}
    models = [embedding_model] + ([chat_model] if do_model else [])
    require_prices(*models)
    runnable = [c for c in cases if c["category"] not in SKIPPED_CATEGORIES]
    chat_calls = embed_calls = 0
    chat_bytes = embed_bytes = 0
    if do_model:
        tool_bytes = len(
            json.dumps([t.model_dump(mode="json") for t in tools], ensure_ascii=False).encode()
        )
        for case in runnable:
            history = history_messages(case)
            messages = initial_messages(
                case["question"], history, history_window_complete=bool(history)
            )
            per_call = tool_bytes + sum(len((m.text or "").encode()) for m in messages)
            chat_calls += repeats
            chat_bytes += per_call * repeats
            if expected_names(case):  # only these have their queries searched
                size = max(len(case["question"].encode()), QUERY_BYTES_FLOOR)
                embed_calls += repeats * MAX_QUERIES_PER_STEP
                embed_bytes += repeats * MAX_QUERIES_PER_STEP * size
    if do_baseline:
        for case in runnable:
            if baseline_eligible(case):
                embed_calls += 1
                embed_bytes += len(case["question"].encode())
    chat_in, embed_in = _tokens(chat_bytes), _tokens(embed_bytes)
    chat_price = price_for(chat_model) if do_model else {"input": 0.0, "output": 0.0}
    embed_price = price_for(embedding_model)["input"]
    chat_usd = (
        chat_in * chat_price["input"] + chat_calls * OUTPUT_TOKENS_PER_STEP * chat_price["output"]
    ) / 1_000_000
    embed_usd = embed_in * embed_price / 1_000_000
    usd = chat_usd + embed_usd
    return {
        "split": split,
        "mode": mode,
        "repeats": repeats,
        "cases": len(runnable),
        "chat_model": chat_model if do_model else None,
        "embedding_model": embedding_model,
        "chat_calls": chat_calls,
        "embedding_calls": embed_calls,
        "estimated_chat_input_tokens": chat_in if do_model else 0,
        "estimated_chat_output_tokens": chat_calls * OUTPUT_TOKENS_PER_STEP,
        "estimated_embedding_tokens": embed_in,
        "price_table_date": PRICE_TABLE_DATE,
        "estimated_chat_usd": chat_usd,
        "estimated_embedding_usd": embed_usd,
        "estimated_usd": usd,
        "within_cap": usd <= cap,
        "cap_is_hard_limit": False,
        "measured": "none before a paid run: the report then holds the meter's figures beside this estimate",
        "assumptions": [
            "conservative estimate from the recorded prices (prices.json), not a measurement; not edited by the plan",
            f"chat input: the exact messages and tool descriptions of each first step, as an upper bound of "
            f"UTF-8 bytes / {BYTES_PER_TOKEN} times {SAFETY_MARGIN}; no cached-input discount",
            f"chat output: {OUTPUT_TOKENS_PER_STEP} tokens per step (the request sets no output limit)",
            f"model-written searches: at most {MAX_QUERIES_PER_STEP} queries per step, each at most "
            f"max(question length, {QUERY_BYTES_FLOOR} bytes); only cases with expected files are searched",
            "baseline: one embedding call per eligible case on the question itself",
            "the cap is not a provider-side limit: the meter adds up the usage each response reports and refuses "
            "the next call once the cap is reached; calls run one at a time, so a run can pass the cap by the "
            "one call in flight",
            "no output limit is set on the request, so one call is not bounded by this estimate; the usage the "
            "meter reads (completion tokens) includes reasoning tokens, but whether the chat model reasons here is "
            "not verified without a paid call",
            f"the SDK retries a failed request by itself (default {SDK_DEFAULT_RETRIES} retries, below the "
            "meter): a retried request is not counted and may be billed",
        ],
    }


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
    step: Step,
    search: Search,
    cases: Sequence[dict[str, Any]],
    repeats: int,
    *,
    collect: dict[int, dict[str, list[list[Hit]]]] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        if case["category"] not in SKIPPED_CATEGORIES:
            rows += await probe_case(step, search, case, repeats, collect=collect)
    return rows


def select_first_step_cases(
    args: argparse.Namespace, files: Sequence[CorpusFile]
) -> list[dict[str, Any]]:
    """The cases of the run. Frozen without --messy/--dataset: the named pools through the shared loaders.
    Otherwise (legacy, or ``--frozen --messy``/``--dataset``): the named case files, as before."""
    if args.frozen and not (args.messy or args.dataset):
        cases, _sealed = select_probe_cases(args.split, files)  # held-out is refused earlier
    else:
        names = args.dataset or (list(MESSY_DATASETS) if args.messy else list(DATASETS))
        cases = []
        for name in names:
            dataset = load_cases(name)
            if any(c.get("split") == HELD_OUT_SPLIT for c in dataset["cases"]):
                raise SystemExit(f"STOPPED: {name} holds held-out cases; nothing was run.")
            problems = validate(dataset, files_to_check(dataset, files))
            if problems:
                raise SystemExit(f"{name} is invalid:\n" + "\n".join(problems))
            cases += [prepare_case(c, len(files)) for c in dataset["cases"]]
        cases = select(cases, args.split)
    if args.ids:
        cases = [c for c in cases if c["id"] in set(args.ids)]
    return cases


async def run(args: argparse.Namespace) -> None:
    # Before any file is read, any store opened or any call made.
    check_first_step_mode(
        args.split,
        frozen=args.frozen,
        mode=args.mode,
        repeats=args.repeats,
        datasets=args.dataset,
        passage=args.passage,
    )
    try:
        # Legacy: the store must hold the messy documents too (cli setup --with-messy). Frozen: it holds them already.
        files = corpus_for(frozen=args.frozen, with_messy=args.messy or args.with_messy)
    except FrozenCorpusError as exc:
        raise SystemExit(f"STOPPED: {exc}") from exc
    verify(files)
    cases = select_first_step_cases(args, files)  # as before, no cases is allowed: it costs nothing

    tools = tuple(ToolDefinition.model_validate(d) for d in ToolRegistry().definitions())
    defaults = application_defaults()
    # Free: nothing is called before the plan is printed (--plan) or accepted against the cap.
    plan = plan_first_step(
        cases,
        mode=args.mode,
        repeats=args.repeats,
        chat_model=defaults["chat_model"],
        embedding_model=defaults["embedding_model"],
        tools=tools,
        cap=args.cap,
        split=args.split,
    )
    if args.plan:
        report_plan(plan, args.cap)
        return
    refuse_over_cap(plan["estimated_usd"], args.cap)

    store = store_for(frozen=args.frozen, name=args.store)
    if args.frozen:
        # Before any chat or embedding call: the store must hold exactly the verified frozen corpus.
        settings: Settings = (await require_verified_index(store, tool_agent=True)).settings
    else:
        settings = eval_settings(tool_agent=True, store=store)
    if (settings.chat_model, settings.embedding_model) != (
        defaults["chat_model"],
        defaults["embedding_model"],
    ):
        # The store's settings use other models than the plan assumed: price those, and hold them to the cap.
        plan = plan_first_step(
            cases,
            mode=args.mode,
            repeats=args.repeats,
            chat_model=settings.chat_model,
            embedding_model=settings.embedding_model,
            tools=tools,
            cap=args.cap,
            split=args.split,
        )
        refuse_over_cap(plan["estimated_usd"], args.cap)
    chat = OpenAIAgentChatService(settings)

    async def step(messages: Sequence[AgentMessage]) -> AgentStepResult:
        return await chat.step(messages=messages, tools=tools)

    meter = CostMeter(args.cap)
    sessions = session_factory(settings)
    model_rows: list[dict[str, Any]] = []
    base_rows: list[dict[str, Any]] = []
    base_hits: dict[str, list[Hit]] = {}
    model_hits: dict[int, dict[str, list[list[Hit]]]] = {}
    top_k = settings.retrieval_top_k
    try:
        with meter.installed():
            async with sessions() as db:
                search = make_search(HybridRetriever(db, settings))
                if args.mode in {"baseline", "both"}:
                    base_rows = await baseline_rows(search, cases, collect=base_hits)
                if args.mode in {"model", "both"}:
                    model_rows = await run_probe(
                        step,
                        search,
                        cases,
                        args.repeats,
                        collect=model_hits,
                    )
    except BudgetExceeded as exc:
        raise SystemExit(f"STOPPED: {exc}") from exc
    report: dict[str, Any] = {
        "settings": {
            "split": args.split,
            "mode": args.mode,
            "repeats": args.repeats,
            "model": chat.model_name if args.mode != "baseline" else None,
            "embedding_model": settings.embedding_model,
            "prompt_id": prompt_id(tools),
            "store": store.database,
            "corpus": "frozen" if args.frozen else "legacy",
            "case_source": "pools"
            if args.frozen and not (args.messy or args.dataset)
            else "case files",
            "candidate_limit": 20,
            "retrieval_top_k": top_k,
            "temperature": 0,
        },
        "plan": plan,
        "spend": meter.summary(),
    }
    if model_rows:
        report |= {"summary": summarise(model_rows), "rows": model_rows}
    if base_rows:
        report |= {"baseline_summary": summarise_answerable(base_rows), "baseline_rows": base_rows}
    if model_rows and base_rows:
        report["comparison"] = compare(base_rows, model_rows)
    if args.passage:
        # Free: database reads only. One case set, one denominator, for the baseline and every repeat.
        report["passage"] = await passage_comparison(
            sessions, cases, files, base_hits, model_hits, top_k=top_k
        )
    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    path = RESULTS / f"first_step_{stamp}{'_' + args.tag if args.tag else ''}.json"
    path.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print_report(report, path.name)


def print_report(report: dict[str, Any], filename: str) -> None:
    c = report["settings"]
    print(
        f"first-step probe  mode={c['mode']}  split={c['split']}  repeats={c['repeats']}  "
        f"model={c['model']}  prompt={c['prompt_id']}  -> {filename}\n"
    )
    if "summary" in report:
        s = report["summary"]
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
    if "baseline_summary" in report:
        b = report["baseline_summary"]
        print(
            f"baseline (question as query): {b.get('found_in_results', 0)} of {b['n']} found, "
            f"MRR {b.get('mrr')}"
        )
    if "comparison" in report:
        k = report["comparison"]
        print(
            f"paired comparison over {k['cases']} cases x repeats = {k['pairs']}: baseline "
            f"{k['baseline_found']} found ({k['baseline_found_pct']}%), model-written "
            f"{k['model_found']} ({k['model_found_pct']}%); baseline only {k['baseline_only']}, "
            f"model only {k['model_only']}; unstable cases {k['unstable_ids']}"
        )
    if "passage" in report:
        p = report["passage"]
        b = p["budget"]
        print(
            f"passage views over {p['cases']} cases (same cases on every side: {p['same_cases']}); model used "
            f"{b['model_searches_mean']} searches and {b['model_chunks_mean_real_budget']} chunks per run "
            f"(baseline at most {b['baseline_chunks_at_most']}); {b['model_runs_without_search']} of "
            f"{b['model_runs']} runs made no search (counted as misses)"
        )
    print(
        f"estimate {report['plan']['estimated_usd']:.5f} USD, measured "
        f"{report['spend']['estimated_total_usd']} USD (cap {report['spend']['cap_usd']})"
    )


def repeats_argument(text: str) -> int:
    value = int(text)
    if not 1 <= value <= MAX_REPEATS:
        raise argparse.ArgumentTypeError(f"--repeats must be between 1 and {MAX_REPEATS}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--split",
        choices=["dev", "test", "regression", "held_out", "all"],
        default="dev",
        help="dev = development pool, test/regression = regression pool, all = both; held_out is refused; "
        "regression needs --frozen",
    )
    parser.add_argument(
        "--mode",
        choices=MODES,
        default="model",
        help="model (default, the legacy probe): the model writes the query; baseline: the question is the "
        "query, no chat call; both: each, plus a paired comparison",
    )
    parser.add_argument("--ids", nargs="+", help="only these case ids")
    parser.add_argument(
        "--messy",
        action="store_true",
        help="use the messy question set instead (the store needs cli setup --with-messy)",
    )
    parser.add_argument(
        "--dataset",
        nargs="+",
        help="case files in evaluation/datasets (bare names only; default: the v2 sets); add --with-messy if they use the messy files",
    )
    parser.add_argument(
        "--with-messy", action="store_true", help="the store holds the messy documents"
    )
    parser.add_argument(
        "--frozen",
        action="store_true",
        help="the store holds the complete frozen M1 corpus (cli setup --frozen); without --messy/--dataset "
        "the cases come from the named pools",
    )
    parser.add_argument(
        "--store",
        help="with --frozen: the evaluation store to measure (default v3; it must verify)",
    )
    parser.add_argument(
        "--repeats",
        type=repeats_argument,
        default=DEFAULT_REPEATS,
        help=f"model runs per question (default {DEFAULT_REPEATS}, at most {MAX_REPEATS})",
    )
    parser.add_argument(
        "--passage",
        action="store_true",
        help="also report passage-level metrics (anchor-chunk recall, rank, MRR) for the baseline and each "
        "repeat; needs --mode both, because the baseline must have been measured (refused otherwise)",
    )
    parser.add_argument("--tag", help="suffix for the result file name")
    parser.add_argument(
        "--plan",
        action="store_true",
        help="print the planned calls and the estimate, then stop: no provider call, no file written",
    )
    parser.add_argument(
        "--cap",
        type=cap_argument,
        required=True,
        help="spend cap in USD (required, no default). Enforced between calls from the usage each response "
        "reports; not a provider-side limit (see the plan's assumptions)",
    )
    return parser


def main() -> None:
    asyncio.run(run(build_parser().parse_args()))


if __name__ == "__main__":
    main()
