"""A against C2 probe: query loading, the shared denominator, per-case movement and the free plan."""

import json

import pytest

from evaluation.rag_eval import dual_query_probe as dq


def write(tmp_path, name, rows, *, complete=True):
    path = tmp_path / name
    path.write_text(
        json.dumps(
            {"status": "complete" if complete else "rows_only", "complete": complete, "rows": rows}
        )
    )
    return path


def row(case, repeat, tool, queries):
    return {"id": case, "repeat": repeat, "tool": tool, "queries": queries}


def test_stored_query_is_the_first_query_of_the_lowest_repeat_that_searched(tmp_path):
    path = write(
        tmp_path,
        "a.json",
        [
            row("c1", 2, "search_knowledge", ["second run"]),
            row("c1", 1, None, []),
            row("c1", 3, "search_knowledge", ["third run"]),
            row("c2", 1, "search_knowledge", ["first q", "other q"]),
            row("c3", 1, "files_query", []),
            row("c3", 2, None, []),
        ],
    )
    queries, failures = dq.load_stored_queries([path])
    assert queries["c1"].query == "second run" and queries["c1"].repeat == 2
    assert queries["c2"].query == "first q"
    assert failures == ["c3"]  # never searched: a routing failure, not a retrieval miss


def test_an_incomplete_result_file_is_refused(tmp_path):
    path = write(tmp_path, "b.json", [], complete=False)
    with pytest.raises(SystemExit, match="not a complete"):
        dq.load_stored_queries([path])


@pytest.mark.parametrize("name", ["../x.json", "/etc/passwd", "sub/x.json", "x.txt"])
def test_result_files_must_be_bare_names_in_the_results_folder(name):
    with pytest.raises(SystemExit):
        dq.result_paths([name])


def case(i, *, language="en", history=None, expected=("f.txt",), category="factual"):
    return {
        "id": i,
        "language": language,
        "history": history,
        "category": category,
        "expected_files": list(expected),
        "split": "dev",
        "question": f"question {i}",
    }


def test_partition_scores_one_english_set_and_lists_every_exclusion(monkeypatch):
    monkeypatch.setattr(
        dq, "baseline_eligible", lambda c: not c.get("history") and bool(c["expected_files"])
    )
    cases = [
        case("a"),
        case("b"),
        case("routing"),
        case("nostore"),
        case("hist", history=[{"role": "user"}]),
        case("ru1", language="roman_urdu"),
    ]
    queries = {"a": dq.StoredQuery("qa", "f", 1), "b": dq.StoredQuery("qb", "f", 1)}
    parts = dq.partition_cases(cases, queries, ["routing", "ru1"])
    assert [c["id"] for c in parts["searched"]] == ["a", "b"]
    assert parts["routing_failures"] == ["routing"]
    assert parts["no_stored_run"] == ["nostore"]
    assert parts["excluded_unsupported_language"] == ["ru1"]


def r(case_id, found, rank, chunks):
    return {
        "id": case_id,
        "found": found,
        "rank": rank,
        "chunk_ids": chunks,
    }


def test_compare_lists_gains_losses_and_rank_changes():
    a = [
        r("g", False, None, ["1"]),
        r("l", True, 2, ["1", "2"]),
        r("u", True, 3, ["1"]),
        r("d", True, 1, ["1"]),
        r("s", True, 1, ["1"]),
    ]
    c = [
        r("g", True, 4, ["1", "2"]),
        r("l", False, None, ["3"]),
        r("u", True, 1, ["1"]),
        r("d", True, 2, ["1"]),
        r("s", True, 1, ["1"]),
    ]
    out = dq.compare_arms(a, c)
    assert out["gained_by_c2"] == ["g"] and out["lost_by_c2"] == ["l"]
    assert out["rank_improved_ids"] == ["u"] and out["rank_worsened_ids"] == ["d"]
    assert out["paired_hit_at_8"]["only_a"] == 1 and out["paired_hit_at_8"]["only_b"] == 1
    assert (
        out["top8_a_fully_retained_cases"] == 4
    )  # g, u, d, s keep every chunk of A; l loses its both


def test_compare_refuses_different_case_sets():
    with pytest.raises(ValueError, match="different cases"):
        dq.compare_arms([r("a", True, 1, [])], [r("b", True, 1, [])])


def test_top8_overlap_edges():
    assert dq.top8_overlap([], []) == 1.0
    assert dq.top8_overlap([], ["x"]) == 0.0
    assert dq.top8_overlap(["x", "y"], ["y", "z"]) == 0.5


def test_plan_counts_one_embedding_for_arm_a_and_two_for_c2_unless_the_texts_match():
    searched = [case("a"), case("b")]
    searched[1]["question"] = "same text"
    queries = {"a": dq.StoredQuery("query a", "f", 1), "b": dq.StoredQuery("same text", "f", 1)}
    plan = dq.plan_dual(
        searched, queries, embedding_model="text-embedding-3-small", cap=1.0, split="dev"
    )
    assert plan["embedding_calls"] == 5  # a: 1 + 2; b: 1 + 1 (equal texts search once in C2)
    assert plan["cases"] == 2 and plan["chat_calls"] == 0


def test_the_probe_refuses_held_out_before_reading_anything():
    import argparse

    args = argparse.Namespace(
        split="held_out", from_results=list(dq.DEFAULT_RESULT_FILES), plan=True, cap=1.0
    )
    with pytest.raises(SystemExit, match="held-out"):
        import asyncio

        asyncio.run(dq.run(args))


def test_the_split_choices_never_offer_the_held_out_pool():
    assert "held_out" not in dq.SPLITS


# ---- the flag must not leak into evaluation runs (review round 1, P2) ----------------------------------------


def test_the_flag_defaults_to_off_in_code():
    from app.core.config import Settings

    assert Settings.model_fields["retrieval_dual_query_enabled"].get_default() is False


def test_a_local_value_of_the_flag_does_not_leak_into_an_evaluation_run(monkeypatch):
    from app.core.config import Settings
    from evaluation.rag_eval import target

    monkeypatch.setattr(
        target, "get_settings", lambda: Settings.model_construct(retrieval_dual_query_enabled=True)
    )
    assert target.eval_settings().retrieval_dual_query_enabled is False
    assert "retrieval_dual_query_enabled" in target.ANSWER_FIELDS


# ---- denominator reconciliation with the earlier standalone experiment (repeat 1 only) -----------------------


def test_partition_lists_scored_cases_whose_query_comes_from_a_later_repeat(monkeypatch):
    monkeypatch.setattr(dq, "baseline_eligible", lambda c: True)
    cases = [case("a"), case("late")]
    queries = {"a": dq.StoredQuery("qa", "f", 1), "late": dq.StoredQuery("qlate", "f", 2)}
    parts = dq.partition_cases(cases, queries, [])
    assert [c["id"] for c in parts["searched"]] == ["a", "late"]  # both are scored
    assert parts["queries_from_later_repeat"] == [
        "late"
    ]  # and the one the earlier experiment dropped is named


def arm(case_id, pool, found, rank, chunks, repeat=1):
    return {
        "id": case_id,
        "pool": pool,
        "found": found,
        "rank": rank,
        "chunk_ids": chunks,
        "expected": ["f.txt"],
        "distinct_files": 1,
        "chunks": len(chunks),
        "latency_ms": 1.0,
        "embedding_calls": 1,
        "query_repeat": repeat,
    }


def test_pool_reports_group_by_pool_and_both_views_can_differ_by_the_late_case():
    a = [
        arm("d1", "development", True, 1, ["1"]),
        arm("d2", "development", False, None, ["2"], 2),
        arm("r1", "regression", True, 1, ["3"]),
    ]
    c = [
        arm("d1", "development", True, 1, ["1"]),
        arm("d2", "development", True, 3, ["2", "4"], 2),
        arm("r1", "regression", True, 1, ["3"]),
    ]
    full = dq.pool_reports(a, c)
    assert set(full) == {"development", "regression"}
    assert full["development"]["comparison"]["gained_by_c2"] == ["d2"]
    first = [r["query_repeat"] == 1 for r in a]
    repeat1 = dq.pool_reports(
        [r for r, k in zip(a, first, strict=True) if k],
        [r for r, k in zip(c, first, strict=True) if k],
    )
    assert repeat1["development"]["comparison"]["cases"] == 1  # the late case is out of this view
    assert repeat1["development"]["comparison"]["gained_by_c2"] == []


# ---- every case accounted for exactly once (review round 3, P2) ----------------------------------------------


def mixed_cases():
    return [
        case("scored"),
        case("late"),
        case("routing"),
        case("nostore"),
        case("chat", category="chitchat", expected=()),
        case("inv", category="inventory", expected=()),
        case("hist", history=[{"role": "user", "text": "x"}]),
        case("noexp", expected=()),
        case("ru1", language="roman_urdu"),
        case("ru_hist", language="roman_urdu", history=[{"role": "user", "text": "x"}]),
    ]


def mixed_parts():
    queries = {"scored": dq.StoredQuery("q", "f", 1), "late": dq.StoredQuery("q2", "f", 2)}
    return dq.partition_cases(mixed_cases(), queries, ["routing"])


def test_every_ineligible_english_case_is_listed_with_one_accurate_reason():
    parts = mixed_parts()
    assert parts["excluded_ineligible"] == {
        "chat": "chitchat",
        "inv": "inventory_question",
        "hist": "earlier_turns",
        "noexp": "no_expected_file",
    }


def test_unsupported_language_wins_over_any_other_reason_and_is_counted_once():
    parts = mixed_parts()
    assert parts["excluded_unsupported_language"] == ["ru1", "ru_hist"]
    assert "ru_hist" not in parts["excluded_ineligible"]


def test_each_case_is_in_exactly_one_partition():
    parts = mixed_parts()
    buckets = [
        [c["id"] for c in parts["searched"]],
        parts["routing_failures"],
        parts["no_stored_run"],
        parts["excluded_unsupported_language"],
        list(parts["excluded_ineligible"]),
    ]
    flat = [i for bucket in buckets for i in bucket]
    assert len(flat) == len(set(flat))
    assert sorted(flat) == sorted(c["id"] for c in mixed_cases())


def test_accounting_summary_adds_up_to_the_selected_cases():
    parts = mixed_parts()
    summary = dq.accounting_summary(parts, len(mixed_cases()))
    assert summary["selected_cases"] == 10
    assert (
        summary["scored"] == 2
        and summary["routing_failures"] == 1
        and summary["no_stored_run"] == 1
    )
    assert summary["excluded_unsupported_language"] == 2
    assert summary["excluded_ineligible"] == {
        "chitchat": 1,
        "inventory_question": 1,
        "earlier_turns": 1,
        "no_expected_file": 1,
    }
    assert (
        summary["scored"]
        + summary["routing_failures"]
        + summary["no_stored_run"]
        + summary["excluded_unsupported_language"]
        + sum(summary["excluded_ineligible"].values())
        == summary["selected_cases"]
    )


def test_a_duplicate_case_id_is_refused_not_silently_counted_twice():
    with pytest.raises(ValueError, match="duplicate"):
        dq.partition_cases([case("a"), case("a")], {}, [])


def test_the_accounting_check_refuses_a_case_that_falls_between_partitions():
    cases = [case("a"), case("b")]
    parts = dq.partition_cases(cases, {}, [])
    parts["no_stored_run"].remove("a")  # simulate a bug that loses a case
    with pytest.raises(ValueError, match="accounted"):
        dq.check_accounting(cases, parts)


def test_the_reason_function_agrees_with_the_established_eligibility_rule():
    from evaluation.rag_eval.first_step_probe import baseline_eligible

    for c in mixed_cases():
        assert (dq.ineligible_reason(c) is None) == baseline_eligible(c), c["id"]


def test_the_scored_set_and_its_denominator_are_unchanged_by_the_accounting():
    parts = mixed_parts()
    assert [c["id"] for c in parts["searched"]] == ["scored", "late"]
    assert parts["queries_from_later_repeat"] == ["late"]


# ---- the shared Qdrant client is closed when the probe ends, however it ends ----------------------------------


def test_the_probe_closes_the_shared_qdrant_client_after_a_run_and_after_a_failure(monkeypatch):
    import argparse
    import asyncio
    from unittest.mock import AsyncMock

    closed = AsyncMock()
    monkeypatch.setattr(dq, "close_shared_qdrant_clients", closed)
    args = argparse.Namespace()

    monkeypatch.setattr(dq, "run", AsyncMock())
    asyncio.run(dq.run_and_close(args))
    assert closed.await_count == 1

    monkeypatch.setattr(dq, "run", AsyncMock(side_effect=RuntimeError("stopped")))
    with pytest.raises(RuntimeError, match="stopped"):
        asyncio.run(dq.run_and_close(args))
    assert closed.await_count == 2
