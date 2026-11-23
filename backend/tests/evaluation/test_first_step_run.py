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
        self.steps: list[Any] = []  # AgentStepResult, or an exception to raise at that call
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
            item = w.steps.pop(0)
            if isinstance(item, BaseException):  # a scripted failure (provider error, cap reached)
                raise item
            return item

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
    monkeypatch.setattr(fsp, "make_chat_service", lambda s: FakeChat(s))
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


# ---- M1-08-F: paid rows survive a failure, and a report says whether it is complete ------------------------


def incomplete(world: World) -> list[Path]:
    return sorted(world.results.glob("first_step_*_incomplete.json"))


def finished(world: World) -> list[Path]:
    return [p for p in world.results.glob("first_step_*.json") if "_incomplete" not in p.name]


def test_a_provider_failure_after_partial_progress_keeps_every_paid_row(world: World):
    from app.llm.base import ChatError

    # both baseline searches are done; p001 ran twice; the first call for p002 fails
    world.steps = [search_step("a1"), search_step("a1"), ChatError("Agent provider request failed")]
    with pytest.raises(SystemExit, match=r"incomplete.*ChatError|ChatError.*incomplete"):
        asyncio.run(fsp.run(run_args(mode="both")))
    (path,) = incomplete(world)
    saved = json.loads(path.read_text())
    assert saved["status"] == "incomplete" and saved["complete"] is False
    assert "ChatError" in saved["incomplete_reason"]
    assert len(saved["baseline_rows"]) == 2 and [r["repeat"] for r in saved["rows"]] == [1, 2]
    assert saved["spend"]["cap_usd"] == 5.0 and "plan" in saved
    # nothing computed from a partial run can be mistaken for a result
    for key in ("summary", "baseline_summary", "comparison", "passage"):
        assert key not in saved
    assert finished(world) == []


def test_a_cap_stop_in_the_model_phase_keeps_the_paid_baseline_rows(world: World):
    from evaluation.rag_eval.meter import BudgetExceeded

    world.steps = [BudgetExceeded("estimated spend $0.0010 reached the $0.00 cap")]
    with pytest.raises(SystemExit, match="STOPPED"):
        asyncio.run(fsp.run(run_args(mode="both")))
    (path,) = incomplete(world)
    saved = json.loads(path.read_text())
    assert len(saved["baseline_rows"]) == 2 and saved["rows"] == []
    assert "reached" in saved["incomplete_reason"] and "comparison" not in saved


def test_a_failure_in_the_baseline_phase_keeps_the_rows_already_made(
    world: World, monkeypatch: pytest.MonkeyPatch
):
    calls = {"n": 0}

    def make_search(_retriever: Any) -> Any:
        async def search(query: str) -> list[Hit]:
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("retrieval failed")
            return [chunk(1, 0)]

        return search

    monkeypatch.setattr(fsp, "make_search", make_search)
    with pytest.raises(SystemExit, match="incomplete"):
        asyncio.run(fsp.run(run_args(mode="baseline")))
    (path,) = incomplete(world)
    assert len(json.loads(path.read_text())["baseline_rows"]) == 1


@pytest.mark.parametrize("failing", ["compare", "passage_comparison"])
def test_a_failure_while_building_the_report_keeps_the_rows_marked_rows_only(
    world: World, monkeypatch: pytest.MonkeyPatch, failing: str
):
    world.steps = [search_step("a1"), search_step("a1"), search_step("a2"), search_step("a2")]

    async def boom_async(*_a: Any, **_k: Any) -> Any:
        raise ValueError("report step failed")

    def boom(*_a: Any, **_k: Any) -> Any:
        raise ValueError("report step failed")

    monkeypatch.setattr(fsp, failing, boom_async if failing == "passage_comparison" else boom)
    with pytest.raises(SystemExit, match=r"rows_only|not complete") as caught:
        asyncio.run(fsp.run(run_args(mode="both", passage=True)))
    assert "ValueError" in str(caught.value)
    (path,) = finished(world)  # one file, at the final name, but it says what it is
    saved = json.loads(path.read_text())
    assert saved["status"] == "rows_only" and saved["complete"] is False
    assert len(saved["rows"]) == 4 and len(saved["baseline_rows"]) == 2
    assert "comparison" not in saved and "passage" not in saved
    assert incomplete(world) == []


def test_a_finished_run_is_marked_complete_and_leaves_no_temporary_file(world: World):
    world.steps = [search_step("a1"), search_step("a1"), search_step("a2"), search_step("a2")]
    asyncio.run(fsp.run(run_args(mode="both")))
    report = world.report()
    assert report["status"] == "complete" and report["complete"] is True
    assert sorted(p.suffix for p in world.results.iterdir()) == [".json"]


def test_two_runs_with_the_same_tag_never_overwrite_each_other(world: World):
    for _ in range(2):
        world.steps = [search_step("a1"), search_step("a1"), search_step("a2"), search_step("a2")]
        asyncio.run(fsp.run(run_args(mode="model", tag="same")))
    assert len(finished(world)) == 2


def test_the_atomic_writer_keeps_the_old_file_when_serialising_fails(tmp_path: Path):
    target = tmp_path / "r.json"
    target.write_text('{"old": true}\n')
    with pytest.raises(TypeError):
        fsp.write_json_atomic(target, {"bad": {1, 2}})
    assert json.loads(target.read_text()) == {"old": True}
    assert [p.name for p in tmp_path.iterdir()] == ["r.json"]


def test_the_atomic_writer_leaves_no_final_file_when_the_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import os

    def boom(*_a: Any, **_k: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    target = tmp_path / "r.json"
    with pytest.raises(OSError):
        fsp.write_json_atomic(target, {"a": 1})
    assert list(tmp_path.iterdir()) == []


# ---- an empty comparison is not a successful pairing -----------------------------------------------------


def test_a_comparison_without_pairs_says_it_paired_nothing():
    base = [{"id": "a", "found": True, "rank": 1}]
    none = fsp.compare(base, [])
    assert none["paired"] is False and none["pairs"] == 0 and none["baseline_found_pct"] is None
    partial = fsp.compare(
        base, [{"id": "a", "repeat": 1, "queries": [], "found": False, "rank": None}]
    )
    assert partial["paired"] is True and partial["pairs"] == 1


def test_two_empty_passage_sections_are_not_the_same_cases():
    assert fsp.same_cases({"rows": []}, {"rows": []}) is False


def test_the_printed_report_does_not_announce_a_pairing_that_did_not_happen(
    capsys: pytest.CaptureFixture[str],
):
    report: dict[str, Any] = {
        "settings": {
            "mode": "both",
            "split": "dev",
            "repeats": 2,
            "model": "m",
            "prompt_id": "p",
        },
        "comparison": fsp.compare([{"id": "a", "found": True, "rank": 1}], []),
        "plan": {"estimated_usd": 0.0},
        "spend": {"estimated_total_usd": 0.0, "cap_usd": 1.0},
    }
    fsp.print_report(report, "x.json")
    out = capsys.readouterr().out
    assert "nothing was compared" in out and "paired comparison over" not in out


# ---- refusals before any spend, at the level of run() ----------------------------------------------------


def test_an_invalid_index_stops_the_run_before_any_chat_or_search(
    world: World, monkeypatch: pytest.MonkeyPatch
):
    async def refuse(_store: Any, **_k: Any) -> Any:
        raise SystemExit("INDEX NOT VERIFIED: stale")

    monkeypatch.setattr(fsp, "require_verified_index", refuse)
    with pytest.raises(SystemExit, match="INDEX NOT VERIFIED"):
        asyncio.run(fsp.run(run_args(mode="both")))
    assert world.events == ["corpus"] and not world.results.exists()


def test_a_cap_below_the_estimate_refuses_before_the_index_is_even_opened(world: World):
    with pytest.raises(SystemExit, match="Refusing to start"):
        asyncio.run(fsp.run(run_args(mode="both", cap=0.0000001)))
    assert world.events == ["corpus"] and not world.results.exists()


def test_a_plan_is_free_and_writes_nothing(world: World, capsys: pytest.CaptureFixture[str]):
    asyncio.run(fsp.run(run_args(mode="both", plan=True)))
    assert world.events == ["corpus"] and not world.results.exists()
    assert "Nothing was called" in capsys.readouterr().out


def _price_of(chat_model: str) -> float:
    plan = fsp.plan_first_step(
        [fab(1), fab(2)],
        mode="both",
        repeats=2,
        chat_model=chat_model,
        embedding_model=application_defaults()["embedding_model"],
        tools=tuple(fsp.ToolDefinition.model_validate(d) for d in fsp.ToolRegistry().definitions()),
        cap=99.0,
        split="dev",
    )
    return float(plan["estimated_usd"])


def test_a_store_that_uses_a_dearer_model_is_re_planned_against_the_cap(
    world: World, monkeypatch: pytest.MonkeyPatch
):
    cheap, dear = _price_of(application_defaults()["chat_model"]), _price_of("gpt-5.4")
    assert dear > cheap
    world.steps = [search_step("a1")] * 4

    async def dearer(_store: Any, **_k: Any) -> Any:
        world.events.append("verify-index")
        return SimpleNamespace(
            settings=SimpleNamespace(
                chat_model="gpt-5.4",
                embedding_model=application_defaults()["embedding_model"],
                retrieval_top_k=3,
            )
        )

    monkeypatch.setattr(fsp, "require_verified_index", dearer)
    with pytest.raises(SystemExit, match="Refusing to start"):
        asyncio.run(fsp.run(run_args(mode="both", cap=(cheap + dear) / 2)))
    assert "chat-service" not in world.events and "chat-call" not in world.events


def test_a_store_that_uses_an_unpriced_model_refuses_before_the_chat_service_exists(
    world: World, monkeypatch: pytest.MonkeyPatch
):
    async def unpriced(_store: Any, **_k: Any) -> Any:
        world.events.append("verify-index")
        return SimpleNamespace(
            settings=SimpleNamespace(
                chat_model="zz-unpriced-model",
                embedding_model=application_defaults()["embedding_model"],
                retrieval_top_k=3,
            )
        )

    monkeypatch.setattr(fsp, "require_verified_index", unpriced)
    with pytest.raises(SystemExit, match="No price recorded"):
        asyncio.run(fsp.run(run_args(mode="both")))
    assert "chat-service" not in world.events and "chat-call" not in world.events


def test_the_run_installs_a_meter_with_the_retry_free_limited_strict_settings(
    world: World, monkeypatch: pytest.MonkeyPatch
):
    seen: list[dict[str, Any]] = []
    real = fsp.CostMeter

    def recording(cap: float, **kw: Any) -> Any:
        seen.append(kw)
        return real(cap, **kw)

    monkeypatch.setattr(fsp, "CostMeter", recording)
    asyncio.run(fsp.run(run_args(mode="baseline")))
    assert seen == [
        {
            "max_output_tokens": fsp.MAX_OUTPUT_TOKENS_PER_STEP,
            "require_usage": True,
            "require_complete": True,
        }
    ]


# ---- D, E and the shared case selection agree ----------------------------------------------------------------


@pytest.mark.parametrize("split", ["dev", "test", "all"])
def test_the_baseline_of_e_scores_exactly_the_cases_the_plain_probe_of_d_scores(split: str):
    """Both probes must compare like with like. On the committed question set the case rule of the first-step
    probe (``baseline_eligible``) selects the same cases as the retrieval probe (``split_cases``)."""
    from evaluation.rag_eval import pools
    from evaluation.rag_eval.retrieval_probe import split_cases

    cases = pools.select(pools.load_question_set()["cases"], split)
    answerable = {c["id"] for c in split_cases(cases)[0]}
    eligible = {c["id"] for c in cases if fsp.baseline_eligible(c)}
    assert eligible == answerable and eligible  # non-empty: the check really compared something


# ---- M1-08-F corrections: cancellation, truncation, no overwrite -----------------------------------------


def only_incomplete(world: World) -> dict[str, Any]:
    (path,) = incomplete(world)
    return json.loads(path.read_text())


def assert_marked_incomplete(saved: dict[str, Any], kind: str) -> None:
    assert saved["status"] == "incomplete" and saved["complete"] is False
    assert saved["incomplete_kind"] == kind
    for key in ("summary", "baseline_summary", "comparison", "passage"):
        assert key not in saved  # nothing derived from a partial run


def test_cancellation_after_the_baseline_keeps_its_rows_and_is_still_a_cancellation(world: World):
    world.steps = [asyncio.CancelledError()]
    with pytest.raises(
        asyncio.CancelledError
    ):  # cancellation is not turned into an exit and not swallowed
        asyncio.run(fsp.run(run_args(mode="both")))
    saved = only_incomplete(world)
    assert_marked_incomplete(saved, "cancelled")
    assert len(saved["baseline_rows"]) == 2 and saved["rows"] == []
    assert finished(world) == [] and world.events.count("chat-call") == 1  # no paid call after it


def test_cancellation_after_partial_model_results_keeps_every_completed_row(world: World):
    world.steps = [search_step("a1"), search_step("a1"), asyncio.CancelledError()]
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(fsp.run(run_args(mode="both")))
    saved = only_incomplete(world)
    assert_marked_incomplete(saved, "cancelled")
    assert [r["repeat"] for r in saved["rows"]] == [1, 2] and len(saved["baseline_rows"]) == 2
    assert world.events.count("chat-call") == 3


def test_cancellation_before_any_result_still_writes_an_empty_incomplete_file(
    world: World, monkeypatch: pytest.MonkeyPatch
):
    def make_search(_retriever: Any) -> Any:
        async def search(_query: str) -> list[Hit]:
            raise asyncio.CancelledError

        return search

    monkeypatch.setattr(fsp, "make_search", make_search)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(fsp.run(run_args(mode="both")))
    saved = only_incomplete(world)
    assert_marked_incomplete(saved, "cancelled")
    assert saved["rows"] == [] and saved["baseline_rows"] == []


def test_a_keyboard_interrupt_is_kept_and_re_raised(world: World):
    world.steps = [search_step("a1"), KeyboardInterrupt()]
    with pytest.raises(KeyboardInterrupt):
        asyncio.run(fsp.run(run_args(mode="both")))
    assert_marked_incomplete(only_incomplete(world), "interrupted")


def test_a_write_failure_during_cancellation_does_not_replace_the_cancellation(
    world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    def broken(_path: Path, _payload: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(fsp, "write_json_atomic", broken)
    world.steps = [asyncio.CancelledError()]
    with pytest.raises(asyncio.CancelledError):  # not OSError
        asyncio.run(fsp.run(run_args(mode="both")))
    assert "could not be saved" in capsys.readouterr().err
    assert incomplete(world) == [] and finished(world) == []


def test_a_write_failure_after_a_provider_error_still_says_the_rows_were_not_saved(
    world: World, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        fsp, "write_json_atomic", lambda *_a: (_ for _ in ()).throw(OSError("disk full"))
    )
    world.steps = [RuntimeError("provider down")]
    with pytest.raises(SystemExit, match="could not be saved"):
        asyncio.run(fsp.run(run_args(mode="both")))


def test_cancellation_while_the_report_is_built_leaves_the_rows_and_never_complete(
    world: World, monkeypatch: pytest.MonkeyPatch
):
    world.steps = [search_step("a1"), search_step("a1"), search_step("a2"), search_step("a2")]

    async def cancelled(*_a: Any, **_k: Any) -> Any:
        raise asyncio.CancelledError

    monkeypatch.setattr(fsp, "passage_comparison", cancelled)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(fsp.run(run_args(mode="both", passage=True)))
    (path,) = finished(world)
    saved = json.loads(path.read_text())
    assert saved["status"] == "rows_only" and saved["complete"] is False
    assert len(saved["rows"]) == 4 and len(saved["baseline_rows"]) == 2


def test_a_truncated_response_stops_the_run_apart_from_a_decision_not_to_search(world: World):
    from evaluation.rag_eval.meter import IncompleteResponse

    # p001 repeat 1 is a genuine decision not to search (a valid miss); repeat 2 is cut off by the output limit
    world.steps = [
        NO_SEARCH,
        IncompleteResponse("the chat response was cut off (finish_reason 'length')"),
    ]
    with pytest.raises(SystemExit, match="incomplete"):
        asyncio.run(fsp.run(run_args(mode="both")))
    saved = only_incomplete(world)
    assert_marked_incomplete(saved, "truncated_response")
    assert "IncompleteResponse" in saved["incomplete_reason"]
    assert [r["tool"] for r in saved["rows"]] == [None]  # the real "no search" is kept as it was
    assert (
        len(saved["rows"]) == 1
    )  # the truncated step produced no row at all, never a fabricated miss


def test_the_run_meter_also_requires_complete_responses(
    world: World, monkeypatch: pytest.MonkeyPatch
):
    seen: list[dict[str, Any]] = []
    real = fsp.CostMeter

    def recording(cap: float, **kw: Any) -> Any:
        seen.append(kw)
        return real(cap, **kw)

    monkeypatch.setattr(fsp, "CostMeter", recording)
    asyncio.run(fsp.run(run_args(mode="baseline")))
    assert seen[0]["require_complete"] is True


def test_a_result_file_name_is_never_reused(tmp_path: Path):
    first = fsp.unique_path(tmp_path, "first_step_X")
    first.write_text("{}")
    second = fsp.unique_path(tmp_path, "first_step_X")
    second.write_text("{}")
    third = fsp.unique_path(tmp_path, "first_step_X")
    assert len({first, second, third}) == 3 and second.name == "first_step_X_2.json"
