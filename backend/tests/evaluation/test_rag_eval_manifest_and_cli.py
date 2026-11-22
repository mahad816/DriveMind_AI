"""M1 ticket 01: the run manifest, the production-equivalence pin and the safe command line.

Everything here is free: no key, no network, no container. Provider calls are replaced by fakes.
"""

import asyncio
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from openai.resources.chat.completions import AsyncCompletions

from app.core.config import Settings
from evaluation.rag_eval import cli, manifest, runner, target
from evaluation.rag_eval.corpus import synthetic_files
from evaluation.rag_eval.dataset import load_cases
from evaluation.rag_eval.meter import (
    ESTIMATES,
    PRICE_TABLE_DATE,
    BudgetExceeded,
    CostMeter,
    estimate_judge,
    estimate_run,
)

# --- the production-equivalence pin -------------------------------------------------------------

# The only settings the evaluation may set differently from the application's code defaults:
# where the store lives, demo and debug off, and the tool agent on (the production path under test).
ALLOWED_DIFFERENCES = {
    "database_url",
    "qdrant_url",
    "qdrant_api_key",
    "qdrant_host",
    "qdrant_port",
    "qdrant_collection",
    "demo_mode",
    "debug",
    "tool_rag_agent_enabled",
}


@pytest.fixture
def pristine_environment(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """``get_settings`` returns the bare code defaults, whatever the local environment says."""
    defaults = Settings.model_construct()
    monkeypatch.setattr(target, "get_settings", lambda: defaults)
    return defaults


def test_evaluation_settings_equal_the_application_defaults_outside_the_allow_list(
    pristine_environment: Settings,
) -> None:
    settings = target.eval_settings()
    differing = {
        name
        for name in Settings.model_fields
        if getattr(settings, name) != getattr(pristine_environment, name)
    }
    assert differing <= ALLOWED_DIFFERENCES, differing - ALLOWED_DIFFERENCES
    assert (
        settings.tool_rag_agent_enabled is True and not pristine_environment.tool_rag_agent_enabled
    )


def test_a_local_override_of_an_answer_setting_does_not_leak_into_the_evaluation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    drifted = Settings.model_construct(
        chat_model="some-other-model",
        retrieval_top_k=99,
        claim_check_enabled=False,
        agent_graph_enabled=True,
        hybrid_retrieval_enabled=False,
    )
    monkeypatch.setattr(target, "get_settings", lambda: drifted)
    settings = target.eval_settings()
    for name, default in target.application_defaults().items():
        if name != "tool_rag_agent_enabled":
            assert getattr(settings, name) == default, name


def test_every_answer_field_is_a_real_setting_and_the_explicit_model_still_wins(
    pristine_environment: Settings,
) -> None:
    assert set(target.ANSWER_FIELDS) <= set(Settings.model_fields)
    assert target.eval_settings(chat_model="gpt-6-luna").chat_model == "gpt-6-luna"
    assert target.eval_settings(tool_agent=False).tool_rag_agent_enabled is False


# --- the manifest -------------------------------------------------------------------------------

REQUIRED_MANIFEST_KEYS = [
    "schema_version",
    "commit",
    "tree_clean",
    "settings",
    "deviations_from_default",
    "embedding_dimension",
    "prompts",
    "indexing",
    "corpus",
    "dataset",
    "price_table_date",
    "concurrency",
    "repeat_index",
    "repeat_count",
    "libraries",
    "cap_usd",
    "spend",
]


def make_manifest(settings: Settings | None = None, **overrides: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "files": synthetic_files(),
        "datasets": ["rag_v2_cases.json"],
        "with_messy": False,
        "split": "dev",
        "concurrency": 3,
        "repeat_index": 1,
        "repeat_count": 1,
        "cap_usd": 1.0,
        **overrides,
    }
    return manifest.build_manifest(settings or target.eval_settings(), **args)


def test_the_manifest_states_everything_that_can_change_an_answer(
    pristine_environment: Settings,
) -> None:
    m = make_manifest()
    assert [key for key in REQUIRED_MANIFEST_KEYS if key not in m] == []
    assert m["schema_version"] == manifest.SCHEMA_VERSION
    assert set(m["settings"]) == set(target.ANSWER_FIELDS)
    # the settings the ticket names: tool agent, hybrid, claim check flag and model, chat and embedding
    # model, thresholds, per-file cap, name-term limit, context size
    for name in (
        "tool_rag_agent_enabled",
        "hybrid_retrieval_enabled",
        "claim_check_enabled",
        "claim_check_model",
        "chat_model",
        "embedding_model",
        "retrieval_score_threshold",
        "retrieval_relative_threshold",
        "retrieval_max_chunks_per_file",
        "retrieval_name_term_max_files",
        "rag_max_context_chars",
    ):
        assert name in m["settings"], name
    assert m["embedding_dimension"] == 1536
    assert set(m["prompts"]["tools"]) == {
        "files_query",
        "resolve_file",
        "search_knowledge",
        "file_evidence",
    }
    assert all(
        len(d) == 64 for d in (m["prompts"]["agent_system"], *m["prompts"]["tools"].values())
    )
    assert m["indexing"]["extraction_pipeline_version"] >= 1
    assert (
        m["corpus"]["version_id"] == "" and m["dataset"]["version_id"] == ""
    )  # until tickets 04-07
    assert m["corpus"]["files"] == len(synthetic_files()) and len(m["corpus"]["files_digest"]) == 64
    assert set(m["dataset"]["files"]) == {"rag_v2_cases.json"}
    assert m["price_table_date"] == PRICE_TABLE_DATE
    assert m["libraries"]["openai"] and m["libraries"]["python"] == sys.version.split()[0]
    assert m["deviations_from_default"] == {"tool_rag_agent_enabled": True}
    json.dumps(m)  # must be plain JSON


def test_a_changed_prompt_or_setting_shows_in_the_manifest(
    pristine_environment: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = make_manifest()
    monkeypatch.setattr(manifest, "AGENT_SYSTEM_PROMPT", "a different policy")
    changed = make_manifest(
        target.eval_settings().model_copy(update={"claim_check_enabled": False})
    )
    assert changed["prompts"]["agent_system"] != before["prompts"]["agent_system"]
    assert changed["prompts"]["tools"] == before["prompts"]["tools"]
    assert changed["deviations_from_default"]["claim_check_enabled"] is False


def test_the_git_state_is_a_commit_and_a_clean_flag_or_unknown() -> None:
    state = manifest.git_state()
    assert set(state) == {"commit", "tree_clean"}
    assert state["commit"] is None or len(state["commit"]) == 40


# --- the command line ---------------------------------------------------------------------------


def invoke(monkeypatch: pytest.MonkeyPatch, *argv: str) -> None:
    monkeypatch.setattr(sys, "argv", ["cli", *argv])
    cli.main()


@pytest.mark.parametrize("command", [["setup"], ["run"], ["rescore", "some.json"]])
def test_every_provider_reaching_command_requires_a_cap(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], command: list[str]
) -> None:
    with pytest.raises(SystemExit) as stop:
        invoke(monkeypatch, *command)
    assert stop.value.code == 2
    assert "--cap" in capsys.readouterr().err


@pytest.mark.parametrize(
    "bad",
    [
        ["--cap", "0"],
        ["--cap", "-1"],
        ["--cap", "nan"],
        ["--cap", "inf"],
        ["--cap", "1", "--repeats", "0"],
        ["--cap", "1", "--repeats", str(cli.MAX_REPEATS + 1)],
        ["--cap", "1", "--limit", "0"],
        ["--cap", "1", "--limit", "-3"],
        ["--cap", "1", "--concurrency", "0"],
    ],
)
def test_unsafe_numbers_are_refused_before_anything_starts(
    monkeypatch: pytest.MonkeyPatch, bad: list[str]
) -> None:
    with pytest.raises(SystemExit) as stop:
        invoke(monkeypatch, "run", *bad)
    assert stop.value.code == 2


def test_the_help_of_the_three_commands_says_the_cap_is_required(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        invoke(monkeypatch, "--help")
    out = capsys.readouterr().out
    assert "no default" in out and "required" in out and "--plan" in out


def test_the_probes_have_no_default_cap() -> None:
    for module in ("first_step_probe", "retrieval_probe", "ragbench_check", "planted_claims"):
        source = (Path(runner.__file__).parent / f"{module}.py").read_text()
        block = re.search(r'add_argument\(\s*"--cap".*?\)', source, re.S)
        assert block, module
        assert "required=True" in block.group(0) and "default=" not in block.group(0), module


@pytest.fixture
def offline_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    """Run ``cli run`` against the committed cases without the corpus files, a provider or a store."""
    calls: dict[str, Any] = {"pipelines": []}

    async def fake_pipeline(
        settings: Settings, cases: Any, files: Any, pipeline: str, *, concurrency: int, repeat: int
    ) -> dict[str, Any]:
        calls["pipelines"].append((pipeline, repeat))
        if calls.get("stop_at") == len(calls["pipelines"]):
            raise BudgetExceeded("estimated spend reached the cap")
        rows = [{"id": c["id"], "repeat": repeat} for c in cases]
        return {"pipeline": pipeline, "model": settings.chat_model, "summary": {}, "rows": rows}

    monkeypatch.setattr(cli, "corpus_files", lambda *, with_messy: synthetic_files())
    monkeypatch.setattr(cli, "verify", lambda files: None)
    monkeypatch.setattr(cli, "files_to_check", lambda dataset, files: [])
    monkeypatch.setattr(cli, "validate", lambda dataset, files: [])
    monkeypatch.setattr(cli, "run_pipeline", fake_pipeline)
    monkeypatch.setattr(cli, "RESULTS", tmp_path / "results")
    calls["results"] = tmp_path / "results"
    return calls


def test_plan_prints_the_estimate_and_writes_and_calls_nothing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    offline_run: dict[str, Any],
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("--plan must not build settings, a meter or a store connection")

    monkeypatch.setattr(cli, "eval_settings", forbidden)
    monkeypatch.setattr(cli, "CostMeter", forbidden)
    invoke(
        monkeypatch,
        *("run", "--plan", "--cap", "5", "--limit", "10", "--repeats", "2"),
        *("--pipelines", "tool_agent", "legacy", "--split", "all"),
    )
    out = capsys.readouterr().out
    plan = json.loads(out[: out.rindex("}") + 1])
    assert plan["within_cap"] is True and plan["cap_usd"] == 5
    detail = plan["plan"]
    assert detail["cases"] == 10 and detail["runs"] == 4
    assert (
        detail["calls"]["agent_step"] == 2 * 10 * 2
    )  # two calls per question, 10 cases, 2 repeats
    assert (
        detail["calls"]["embedding"] == (1 + 1) * 10 * 2
    )  # both pipelines embed once per question
    assert detail["calls"]["chat"] == 1 * 10 * 2  # legacy only
    expected = 10 * 2 * (0.0025 + 0.001) + detail["calls"]["judge"] * ESTIMATES["judge"]["usd"]
    assert detail["estimated_usd"] == pytest.approx(expected, abs=1e-4)
    assert offline_run["pipelines"] == [] and not offline_run["results"].exists()


def test_a_run_whose_estimate_exceeds_the_cap_refuses_to_start(
    monkeypatch: pytest.MonkeyPatch, offline_run: dict[str, Any]
) -> None:
    with pytest.raises(SystemExit, match="Refusing to start"):
        invoke(monkeypatch, "run", "--cap", "0.001", "--limit", "20", "--split", "all")
    assert offline_run["pipelines"] == [] and not offline_run["results"].exists()


def test_repeats_write_one_file_per_repeat_with_the_index_in_rows_and_manifest(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    offline_run: dict[str, Any],
) -> None:
    invoke(monkeypatch, "run", "--cap", "5", "--limit", "3", "--repeats", "3", "--tag", "t")
    files = sorted(offline_run["results"].glob("*.json"))
    assert len(files) == 3 and len({f.name for f in files}) == 3
    assert offline_run["pipelines"] == [("tool_agent", 1), ("tool_agent", 2), ("tool_agent", 3)]
    for index, path in enumerate(files, start=1):
        data = json.loads(path.read_text())
        assert f"_r{index}of3_t" in path.name
        assert data["manifest"]["repeat_index"] == index and data["manifest"]["repeat_count"] == 3
        assert data["manifest"]["cap_usd"] == 5 and data["manifest"]["spend"]["cap_usd"] == 5
        assert {r["repeat"] for r in data["rows"]} == {index}
        assert data["manifest"]["settings"]["tool_rag_agent_enabled"] is True
    capsys.readouterr()


def test_a_single_run_keeps_the_old_file_name_shape(
    monkeypatch: pytest.MonkeyPatch, offline_run: dict[str, Any]
) -> None:
    invoke(monkeypatch, "run", "--cap", "5", "--limit", "2", "--pipelines", "legacy")
    (path,) = offline_run["results"].glob("*.json")
    assert "_r1of" not in path.name and "_legacy_" in path.name
    data = json.loads(path.read_text())
    assert data["manifest"]["settings"]["tool_rag_agent_enabled"] is False
    assert data["manifest"]["repeat_count"] == 1


def test_hitting_the_cap_stops_the_run_and_nothing_further_is_started(
    monkeypatch: pytest.MonkeyPatch, offline_run: dict[str, Any]
) -> None:
    offline_run["stop_at"] = 2
    with pytest.raises(SystemExit, match="STOPPED"):
        invoke(monkeypatch, "run", "--cap", "5", "--limit", "3", "--repeats", "4")
    assert len(offline_run["pipelines"]) == 2  # the third and fourth were never started
    assert (
        len(list(offline_run["results"].glob("*.json"))) == 1
    )  # only the finished run was written


def test_the_estimate_is_the_sum_of_the_dated_constants() -> None:
    unit = ESTIMATES["per_question"]
    one = estimate_run(["tool_agent"], 100, 1, 0)
    assert one["estimated_usd"] == pytest.approx(100 * unit["tool_agent"]["usd"])
    assert one["calls"] == {
        "intent_gate": 100,
        "agent_step": 200,
        "claim_check": 100,
        "embedding": 100,
        "judge": 0,
    }
    assert estimate_run(["tool_agent"], 100, 5, 0)["estimated_usd"] == pytest.approx(
        5 * one["estimated_usd"]
    )
    assert estimate_judge(50)["estimated_usd"] == pytest.approx(50 * ESTIMATES["judge"]["usd"])


# --- rescore keeps working on a file written before this ticket ---------------------------------


def old_format_result(tmp_path: Path, behaviors: set[str]) -> tuple[Path, list[dict[str, Any]]]:
    cases = [c for c in load_cases()["cases"] if c["expected_behavior"] in behaviors][:3]
    rows = [
        {
            "id": c["id"],
            "category": c["category"],
            "split": c["split"],
            "language": c["language"],
            "expected_behavior": c["expected_behavior"],
            "question": c["question"],
            "reply": "",
            "cited_files": [],
            "error": None,
            "latency_s": 1.0,
        }
        for c in cases
    ]
    old = {  # exactly the keys the harness wrote before the manifest existed
        "pipeline": "tool_agent",
        "model": "gpt-5.4-nano",
        "started": "2026-11-19T10:00:00+00:00",
        "summary": {},
        "rows": rows,
        "split": "dev",
        "datasets": ["rag_v2_cases.json"],
        "retrieval": {"score_threshold": 0.25, "relative_threshold": 0.7},
        "spend_so_far": {"cap_usd": 3.0, "estimated_total_usd": 0.0, "by_label_and_model": []},
    }
    path = tmp_path / "rag_v2_old.json"
    path.write_text(json.dumps(old))
    return path, cases


def rescore_args(path: Path, **overrides: Any) -> Any:
    fields: dict[str, Any] = {
        "file": str(path),
        "with_messy": False,
        "dataset": ["rag_v2_cases.json"],
        "cap": 1.0,
        "plan": False,
        **overrides,
    }
    return SimpleNamespace(**fields)


async def test_rescore_works_on_a_result_file_without_a_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "corpus_files", lambda *, with_messy: synthetic_files())
    path, cases = old_format_result(tmp_path, {"answer"})  # not judged: no provider involved
    assert len(cases) == 3
    await cli.rescore(rescore_args(path))
    out = json.loads(path.with_name("rag_v2_old_rescored.json").read_text())
    assert "manifest" not in out and out["rescored_from"] == "rag_v2_old.json"
    assert [r["id"] for r in out["rows"]] == [c["id"] for c in cases]
    assert (
        all("overall" in r for r in out["rows"])
        and out["rescore_spend"]["estimated_total_usd"] == 0
    )


async def test_rescore_plan_counts_only_the_judged_rows_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "corpus_files", lambda *, with_messy: synthetic_files())
    monkeypatch.setattr(cli, "eval_settings", lambda **kw: pytest.fail("a plan builds no settings"))
    path, cases = old_format_result(tmp_path, {"not_found"})
    await cli.rescore(rescore_args(path, plan=True))
    out = capsys.readouterr().out
    plan = json.loads(out[: out.rindex("}") + 1])["plan"]
    assert plan["calls"] == {"judge": len(cases)}
    assert plan["estimated_usd"] == pytest.approx(len(cases) * ESTIMATES["judge"]["usd"])
    assert list(tmp_path.glob("*_rescored.json")) == []


async def test_rescore_refuses_when_the_judge_estimate_exceeds_the_cap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "corpus_files", lambda *, with_messy: synthetic_files())
    path, cases = old_format_result(tmp_path, {"not_found"})
    args = rescore_args(path, cap=0.001)  # three judged rows at the planning cost are above this
    with pytest.raises(SystemExit, match="Refusing to start"):
        await cli.rescore(args)
    assert not path.with_name("rag_v2_old_rescored.json").exists()


# --- the spend cap really stops paid work, also inside the tool agent ----------------------------


def test_the_cap_error_cannot_be_swallowed_by_a_broad_except() -> None:
    assert not issubclass(BudgetExceeded, Exception)


async def test_hitting_the_cap_stops_the_real_tool_agent_call_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``OpenAIAgentChatService.step`` turns every Exception into ChatError; the cap must get through."""
    from app.llm.openai_agent_service import OpenAIAgentChatService

    reached_provider = 0

    async def fake_create(self: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal reached_provider
        reached_provider += 1
        return SimpleNamespace(
            model="gpt-5.4-nano",
            choices=[SimpleNamespace(message=SimpleNamespace(content="done", tool_calls=None))],
            usage=SimpleNamespace(
                prompt_tokens=1_000_000, completion_tokens=0, prompt_tokens_details=None
            ),
        )

    monkeypatch.setattr(AsyncCompletions, "create", fake_create)
    service = OpenAIAgentChatService(
        Settings.model_construct(chat_model="gpt-5.4-nano", openai_api_key="not-a-real-key")
    )
    meter = CostMeter(
        0.10
    )  # one call costs 0.20 at the recorded price, so the first one passes the cap
    with meter.installed():
        first = await service.step(messages=[], tools=[])
        assert first.text == "done"
        with pytest.raises(BudgetExceeded):
            await service.step(messages=[], tools=[])
        with pytest.raises(BudgetExceeded):
            await service.step(messages=[], tools=[])
    assert reached_provider == 1  # no further paid request was sent after the cap was reached


async def test_a_cap_hit_cancels_the_other_cases_of_a_pipeline_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: list[str] = []
    cancelled: list[str] = []

    async def fake_case(settings: Any, case: dict[str, Any], *args: Any) -> dict[str, Any]:
        started.append(case["id"])
        if case["id"] == "a":
            raise BudgetExceeded("cap reached")
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.append(case["id"])
            raise
        return {"id": case["id"]}

    monkeypatch.setattr(runner, "run_case", fake_case)
    monkeypatch.setattr(runner, "session_factory", lambda settings: None)
    cases = [{"id": i, "question": "q", "must_include": []} for i in ("a", "b", "c")]
    with pytest.raises(BudgetExceeded):
        await runner.run_pipeline(target.eval_settings(), cases, [], "tool_agent", concurrency=3)
    assert sorted(cancelled) == ["b", "c"]


async def test_rows_carry_the_repeat_index(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_case(settings: Any, case: dict[str, Any], *args: Any) -> dict[str, Any]:
        return {
            "id": case["id"],
            "category": "x",
            "split": "dev",
            "language": "en",
            "expected_behavior": "answer",
            "question": case["question"],
            "reply": "",
            "cited_files": [],
            "error": None,
            "latency_s": 0.0,
            "overall": {"pass": False},
            "evidence": {"found": False},
            "answer": {"correct": False},
            "clean": {"clean": True},
            "refusal": None,
        }

    monkeypatch.setattr(runner, "run_case", fake_case)
    monkeypatch.setattr(runner, "session_factory", lambda settings: None)
    cases = [{"id": "a", "question": "q", "must_include": []}]
    result = await runner.run_pipeline(target.eval_settings(), cases, [], "legacy", repeat=2)
    assert [r["repeat"] for r in result["rows"]] == [2]


def test_an_unpriced_model_stops_the_run_instead_of_being_counted_as_free() -> None:
    from evaluation.rag_eval.meter import UnpricedModel, require_prices

    bad = SimpleNamespace(
        model="gpt-7-new",
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=1, prompt_tokens_details=None),
    )
    with pytest.raises(UnpricedModel):
        CostMeter(1.0).record(bad)
    assert not issubclass(UnpricedModel, Exception)  # application code cannot swallow it
    with pytest.raises(SystemExit, match="gpt-7-new"):
        require_prices("gpt-5.4-nano", "gpt-7-new")
    require_prices("gpt-5.4-nano", "gpt-5.4-mini-2026-03-17")


def test_run_refuses_an_unpriced_chat_model_before_any_spend(
    monkeypatch: pytest.MonkeyPatch, offline_run: dict[str, Any]
) -> None:
    with pytest.raises(SystemExit, match="No price recorded"):
        invoke(monkeypatch, "run", "--cap", "5", "--limit", "2", "--model", "gpt-7-new")
    assert offline_run["pipelines"] == []
