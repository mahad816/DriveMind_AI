"""The first-step probe judges tool wording, so its counting must be exactly right."""

from typing import Any

import pytest

from app.agents.tool_rag.agent_models import AgentStepResult, ToolCallRequest
from evaluation.rag_eval.first_step_probe import (
    FirstCall,
    case_kind,
    first_call,
    history_messages,
    probe_case,
    run_probe,
    summarise,
)
from evaluation.rag_eval.retrieval_probe import Hit


def call(name: str, call_id: str = "c1", **arguments: Any) -> ToolCallRequest:
    return ToolCallRequest(call_id=call_id, tool_name=name, arguments=arguments)


def step(*calls: ToolCallRequest, text: str | None = None) -> AgentStepResult:
    return AgentStepResult(text=text, tool_calls=tuple(calls))


def case(cid="c", category="single_fact", files=("synthetic/a.txt",), **extra: Any):
    return {
        "id": cid,
        "split": "dev",
        "category": category,
        "question": f"question {cid}",
        "expected_files": list(files),
        **extra,
    }


# ---- reading the model's first step --------------------------------------------------------


def test_a_text_only_step_is_no_tool():
    assert first_call(step(text="Hello")) == FirstCall(None, ())


def test_a_search_step_returns_every_query_in_order():
    s = step(
        call("search_knowledge", "a", query="meal limit", scope={}),
        call("search_knowledge", "b", query="hotel limit", scope={}),
    )
    assert first_call(s) == FirstCall("search_knowledge", ("meal limit", "hotel limit"))


def test_a_listing_step_has_no_search_query():
    assert first_call(step(call("files_query", operation="LATEST"))) == FirstCall("files_query", ())


def test_only_search_calls_contribute_queries_even_when_another_tool_is_first():
    s = step(
        call("resolve_file", "a", reference="budget"),
        call("search_knowledge", "b", query="total budget", scope={}),
    )
    assert first_call(s) == FirstCall("resolve_file", ("total budget",))


def test_inventory_is_the_only_kind_that_may_use_the_listing_tool():
    assert case_kind(case(category="inventory")) == "inventory"
    assert case_kind(case(category="aggregation_list_count")) == "content"


def test_case_history_is_converted_like_the_real_request_path():
    prior = history_messages(
        case(
            history=[
                {"role": "user", "text": "What is the meal limit?"},
                {"role": "assistant", "text": "40 USD."},
            ]
        )
    )
    assert [m.role for m in prior] == ["USER", "ASSISTANT"]
    assert history_messages(case()) == ()


# ---- running one case --------------------------------------------------------------------------


class FakeModel:
    """Replays prepared steps and remembers the messages it was sent."""

    def __init__(self, *steps: AgentStepResult):
        self.steps, self.seen = list(steps), []

    async def __call__(self, messages):
        self.seen.append(list(messages))
        return self.steps.pop(0)


class FakeSearch:
    """Returns prepared files per query and remembers which queries were run."""

    def __init__(self, files_by_query: dict[str, list[str]]):
        self.files_by_query, self.searched = files_by_query, []

    async def __call__(self, query: str) -> list[Hit]:
        self.searched.append(query)
        return [Hit(name, 0.5) for name in self.files_by_query[query]]


def fake_search(files_by_query: dict[str, list[str]]) -> FakeSearch:
    return FakeSearch(files_by_query)


@pytest.mark.asyncio
async def test_each_repeat_is_judged_separately_and_the_written_query_is_what_gets_searched():
    model = FakeModel(
        step(call("search_knowledge", query="meal limit", scope={})),
        step(call("files_query", operation="LATEST")),
    )
    search = fake_search({"meal limit": ["a.txt", "b.txt"]})
    rows = await probe_case(model, search, case(), repeats=2)
    assert [r["tool"] for r in rows] == ["search_knowledge", "files_query"]
    assert rows[0]["found"] and rows[0]["rank"] == 1 and rows[0]["queries"] == ["meal limit"]
    assert "found" not in rows[1] and rows[1]["queries"] == []  # nothing was searched
    assert search.searched == ["meal limit"]


@pytest.mark.asyncio
async def test_a_two_search_first_step_is_scored_on_both_searches_together():
    model = FakeModel(
        step(
            call("search_knowledge", "a", query="security", scope={}),
            call("search_knowledge", "b", query="hosting", scope={}),
        )
    )
    search = fake_search({"security": ["policy.txt"], "hosting": ["contract.txt"]})
    expected = ("synthetic/policy.txt", "synthetic/contract.txt")
    (row,) = await probe_case(model, search, case(files=expected), repeats=1)
    assert row["found_all"] and row["distinct_files"] == 2


@pytest.mark.asyncio
async def test_a_follow_up_sends_the_earlier_turns_and_the_history_note():
    model = FakeModel(step(text="ok"))
    follow_up = case(
        history=[
            {"role": "user", "text": "What is the meal limit?"},
            {"role": "assistant", "text": "40 USD."},
        ]
    )
    await probe_case(model, fake_search({}), follow_up, repeats=1)
    roles = [m.role for m in model.seen[0]]
    assert roles == ["SYSTEM", "SYSTEM", "USER", "ASSISTANT", "USER"]
    assert "window is complete" in (model.seen[0][1].text or "")


@pytest.mark.asyncio
async def test_chit_chat_is_not_sent_to_the_model_at_all():
    model = FakeModel()  # would raise IndexError if called
    assert await run_probe(model, fake_search({}), [case(category="chitchat")], 1) == []


# ---- the summary ---------------------------------------------------------------------------------


def row(rid, tool, queries=(), expected=("a.txt",), kind="content", **measured: Any) -> dict:
    base = {
        "id": rid,
        "kind": kind,
        "tool": tool,
        "queries": list(queries),
        "expected": list(expected),
    }
    return base | measured


def test_summary_counts_wrong_tool_no_tool_and_misses_separately():
    rows = [
        row("ok", "search_knowledge", ["meal limit"], found=True, rank=1, found_all=True),
        row("miss", "search_knowledge", ["x y z"], found=False, rank=None, found_all=False),
        row("wrong", "files_query"),
        row("silent", None),
        row("inv", "files_query", kind="inventory"),
    ]
    s = summarise(rows)
    assert s["content_runs"] == 4  # the inventory run is not a content run
    assert s["wrong_tool"] == 1 and s["wrong_tool_ids"] == ["wrong"]
    assert s["no_tool"] == 1
    assert s["search_runs_with_expected_file"] == 2 and s["search_found_expected_file"] == 1
    assert s["search_ranked_first"] == 1 and s["missed_ids"] == ["miss"]
    assert s["inventory_first_tool"] == {"files_query": 1}  # reported, never counted wrong


def test_summary_tracks_multi_file_questions_and_several_searches():
    rows = [
        row(
            "m",
            "search_knowledge",
            ["a b", "c d"],
            expected=("a", "b"),
            found=True,
            rank=1,
            found_all=True,
        ),
        row(
            "m",
            "search_knowledge",
            ["a b"],
            expected=("a", "b"),
            found=True,
            rank=1,
            found_all=False,
        ),
        row("s", "search_knowledge", ["a b c"], found=True, rank=2, found_all=True),
    ]
    s = summarise(rows)
    assert (s["multi_file_runs"], s["multi_file_all_found"]) == (2, 1)
    assert s["multi_file_missed_ids"] == ["m"]
    assert s["runs_with_several_searches"] == 1
    assert s["median_query_words"] == 2


def test_summary_of_nothing_does_not_crash():
    s = summarise([])
    assert s["content_runs"] == 0 and s["median_query_words"] is None
