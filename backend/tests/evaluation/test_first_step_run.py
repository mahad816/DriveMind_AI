"""M1-08-E final P2: ``--passage`` is only allowed with ``--mode both``, and a ``both`` run reports what it measured.

``run()``-level tests with fabricated cases and fakes for everything that would touch a store, a database or a
provider: the corpus, the verified index, the chat service, the sessions, the retriever and the database read of the
passage metrics. A tripwire makes any real provider call fail the test. No sealed file is read.

The defect: ``--passage`` with the default mode (``model``) wrote ``passage.baseline`` although no baseline search
had run, so it showed 0 found for a baseline that was never measured.
"""

import argparse
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.agents.tool_rag.agent_models import AgentStepResult, ToolCallRequest
from evaluation.rag_eval import first_step_probe as fsp
from evaluation.rag_eval import probe_pools, runner
from evaluation.rag_eval.anchors import AnchorMap
from evaluation.rag_eval.retrieval_probe import Hit
from evaluation.rag_eval.target import application_defaults


@pytest.fixture(autouse=True)
def no_provider_call(monkeypatch: pytest.MonkeyPatch) -> None:
    from openai.resources.chat.completions import AsyncCompletions
    from openai.resources.embeddings import AsyncEmbeddings

    async def tripwire(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a provider call was attempted")

    monkeypatch.setattr(AsyncEmbeddings, "create", tripwire)
    monkeypatch.setattr(AsyncCompletions, "create", tripwire)


def fab(i: int) -> dict[str, Any]:
    return {
        "id": f"p{i:03d}",
        "split": "dev",
        "category": "single_fact",
        "language": "en",
        "expected_behavior": "answer",
        "question": f"zq-run question number {i}?",
        "expected_files": [f"synthetic/doc{i}.txt"],
        "evidence_anchors": [{"file": f"synthetic/doc{i}.txt", "quote": "q"}],
    }


def chunk(i: int, n: int = 0) -> Hit:
    return Hit(f"doc{i}.txt", 0.5, f"c{i}-{n}")


def search_step(query: str) -> AgentStepResult:
    call = ToolCallRequest(call_id="c", tool_name="search_knowledge", arguments={"query": query})
    return AgentStepResult(text=None, tool_calls=(call,), returned_model="fake-model")


NO_SEARCH = AgentStepResult(text="an answer", tool_calls=(), returned_model="fake-model")


def run_args(**kw: Any) -> argparse.Namespace:
    return argparse.Namespace(
        **{
            "split": "dev",
            "frozen": True,
            "messy": False,
            "with_messy": False,
            "dataset": None,
            "mode": "model",  # the default of the command
            "repeats": 2,
            "ids": None,
            "passage": False,
            "plan": False,
            "cap": 5.0,
            "store": None,
            "tag": None,
            **kw,
        }
    )


class World:
    """Everything run() reaches, replaced by fakes that record what was used."""

    def __init__(self, tmp_path: Path):
        self.events: list[str] = []
        self.results = tmp_path / "results"
        self.steps: list[AgentStepResult] = []
        q1, q2 = fab(1)["question"], fab(2)["question"]
        # baseline: the question of p001 finds its file, the question of p002 does not
        self.by_query = {
            q1: [chunk(1, 0)],
            q2: [chunk(9, 0)],
            "a1": [chunk(1, 0)],
            "a2": [chunk(2, 0)],
        }

    def report(self) -> dict[str, Any]:
        (path,) = self.results.glob("first_step_*.json")
        return json.loads(path.read_text())


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> World:
    w = World(tmp_path)
    defaults = application_defaults()
    settings = SimpleNamespace(
        chat_model=defaults["chat_model"],
        embedding_model=defaults["embedding_model"],
        retrieval_top_k=3,
    )

    def corpus_for(**_k: Any) -> list[Any]:
        w.events.append("corpus")
        return []

    async def require_verified_index(_store: Any, **_k: Any) -> Any:
        w.events.append("verify-index")
        return SimpleNamespace(settings=settings)

    class FakeChat:
        model_name = "fake-chat"

        def __init__(self, _settings: Any):
            w.events.append("chat-service")

        async def step(self, **_k: Any) -> AgentStepResult:
            w.events.append("chat-call")
            return w.steps.pop(0)

    class Sessions:
        def __call__(self) -> "Sessions":
            return self

        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_a: Any) -> None:
            return None

    def make_search(_retriever: Any) -> Any:
        async def search(query: str) -> list[Hit]:
            w.events.append(f"search:{query}")
            return list(w.by_query.get(query, []))

        return search

    async def load_resolved(_sessions: Any, by_id: dict[str, Any], _rows: Any, _files: Any) -> Any:
        anchors = {
            i: [AnchorMap(f"synthetic/doc{i[-1]}.txt", "q", "whole", (f"c{i[-1]}-0",))]
            for i in by_id
        }
        return SimpleNamespace(database=True, anchors=anchors, names={})

    monkeypatch.setattr(fsp, "corpus_for", corpus_for)
    monkeypatch.setattr(fsp, "verify", lambda _f: None)
    monkeypatch.setattr(fsp, "select_first_step_cases", lambda _a, _f: [fab(1), fab(2)])
    monkeypatch.setattr(
        fsp, "store_for", lambda **_k: SimpleNamespace(database="drivemind_eval_v3")
    )
    monkeypatch.setattr(fsp, "require_verified_index", require_verified_index)
    monkeypatch.setattr(fsp, "OpenAIAgentChatService", FakeChat)
    monkeypatch.setattr(fsp, "session_factory", lambda _s: Sessions())
    monkeypatch.setattr(fsp, "HybridRetriever", lambda _db, _s: object())
    monkeypatch.setattr(fsp, "make_search", make_search)
    monkeypatch.setattr(fsp, "RESULTS", w.results)
    monkeypatch.setattr(runner, "load_resolved", load_resolved)
    return w


def overall(section: dict[str, Any]) -> dict[str, Any]:
    (block,) = section["pools"].values()
    return block["overall"]


# ---- --passage is refused unless the baseline is measured -------------------------------------------


@pytest.mark.parametrize("mode", ["model", "baseline"])
def test_passage_is_refused_unless_the_mode_is_both_and_nothing_runs(world: World, mode: str):
    with pytest.raises(SystemExit, match=r"--passage .*--mode both"):
        asyncio.run(fsp.run(run_args(mode=mode, passage=True)))
    assert (
        world.events == []
    )  # not even the corpus: refused before anything is read, called or opened
    assert not world.results.exists()


def test_passage_with_the_default_mode_is_refused(world: World):
    parsed = fsp.build_parser().parse_args(["--frozen", "--passage", "--cap", "1"])
    assert parsed.mode == "model"  # the default of the command is not both
    with pytest.raises(SystemExit, match="--mode both"):
        asyncio.run(fsp.run(parsed))
    assert world.events == []


def test_the_check_names_the_required_combination_and_allows_both():
    for mode in ("model", "baseline"):
        with pytest.raises(SystemExit, match=r"--passage .*--mode both"):
            probe_pools.check_first_step_mode(
                "dev", frozen=True, mode=mode, repeats=2, passage=True
            )
    probe_pools.check_first_step_mode("dev", frozen=True, mode="both", repeats=2, passage=True)
    for mode in ("model", "baseline", "both"):  # without --passage nothing changes
        probe_pools.check_first_step_mode("dev", frozen=True, mode=mode, repeats=2)


def test_the_cap_and_split_refusals_still_come_first_or_alongside(world: World):
    with pytest.raises(SystemExit, match="held-out"):
        asyncio.run(fsp.run(run_args(split="held_out", mode="both", passage=True)))
    assert world.events == []


# ---- a valid both run reports what was measured --------------------------------------------------------


def test_a_both_run_with_passage_reports_the_measured_baseline_and_model_views(world: World):
    # p001 repeat 1 searches and finds, repeat 2 writes no search; p002 searches and finds both times
    world.steps = [search_step("a1"), NO_SEARCH, search_step("a2"), search_step("a2")]
    asyncio.run(fsp.run(run_args(mode="both", passage=True)))
    report = world.report()
    # what the baseline really did: p001 found, p002 not
    assert [r["found"] for r in report["baseline_rows"]] == [True, False]
    baseline = overall(report["passage"]["baseline"])
    assert (baseline["any_found"]["passed"], baseline["any_found"]["n"]) == (1, 2)
    # model repeats, same denominator, the no-search run is a miss
    first = overall(report["passage"]["model_equal_budget"]["repeat_1"])
    second = overall(report["passage"]["model_equal_budget"]["repeat_2"])
    assert (first["any_found"]["passed"], first["any_found"]["n"]) == (2, 2)
    assert (second["any_found"]["passed"], second["any_found"]["n"]) == (1, 2)
    assert report["passage"]["same_cases"] is True and report["passage"]["cases"] == 2
    budget = report["passage"]["budget"]
    assert (budget["model_runs"], budget["model_runs_without_search"]) == (4, 1)
    # file level agrees with the passage level on the paired comparison
    cmp = report["comparison"]
    assert (cmp["pairs"], cmp["baseline_found"], cmp["model_found"]) == (4, 2, 3)
    assert cmp["unpaired_ids"] == [] and report["settings"]["mode"] == "both"
    # one baseline search per eligible case, one model search per search step: nothing else was searched
    searches = [e for e in world.events if e.startswith("search:")]
    assert len(searches) == 2 + 3 and world.events.count("chat-call") == 4


def test_equal_budget_metrics_stay_consistent_in_a_run(world: World):
    world.by_query["a1"] = [chunk(8, 0), chunk(8, 1), chunk(1, 0)]  # the anchor is third of three
    world.steps = [search_step("a1"), search_step("a1"), search_step("a2"), search_step("a2")]
    asyncio.run(fsp.run(run_args(mode="both", passage=True)))
    passage = json.loads(next(world.results.glob("*.json")).read_text())["passage"]
    # the retriever's own top-k is 3 here, so the single search keeps all three and finds p001's anchor at rank 3
    first = overall(passage["model_equal_budget"]["repeat_1"])
    assert first["any_found"]["passed"] == 2 and first["first_rank_distribution"]["3"] == 1
    assert overall(passage["model_real_budget"]["repeat_1"])["any_found"]["passed"] == 2


# ---- the other modes keep their behaviour ------------------------------------------------------------------


def test_model_mode_without_passage_still_runs_and_writes_no_baseline(world: World):
    world.steps = [search_step("a1"), search_step("a1"), search_step("a2"), search_step("a2")]
    asyncio.run(fsp.run(run_args(mode="model")))
    report = world.report()
    assert "baseline_rows" not in report and "comparison" not in report and "passage" not in report
    assert report["summary"]["content_runs"] == 4


def test_baseline_mode_without_passage_makes_no_chat_call(world: World):
    asyncio.run(fsp.run(run_args(mode="baseline")))
    report = world.report()
    assert "rows" not in report and len(report["baseline_rows"]) == 2
    assert "chat-call" not in world.events and report["settings"]["model"] is None
