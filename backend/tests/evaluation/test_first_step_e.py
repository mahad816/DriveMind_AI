"""M1-08-E: the model-written-query probe: modes, repeats, pools, plan, cap and held-out refusal.

Free: no key, no network, no container. Every case, query and model answer is FABRICATED. A tripwire replaces the
provider's chat and embedding methods for every test in this file (the one metering test swaps in a counting fake),
so a test that reaches a paid call fails instead of spending. No sealed file, review sheet or attestation is read.
"""

import argparse
import asyncio
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.agents.tool_rag.agent_models import AgentStepResult, ToolCallRequest, ToolDefinition
from app.agents.tool_rag.registry import ToolRegistry
from evaluation.rag_eval import first_step_probe as fsp
from evaluation.rag_eval import probe_pools, retrieval_probe
from evaluation.rag_eval.meter import BudgetExceeded, CostMeter, price_for
from evaluation.rag_eval.retrieval_probe import Hit

MARKER = "zq-e-probe-marker"


@pytest.fixture(autouse=True)
def no_provider_call(monkeypatch: pytest.MonkeyPatch) -> None:
    from openai.resources.chat.completions import AsyncCompletions
    from openai.resources.embeddings import AsyncEmbeddings

    async def tripwire(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a provider call was attempted")

    monkeypatch.setattr(AsyncEmbeddings, "create", tripwire)
    monkeypatch.setattr(AsyncCompletions, "create", tripwire)


TOOLS = tuple(ToolDefinition.model_validate(d) for d in ToolRegistry().definitions())
CHAT, EMBED = "gpt-5.4-nano", "text-embedding-3-small"


def fab(i: int = 1, *, category: str = "single_fact", **extra: Any) -> dict[str, Any]:
    return {
        "id": f"e{i:03d}",
        "split": "dev",
        "category": category,
        "question": f"{MARKER} question number {i}?",
        "expected_files": [f"synthetic/doc{i}.txt"],
        **extra,
    }


def search_step(*queries: str) -> AgentStepResult:
    calls = tuple(
        ToolCallRequest(call_id=f"c{n}", tool_name="search_knowledge", arguments={"query": q})
        for n, q in enumerate(queries)
    )
    return AgentStepResult(text=None, tool_calls=calls, returned_model="fake-model-1")


class Model:
    def __init__(self, *steps: AgentStepResult):
        self.steps, self.calls = list(steps), 0

    async def __call__(self, _messages: Any) -> AgentStepResult:
        self.calls += 1
        return self.steps.pop(0)


class Search:
    def __init__(self, by_query: dict[str, list[str]]):
        self.by_query, self.searched = by_query, []

    async def __call__(self, query: str) -> list[Hit]:
        self.searched.append(query)
        return [Hit(n, 0.5, f"chunk-{n}-{i}") for i, n in enumerate(self.by_query.get(query, []))]


def plan(cases, **kw: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "mode": "model",
        "repeats": 2,
        "chat_model": CHAT,
        "embedding_model": EMBED,
        "tools": TOOLS,
        "cap": 1.0,
        "split": "dev",
    }
    return fsp.plan_first_step(cases, **(args | kw))


# ---- refusals before anything is read or called ---------------------------------------------------


@pytest.mark.parametrize("frozen", [True, False])
def test_the_held_out_pool_is_refused_before_any_read(frozen: bool):
    with pytest.raises(SystemExit, match="held-out pool is not available"):
        probe_pools.check_first_step_mode("held_out", frozen=frozen, mode="model", repeats=2)


def test_run_refuses_held_out_before_the_corpus_is_even_selected(monkeypatch: pytest.MonkeyPatch):
    def boom(**_k: Any):
        raise AssertionError("the corpus was selected for a held-out run")

    monkeypatch.setattr(fsp, "corpus_for", boom)
    args = SimpleNamespace(
        split="held_out", frozen=True, mode="model", repeats=2, dataset=None, passage=False
    )
    with pytest.raises(SystemExit, match="held-out"):
        asyncio.run(fsp.run(args))  # type: ignore[arg-type]


@pytest.mark.parametrize("repeats", [0, -1, probe_pools.MAX_REPEATS + 1])
def test_repeats_outside_the_limit_are_refused(repeats: int):
    with pytest.raises(SystemExit, match="--repeats"):
        probe_pools.check_first_step_mode("dev", frozen=True, mode="model", repeats=repeats)
    with pytest.raises(argparse.ArgumentTypeError):
        fsp.repeats_argument(str(repeats))


def test_the_default_repeats_are_conservative_and_the_limit_is_explicit():
    assert fsp.DEFAULT_REPEATS == 2 and probe_pools.MAX_REPEATS == 5
    probe_pools.check_first_step_mode("dev", frozen=True, mode="both", repeats=5)


def test_unknown_mode_and_regression_without_frozen_are_refused():
    with pytest.raises(SystemExit, match="unknown mode"):
        probe_pools.check_first_step_mode("dev", frozen=True, mode="bogus", repeats=1)
    with pytest.raises(SystemExit, match="needs --frozen"):
        probe_pools.check_first_step_mode("regression", frozen=False, mode="model", repeats=1)


@pytest.mark.parametrize("name", ["/abs/sealed.json", "../x.json", "a/b.json", "x.txt", ""])
def test_dataset_names_that_leave_the_datasets_folder_are_refused(name: str):
    with pytest.raises(SystemExit, match="--dataset"):
        probe_pools.check_first_step_mode(
            "dev", frozen=False, mode="model", repeats=1, datasets=[name]
        )


def test_a_dataset_file_holding_held_out_cases_is_refused_without_quoting_them(
    monkeypatch: pytest.MonkeyPatch,
):
    held = fab(1) | {"split": "held_out", "question": f"{MARKER} hidden question"}
    monkeypatch.setattr(fsp, "load_cases", lambda name: {"cases": [held]})
    args = argparse.Namespace(frozen=False, messy=False, dataset=["x.json"], split="all", ids=None)
    with pytest.raises(SystemExit) as exc:
        fsp.select_first_step_cases(args, [])
    assert "held-out" in str(exc.value) and MARKER not in str(exc.value)


# ---- pool selection and the legacy meaning of the flags -------------------------------------------


def test_frozen_without_messy_selects_the_named_pool(monkeypatch: pytest.MonkeyPatch):
    seen: dict[str, Any] = {}

    def spy(split: str, files: Any):
        seen["split"] = split
        return [fab(1), fab(2)], None

    monkeypatch.setattr(fsp, "select_probe_cases", spy)
    args = argparse.Namespace(
        frozen=True, messy=False, dataset=None, split="regression", ids=["e002"]
    )
    cases = fsp.select_first_step_cases(args, [])
    assert seen == {"split": "regression"} and [c["id"] for c in cases] == ["e002"]


def test_frozen_plus_messy_keeps_probing_the_messy_question_set(monkeypatch: pytest.MonkeyPatch):
    """Legacy contract (the second D review): ``first_step_probe --frozen --messy`` is valid and still reads the
    messy case files, not the pools."""
    loaded: list[str] = []

    def load(name: str) -> dict[str, Any]:
        loaded.append(name)
        return {"cases": [fab(1)]}

    def no_pool(*_a: Any):
        raise AssertionError("the pool selector was used for --frozen --messy")

    monkeypatch.setattr(fsp, "load_cases", load)
    monkeypatch.setattr(fsp, "select_probe_cases", no_pool)
    monkeypatch.setattr(fsp, "validate", lambda *_a, **_k: [])
    monkeypatch.setattr(fsp, "files_to_check", lambda d, f: f)
    monkeypatch.setattr(fsp, "prepare_case", lambda c, n: c)
    probe_pools.check_first_step_mode(
        "dev", frozen=True, mode="model", repeats=2
    )  # no --messy refusal
    args = argparse.Namespace(frozen=True, messy=True, dataset=None, split="dev", ids=None)
    assert [c["id"] for c in fsp.select_first_step_cases(args, [])] == ["e001"]
    assert loaded == list(retrieval_probe.MESSY_DATASETS)


def test_legacy_runs_still_read_the_legacy_case_files(monkeypatch: pytest.MonkeyPatch):
    loaded: list[str] = []

    def load(name: str) -> dict[str, Any]:
        loaded.append(name)
        return {"cases": [fab(1)]}

    monkeypatch.setattr(fsp, "load_cases", load)
    monkeypatch.setattr(fsp, "validate", lambda *_a, **_k: [])
    monkeypatch.setattr(fsp, "files_to_check", lambda d, f: f)
    monkeypatch.setattr(fsp, "prepare_case", lambda c, n: c)
    args = argparse.Namespace(frozen=False, messy=False, dataset=None, split="dev", ids=None)
    assert len(fsp.select_first_step_cases(args, [])) == len(retrieval_probe.DATASETS)
    assert loaded == list(retrieval_probe.DATASETS)


# ---- repeats, determinism, comparability ----------------------------------------------------------


def test_repeats_are_recorded_and_the_same_mocked_outputs_give_identical_rows():
    def rows() -> list[dict[str, Any]]:
        model = Model(search_step("q one"), search_step("q two"))
        search = Search({"q one": ["doc1.txt"], "q two": ["other.txt"]})
        return asyncio.run(fsp.probe_case(model, search, fab(1), repeats=2))

    first, second = rows(), rows()
    assert first == second
    assert [r["repeat"] for r in first] == [1, 2] and {r["mode"] for r in first} == {"model"}
    assert [r["found"] for r in first] == [True, False]
    assert {r["returned_model"] for r in first} == {"fake-model-1"}


def test_model_hits_are_collected_per_search_for_the_passage_metrics():
    model = Model(search_step("a", "b"))
    search = Search({"a": ["doc1.txt", "x.txt", "y.txt"], "b": ["z.txt", "w.txt"]})
    collect: dict[int, dict[str, list[list[Hit]]]] = {}
    asyncio.run(fsp.probe_case(model, search, fab(1), 1, collect=collect))
    assert [[h.filename for h in s] for s in collect[1]["e001"]] == [
        ["doc1.txt", "x.txt", "y.txt"],
        ["z.txt", "w.txt"],
    ]


def test_baseline_rows_use_the_same_measure_and_skip_what_a_question_alone_cannot_test():
    cases = [
        fab(1),
        fab(2, category="chitchat"),
        fab(3, category="inventory"),
        fab(4, history=[{"role": "user", "text": "earlier"}]),
        fab(5, expected_files=[]),
    ]
    question = cases[0]["question"]
    search = Search({question: ["doc1.txt", "b.txt"]})
    collect: dict[str, list[Hit]] = {}
    rows = asyncio.run(fsp.baseline_rows(search, cases, collect=collect))
    assert [r["id"] for r in rows] == ["e001"] and search.searched == [question]
    expected = retrieval_probe.measure(collect["e001"], ["doc1.txt"])
    assert rows[0]["mode"] == "baseline" and rows[0]["repeat"] == 0
    keys = ("found", "rank", "found_all", "chunks")
    assert {k: rows[0][k] for k in keys} == {k: expected[k] for k in keys}


def test_the_comparison_counts_every_pair_and_a_missing_search_is_a_miss():
    base = [
        {"id": "a", "found": True, "rank": 1},
        {"id": "b", "found": False, "rank": None},
    ]
    model = [
        {"id": "a", "repeat": 1, "queries": ["q"], "found": True, "rank": 2},
        {"id": "a", "repeat": 2, "queries": [], "tool": "files_query"},  # no search: a miss
        {"id": "b", "repeat": 1, "queries": ["q"], "found": True, "rank": 1},
        {"id": "b", "repeat": 2, "queries": ["q"], "found": True, "rank": 1},
    ]
    k = fsp.compare(base, model)
    assert (k["cases"], k["pairs"]) == (2, 4)
    assert (k["both_found"], k["baseline_only"], k["model_only"], k["neither"]) == (1, 1, 2, 0)
    assert (k["baseline_found"], k["model_found"]) == (2, 3)
    assert k["model_runs_that_searched"] == 3 and k["model_found_when_searched"] == 3
    assert k["unstable_ids"] == ["a"]
    assert k["baseline_mrr"] == round((1 + 1 + 0 + 0) / 4, 3)
    assert k["model_mrr"] == round((0.5 + 0 + 1 + 1) / 4, 3)


def test_the_legacy_summary_ignores_the_new_row_fields():
    row = {
        "id": "x",
        "kind": "content",
        "mode": "model",
        "repeat": 1,
        "tool": "search_knowledge",
        "queries": ["q w"],
        "expected": ["a"],
        "found": True,
        "rank": 1,
        "found_all": True,
    }
    assert fsp.summarise([row])["search_found_expected_file"] == 1


def test_the_prompt_identifier_is_stable_and_follows_the_tool_text():
    assert fsp.prompt_id(TOOLS) == fsp.prompt_id(TOOLS) and len(fsp.prompt_id(TOOLS)) == 16
    changed = (TOOLS[0].model_copy(update={"description": TOOLS[0].description + " x"}), *TOOLS[1:])
    assert fsp.prompt_id(changed) != fsp.prompt_id(TOOLS)


# ---- the plan --------------------------------------------------------------------------------------


def test_cost_grows_with_repeats_for_the_model_mode_and_not_for_the_baseline():
    cases = [fab(1), fab(2)]
    costs = [plan(cases, repeats=r)["estimated_usd"] for r in (1, 2, 3)]
    assert costs[0] < costs[1] < costs[2]
    assert plan(cases, repeats=3)["chat_calls"] == 6
    base = [plan(cases, mode="baseline", repeats=r) for r in (1, 3)]
    assert base[0]["estimated_usd"] == base[1]["estimated_usd"] and base[0]["chat_calls"] == 0
    both = plan(cases, mode="both")
    model_only = plan(cases, mode="model")
    assert both["embedding_calls"] == model_only["embedding_calls"] + 2
    assert both["estimated_usd"] > model_only["estimated_usd"]


def test_the_plan_prices_chat_and_embeddings_from_the_recorded_prices():
    case = fab(1)
    p = plan([case], repeats=1)
    nano, emb = price_for(CHAT), price_for(EMBED)
    assert p["estimated_chat_usd"] == pytest.approx(
        (
            p["estimated_chat_input_tokens"] * nano["input"]
            + fsp.OUTPUT_TOKENS_PER_STEP * nano["output"]
        )
        / 1e6
    )
    assert p["estimated_embedding_usd"] == pytest.approx(
        p["estimated_embedding_tokens"] * emb["input"] / 1e6
    )
    assert p["estimated_usd"] == p["estimated_chat_usd"] + p["estimated_embedding_usd"]
    assert p["estimated_chat_input_tokens"] >= math.ceil(len(case["question"].encode()) / 3)


def test_the_plan_is_full_precision_and_the_cap_comparison_is_exact():
    p = plan([fab(1)], mode="baseline", repeats=1, cap=1.0)
    exact = p["estimated_usd"]
    assert 0 < exact < 0.000005  # a display rounding to five places would be 0.0
    assert plan([fab(1)], mode="baseline", cap=exact)["within_cap"] is True
    assert plan([fab(1)], mode="baseline", cap=exact * 0.999)["within_cap"] is False


def test_unknown_prices_refuse_the_plan_but_the_baseline_needs_no_chat_price():
    with pytest.raises(SystemExit, match="No price recorded for gpt-unknown"):
        plan([fab(1)], chat_model="gpt-unknown")
    with pytest.raises(SystemExit, match="No price recorded for embed-unknown"):
        plan([fab(1)], mode="baseline", embedding_model="embed-unknown")
    assert plan([fab(1)], mode="baseline", chat_model="gpt-unknown")["chat_calls"] == 0


def test_chitchat_is_not_planned_and_the_plan_states_its_assumptions():
    p = plan([fab(1, category="chitchat"), fab(2)])
    assert p["cases"] == 1 and p["chat_calls"] == 2
    text = " ".join(p["assumptions"])
    assert "no cached-input discount" in text and "no output limit" in text
    assert "one call in flight" in text and p["measured"].startswith("none before")


# ---- run(): plan, cap, spending order --------------------------------------------------------------


def run_args(**kw: Any) -> argparse.Namespace:
    return argparse.Namespace(
        **{
            "split": "dev",
            "frozen": True,
            "messy": False,
            "with_messy": False,
            "dataset": None,
            "mode": "model",
            "repeats": 2,
            "ids": None,
            "passage": False,
            "plan": False,
            "cap": 1.0,
            "store": None,
            "tag": None,
            **kw,
        }
    )


@pytest.fixture
def offline_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    """run() with the corpus and cases fabricated; any store opened is recorded."""
    touched: list[str] = []
    monkeypatch.setattr(fsp, "corpus_for", lambda **_k: [])
    monkeypatch.setattr(fsp, "verify", lambda _f: None)
    monkeypatch.setattr(fsp, "select_first_step_cases", lambda _a, _f: [fab(1), fab(2)])
    monkeypatch.setattr(fsp, "RESULTS", tmp_path / "results")

    def store(**_k: Any):
        touched.append("store")
        raise AssertionError("the store was opened before the plan was accepted")

    monkeypatch.setattr(fsp, "store_for", store)
    return touched


def test_plan_prints_and_stops_with_nothing_opened_called_or_written(
    offline_run: list[str], capsys: pytest.CaptureFixture[str], tmp_path: Path
):
    asyncio.run(fsp.run(run_args(plan=True, mode="both")))
    out = capsys.readouterr().out
    assert '"estimated_usd"' in out and "Nothing was called or written" in out
    assert offline_run == [] and not (tmp_path / "results").exists()


def test_an_estimate_above_the_cap_is_refused_before_the_store_is_opened(offline_run: list[str]):
    exact = plan([fab(1), fab(2)])["estimated_usd"]
    with pytest.raises(SystemExit, match="Refusing to start"):
        asyncio.run(fsp.run(run_args(cap=exact * 0.999)))
    assert offline_run == []  # and the tripwire fixture proves no provider call


def test_a_tiny_cap_below_the_estimate_refuses_at_full_precision(offline_run: list[str]):
    with pytest.raises(SystemExit, match="Refusing to start"):
        asyncio.run(fsp.run(run_args(cap=1e-9, mode="baseline")))
    assert offline_run == []


def test_an_estimate_within_the_cap_goes_on_to_the_store_check(offline_run: list[str]):
    with pytest.raises(AssertionError, match="store was opened"):
        asyncio.run(fsp.run(run_args(cap=1.0)))
    assert offline_run == ["store"]


# ---- the meter ------------------------------------------------------------------------------------


def test_the_meter_stops_the_run_before_the_next_chat_call_once_the_cap_is_reached(
    monkeypatch: pytest.MonkeyPatch,
):
    from openai.resources.chat.completions import AsyncCompletions

    made = 0

    async def fake_create(*_a: Any, **_k: Any) -> Any:
        nonlocal made
        made += 1
        usage = SimpleNamespace(
            prompt_tokens=1_000_000, completion_tokens=0, prompt_tokens_details=None
        )
        return SimpleNamespace(model=CHAT, usage=usage)

    monkeypatch.setattr(AsyncCompletions, "create", fake_create)  # the meter wraps this one

    async def step(_messages: Any) -> AgentStepResult:
        await AsyncCompletions.create(None, model=CHAT, messages=[])  # type: ignore[arg-type]
        return search_step("q")

    meter = CostMeter(0.1)  # one call here costs 0.2 USD

    async def go() -> None:
        with meter.installed():
            await fsp.run_probe(step, Search({}), [fab(1), fab(2), fab(3)], 2)

    with pytest.raises(BudgetExceeded):
        asyncio.run(go())
    assert (
        made == 1
    )  # the second call never started: overshoot is bounded by the one call in flight
    assert meter.tripped and meter.total == pytest.approx(0.2)


# ---- the report ------------------------------------------------------------------------------------


def test_print_report_handles_a_baseline_only_report(capsys: pytest.CaptureFixture[str]):
    report = {
        "settings": {
            "mode": "baseline",
            "split": "dev",
            "repeats": 2,
            "model": None,
            "prompt_id": "abc",
        },
        "baseline_summary": {"n": 1, "found_in_results": 1, "mrr": 1.0},
        "plan": {"estimated_usd": 0.00001},
        "spend": {"estimated_total_usd": 0.0, "cap_usd": 0.1},
    }
    fsp.print_report(report, "f.json")
    out = capsys.readouterr().out
    assert "mode=baseline" in out and "baseline (question as query): 1 of 1" in out
