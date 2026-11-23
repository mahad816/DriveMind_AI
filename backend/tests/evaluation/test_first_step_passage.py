"""M1-08-E corrections: passage metrics of the model-written probe are comparable with the baseline.

Free: no key, no network, no database. Cases, chunks, anchors and model answers are FABRICATED; the one database read
(``load_resolved``) is replaced by a fake. A tripwire makes any provider call fail the test.

What these tests pin down (the reviewer's P2):
* both sides score the same eligible cases, so the denominators are equal by construction;
* a model run that wrote no search is an empty retrieval, a miss, never an exclusion;
* the equal-budget view gives the model the baseline's total of top-k chunks; the real-budget view (each search at
  top-k) is reported apart and labelled, with the searches and chunks the model really used.
"""

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from app.agents.tool_rag.agent_models import AgentStepResult, ToolCallRequest
from evaluation.rag_eval import first_step_probe as fsp
from evaluation.rag_eval import runner
from evaluation.rag_eval.anchors import AnchorMap
from evaluation.rag_eval.retrieval_probe import Hit


@pytest.fixture(autouse=True)
def no_provider_call(monkeypatch: pytest.MonkeyPatch) -> None:
    from openai.resources.chat.completions import AsyncCompletions
    from openai.resources.embeddings import AsyncEmbeddings

    async def tripwire(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a provider call was attempted")

    monkeypatch.setattr(AsyncEmbeddings, "create", tripwire)
    monkeypatch.setattr(AsyncCompletions, "create", tripwire)


def fab(i: int, *, category: str = "single_fact", **extra: Any) -> dict[str, Any]:
    return {
        "id": f"p{i:03d}",
        "split": "dev",
        "category": category,
        "language": "en",
        "expected_behavior": "answer",
        "question": f"zq-passage question number {i}?",
        "expected_files": [f"synthetic/doc{i}.txt"],
        "evidence_anchors": [{"file": f"synthetic/doc{i}.txt", "quote": "q"}],
        **extra,
    }


def chunk(i: int, n: int = 0) -> Hit:
    return Hit(f"doc{i}.txt", 0.5, f"c{i}-{n}")


def step(*queries: str) -> AgentStepResult:
    calls = tuple(
        ToolCallRequest(call_id=f"c{n}", tool_name="search_knowledge", arguments={"query": q})
        for n, q in enumerate(queries)
    )
    return AgentStepResult(text=None, tool_calls=calls, returned_model="fake")


class Model:
    def __init__(self, *steps: AgentStepResult):
        self.steps = list(steps)

    async def __call__(self, _messages: Any) -> AgentStepResult:
        return self.steps.pop(0)


class Search:
    def __init__(self, by_query: dict[str, list[Hit]]):
        self.by_query = by_query

    async def __call__(self, query: str) -> list[Hit]:
        return list(self.by_query.get(query, []))


# ---- what is recorded per run (the reviewer's reproduction first) ----------------------------------


def test_a_run_without_a_search_is_recorded_as_an_empty_retrieval():
    no_search = AgentStepResult(text="an answer", tool_calls=(), returned_model="fake")
    collect: dict[int, dict[str, list[list[Hit]]]] = {}
    asyncio.run(fsp.probe_case(Model(no_search), Search({}), fab(1), 1, collect=collect))
    assert collect.get(1, {}).get("p001") == []


def test_a_listing_tool_run_is_also_an_empty_retrieval():
    listing = AgentStepResult(
        text=None,
        tool_calls=(ToolCallRequest(call_id="x", tool_name="files_query", arguments={}),),
        returned_model="fake",
    )
    collect: dict[int, dict[str, list[list[Hit]]]] = {}
    asyncio.run(fsp.probe_case(Model(listing), Search({}), fab(1), 1, collect=collect))
    assert collect[1]["p001"] == []


def test_every_search_of_a_step_is_kept_apart_and_uncut():
    collect: dict[int, dict[str, list[list[Hit]]]] = {}
    search = Search({"a": [chunk(1, 0), chunk(9, 1), chunk(9, 2)], "b": [chunk(8, 0), chunk(8, 1)]})
    asyncio.run(fsp.probe_case(Model(step("a", "b")), search, fab(1), 1, collect=collect))
    assert [len(s) for s in collect[1]["p001"]] == [3, 2]


@pytest.mark.parametrize(
    "case",
    [
        fab(2, category="inventory"),
        fab(3, history=[{"role": "user", "text": "earlier"}]),
        fab(4, expected_files=[]),
    ],
)
def test_cases_the_baseline_cannot_score_are_not_collected_for_the_model_either(case):
    collect: dict[int, dict[str, list[list[Hit]]]] = {}
    asyncio.run(
        fsp.probe_case(Model(step("a")), Search({"a": [chunk(1)]}), case, 1, collect=collect)
    )
    assert case["id"] not in collect.get(1, {})


def test_the_passage_cases_are_exactly_the_baseline_eligible_cases():
    cases = [
        fab(1),
        fab(2, category="inventory"),
        fab(3, category="chitchat"),
        fab(4, history=[{"role": "user", "text": "x"}]),
        fab(5, expected_files=[]),
        fab(6),
    ]
    assert [c["id"] for c in fsp.passage_cases(cases)] == ["p001", "p006"]
    assert [c["id"] for c in fsp.passage_cases(cases)] == [
        c["id"] for c in cases if fsp.baseline_eligible(c)
    ]


# ---- the two retrieval budgets -----------------------------------------------------------------------


def test_equal_budget_takes_chunks_round_robin_and_stops_at_top_k():
    a = [chunk(1, 0), chunk(1, 1), chunk(1, 2)]
    b = [chunk(2, 0), chunk(2, 1)]
    got = fsp.equal_budget_hits([a, b], top_k=3)
    assert [h.chunk_id for h in got] == ["c1-0", "c2-0", "c1-1"]


def test_equal_budget_skips_a_chunk_both_searches_returned_and_spends_the_slot_on_the_next():
    a = [chunk(1, 0), chunk(1, 1)]
    b = [chunk(1, 0), chunk(2, 0)]
    assert [h.chunk_id for h in fsp.equal_budget_hits([a, b], top_k=3)] == ["c1-0", "c2-0", "c1-1"]


def test_with_one_search_the_equal_budget_is_the_baselines_own_top_k():
    only = [chunk(1, n) for n in range(6)]
    assert fsp.equal_budget_hits([only], top_k=4) == only[:4]


def test_equal_budget_of_no_search_is_empty_and_real_budget_cuts_each_search():
    assert fsp.equal_budget_hits([], top_k=4) == []
    assert fsp.real_budget_hits([], top_k=4) == []
    a = [chunk(1, n) for n in range(5)]
    b = [chunk(2, n) for n in range(5)]
    got = fsp.real_budget_hits([a, b], top_k=2)
    assert [h.chunk_id for h in got] == ["c1-0", "c1-1", "c2-0", "c2-1"]


def test_the_budget_summary_shows_the_extra_searches_and_chunks_the_model_used():
    collect = {
        1: {"p001": [[chunk(1, n) for n in range(5)], [chunk(2, n) for n in range(5)]], "p002": []},
        2: {"p001": [[chunk(1, 0)]], "p002": [[chunk(3, 0), chunk(3, 1)]]},
    }
    s = fsp.budget_summary(collect, top_k=3)
    assert s["baseline_chunks_at_most"] == 3
    assert s["model_searches_mean"] == pytest.approx((2 + 0 + 1 + 1) / 4)
    assert s["model_chunks_mean_real_budget"] == pytest.approx((6 + 0 + 1 + 2) / 4)
    assert s["model_runs_without_search"] == 1 and s["model_runs"] == 4


# ---- the passage report: same cases, same denominator, a miss is a miss ----------------------------


def fake_resolved(cases: list[dict[str, Any]]) -> SimpleNamespace:
    anchors, names = {}, {}
    for c in cases:
        n = c["id"][-1]  # p001 -> "1"
        names[c["expected_files"][0] if c["expected_files"] else "x"] = f"doc{n}.txt"
        anchors[c["id"]] = [AnchorMap(f"synthetic/doc{n}.txt", "q", "whole", (f"c{n}-0",))]
    return SimpleNamespace(database=True, anchors=anchors, names=names)


@pytest.fixture
def resolved(monkeypatch: pytest.MonkeyPatch):
    async def load(_sessions, by_id, _rows, _files):
        return fake_resolved(list(by_id.values()))

    monkeypatch.setattr(runner, "load_resolved", load)


def comparison(cases, base_hits, collect, top_k=3) -> dict[str, Any]:
    return asyncio.run(fsp.passage_comparison(None, cases, [], base_hits, collect, top_k=top_k))


def overall(section: dict[str, Any]) -> dict[str, Any]:
    (block,) = section["pools"].values()
    return block["overall"]


def test_both_sides_score_the_same_cases_and_a_no_search_run_counts_as_a_miss(resolved):
    cases = [fab(1), fab(2), fab(3, category="inventory"), fab(4, history=[{"role": "user"}])]
    base = {"p001": [chunk(1, 0)], "p002": [chunk(2, 0)]}
    collect = {1: {"p001": [[chunk(1, 0)]], "p002": []}}  # p002: the model wrote no search
    out = comparison(cases, base, collect)
    assert out["same_cases"] is True and out["cases"] == 2
    assert overall(out["baseline"])["answerable_cases"] == 2
    for view in ("model_equal_budget", "model_real_budget"):
        model = overall(out[view]["repeat_1"])
        assert model["answerable_cases"] == 2 and model["measured"] == 2  # same denominator
        assert (model["any_found"]["passed"], model["any_found"]["n"]) == (1, 2)  # the miss counts
    assert (overall(out["baseline"])["any_found"]["passed"]) == 2


def test_a_case_missing_from_a_repeat_is_still_scored_as_a_miss_not_dropped(resolved):
    cases = [fab(1), fab(2)]
    base = {"p001": [chunk(1, 0)], "p002": [chunk(2, 0)]}
    out = comparison(cases, base, {1: {"p001": [[chunk(1, 0)]]}})  # nothing recorded for p002
    assert overall(out["model_equal_budget"]["repeat_1"])["answerable_cases"] == 2


def test_the_equal_budget_does_not_hide_the_advantage_of_a_second_search(resolved):
    """The anchor is the first chunk of the model's second search. With a total budget of one chunk the baseline
    treatment cannot see it; the real budget (one chunk per search) does, and is reported apart."""
    cases = [fab(1)]
    base = {"p001": [chunk(9, 0)]}
    collect = {1: {"p001": [[chunk(8, 0)], [chunk(1, 0)]]}}
    out = comparison(cases, base, collect, top_k=1)
    assert overall(out["model_equal_budget"]["repeat_1"])["any_found"]["passed"] == 0
    assert overall(out["model_real_budget"]["repeat_1"])["any_found"]["passed"] == 1
    assert out["budget"]["model_searches_mean"] == 2
    assert "not an equal budget" in out["labels"]["model_real_budget"]


def test_passage_recall_coverage_and_rank_are_computed_per_repeat(resolved):
    cases = [fab(1), fab(2)]
    base = {"p001": [chunk(1, 0)], "p002": [chunk(7, 0), chunk(2, 0)]}
    collect = {
        1: {"p001": [[chunk(5, 0), chunk(1, 0)]], "p002": [[chunk(2, 0)]]},
        2: {"p001": [], "p002": [[chunk(2, 0)]]},
    }
    out = comparison(cases, base, collect, top_k=3)
    first = overall(out["model_equal_budget"]["repeat_1"])
    second = overall(out["model_equal_budget"]["repeat_2"])
    assert first["any_found"]["passed"] == 2 and first["mrr"] == round((1 / 2 + 1) / 2, 3)
    assert first["mean_anchor_coverage"] == 1.0
    assert second["any_found"]["passed"] == 1 and second["mean_anchor_coverage"] == 0.5
    assert second["mrr"] == 0.5
    assert overall(out["baseline"])["mrr"] == round((1 + 1 / 2) / 2, 3)


def test_a_different_case_set_on_the_two_sides_is_flagged_not_hidden():
    base = {"rows": [{"id": "a"}]}
    assert fsp.same_cases(base, {"rows": [{"id": "a"}, {"id": "b"}]}) is False
    assert fsp.same_cases(base, {"rows": [{"id": "a"}]}) is True
    assert (
        fsp.same_cases(base, {"status": "unavailable"}) is False
    )  # a missing side is never "the same"


# ---- the paired file-level comparison ------------------------------------------------------------------


def test_a_baseline_case_without_all_repeats_is_reported_unpaired_not_silently_skipped():
    base = [{"id": "a", "found": True, "rank": 1}, {"id": "b", "found": True, "rank": 1}]
    model = [
        {"id": "a", "repeat": 1, "queries": ["q"], "found": True, "rank": 1},
        {"id": "a", "repeat": 2, "queries": ["q"], "found": True, "rank": 1},
        {"id": "b", "repeat": 1, "queries": ["q"], "found": True, "rank": 1},  # repeat 2 missing
    ]
    k = fsp.compare(base, model)
    assert k["unpaired_ids"] == ["b"] and k["cases"] == 1 and k["pairs"] == 2
    assert k["repeats_per_case"] == 2


def test_the_comparison_note_says_the_searches_are_not_budget_matched():
    k = fsp.compare([{"id": "a", "found": True, "rank": 1}], [])
    assert "several searches" in k["note"]


# ---- cost honesty ----------------------------------------------------------------------------------------


def test_the_plan_and_the_cap_help_do_not_claim_a_hard_provider_limit():
    p = fsp.plan_first_step(
        [fab(1)],
        mode="model",
        repeats=1,
        chat_model="gpt-5.4-nano",
        embedding_model="text-embedding-3-small",
        tools=(),
        cap=1.0,
        split="dev",
    )
    assert p["cap_is_hard_limit"] is False
    text = " ".join(p["assumptions"])
    assert "not a provider-side limit" in text and "retries" in text and "reasoning" in text
    help_text = " ".join(fsp.build_parser().format_help().split())
    assert "hard spend cap" not in help_text and "between calls" in help_text


def test_the_equal_budget_gives_each_search_its_turn_instead_of_favouring_the_first(resolved):
    """Two searches, a total budget of two chunks. The anchor is the best chunk of the SECOND search. Taking the first
    search's chunks first would use the whole budget on it; taking turns reaches the anchor."""
    cases = [fab(1)]
    base = {"p001": [chunk(9, 0), chunk(9, 1)]}
    collect = {1: {"p001": [[chunk(8, 0), chunk(8, 1)], [chunk(1, 0)]]}}
    out = comparison(cases, base, collect, top_k=2)
    assert overall(out["model_equal_budget"]["repeat_1"])["any_found"]["passed"] == 1
    assert (
        overall(out["model_equal_budget"]["repeat_1"])["mean_chunks"] == 2
    )  # still only two chunks
