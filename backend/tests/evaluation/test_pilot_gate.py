"""The free gate around the pilot's two paid arms: it must stop on anything missing, stale, incomplete or unfair.

Everything here uses temporary files and a patched ``git_state``; no provider, no store, no real run.
"""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from evaluation.rag_eval import pilot_gate as gate

IDS = ["a1", "a2"]
RUN = "pilot_20261125_101500_4242"
HEAD = "c" * 40
CLEAN = {"commit": HEAD, "tree_clean": True}


def arm(
    label: str, dual: bool, *, run: str = RUN, started: str = "2026-11-25T10:15:00"
) -> dict[str, Any]:
    return {
        "pipeline": "tool_agent",
        "model": "gpt-5.4-nano",
        "tag": gate.tag_for(run, label),
        "started": started,
        "summary": {"incomplete": False, "cap_stopped": 0},
        "rows": [{"id": i, "error": None, "accounting": {"total": {}}} for i in IDS],
        "manifest": {
            "retrieval_strategy": {"label": label, "selected_explicitly": True},
            "settings": {"retrieval_dual_query_enabled": dual, "chat_model": "gpt-5.4-nano"},
            "case_ids": IDS,
            "commit": HEAD,
            "tree_clean": True,
            "prompts": {"x": 1},
            "indexing": {},
            "corpus": {"files_digest": "d"},
            "dataset": {"split": "dev"},
            "price_table_date": "2026-11-19",
            "concurrency": 1,
            "libraries": {},
        },
    }


def problems(data: dict[str, Any], strategy: str = "A", **kw: Any) -> list[str]:
    return gate.arm_problems(
        data, strategy, IDS, run_id=kw.get("run_id", RUN), head=kw.get("head", HEAD)
    )


def test_a_complete_arm_of_this_run_passes_and_a_fair_pair_passes() -> None:
    a = arm("A", False)
    c2 = arm("C2-cap3", True, started="2026-11-25T10:16:00")
    assert problems(a) == [] and problems(c2, "C2-cap3") == []
    assert gate.pair_problems(a, c2) == []


@pytest.mark.parametrize(
    ("change", "fragment"),
    [
        (lambda d: d["summary"].update(incomplete=True), "spend cap"),
        (lambda d: d["rows"][1].update(error="TimeoutError"), "error"),
        (lambda d: d["rows"][0].update(cap_stopped=True), "cap-stopped"),
        (lambda d: d["rows"].pop(), "exactly the pilot cases"),
        (lambda d: d["rows"].append(dict(d["rows"][0])), "exactly the pilot cases"),
        (lambda d: d["manifest"].update(case_ids=["a1"]), "exactly the pilot cases"),
        (lambda d: d["manifest"].update(case_ids=["a1", "zz"]), "exactly the pilot cases"),
        (
            lambda d: d["manifest"]["retrieval_strategy"].update(selected_explicitly=False),
            "manifest strategy",
        ),
        (
            lambda d: d["manifest"]["retrieval_strategy"].update(label="C2-cap3"),
            "manifest strategy",
        ),
        (
            lambda d: d["manifest"]["settings"].update(retrieval_dual_query_enabled=True),
            "does not match",
        ),
        (lambda d: d.update(pipeline="legacy"), "not tool_agent"),
        (lambda d: d["rows"][0].update(accounting=None), "accounting"),
        (lambda d: d.update(tag="pilot_20250101_000000_1_A"), "own tag"),  # another run's result
        (lambda d: d.update(tag=None), "own tag"),
        (lambda d: d["manifest"].update(commit="d" * 40), "different commit"),
        (lambda d: d["manifest"].update(tree_clean=False), "not clean"),
        (lambda d: d["manifest"].update(tree_clean=None), "not clean"),
    ],
)
def test_an_incomplete_stale_or_mismatched_arm_is_stopped(change: Any, fragment: str) -> None:
    data = copy.deepcopy(arm("A", False))
    change(data)
    found = problems(data)
    assert found and any(fragment in p for p in found)


def test_an_unknown_head_stops_the_arm() -> None:
    assert any("different commit" in p for p in problems(arm("A", False), head=None))


def test_the_run_order_may_differ_from_the_order_of_the_ids_given() -> None:
    data = arm("A", False)
    data["rows"].reverse()
    data["manifest"]["case_ids"] = list(reversed(IDS))
    assert problems(data) == []


@pytest.mark.parametrize(
    ("change", "fragment"),
    [
        (lambda d: d["manifest"]["settings"].update(chat_model="other"), "settings differ"),
        (lambda d: d["manifest"].update(commit="d" * 40), "commit differs"),
        (lambda d: d["manifest"].update(case_ids=["a1"]), "case_ids differs"),
        (lambda d: d["manifest"]["prompts"].update(x=2), "prompts differs"),
        (lambda d: d.update(model="gpt-5.4-mini"), "chat model differs"),
        (lambda d: d.update(started="2026-11-25T10:00:00"), "did not start after"),
    ],
)
def test_an_unfair_pair_is_stopped(change: Any, fragment: str) -> None:
    c2 = copy.deepcopy(arm("C2-cap3", True, started="2026-11-25T10:16:00"))
    change(c2)
    assert any(fragment in p for p in gate.pair_problems(arm("A", False), c2))


# --- finding the one result of this run ----------------------------------------------------------


def write(folder: Path, name: str, data: dict[str, Any]) -> Path:
    path = folder / name
    path.write_text(json.dumps(data))
    return path


def test_the_result_is_found_by_its_own_run_id_and_never_by_age(tmp_path: Path) -> None:
    older = "pilot_20250101_000000_1"
    write(tmp_path, f"rag_v2_x_tool_agent_m_dev_{older}_A.json", arm("A", False, run=older))
    found, why = gate.find_result(tmp_path, RUN, "A")
    assert (
        found is None and "no result file for run" in why[0]
    )  # the old complete result is not this run's
    mine = write(tmp_path, f"rag_v2_y_tool_agent_m_dev_{RUN}_A.json", arm("A", False))
    assert gate.find_result(tmp_path, RUN, "A") == (mine, [])
    assert gate.find_result(tmp_path, RUN, "C2-cap3")[0] is None  # the other arm has not run


def test_two_files_for_one_arm_are_refused(tmp_path: Path) -> None:
    for stamp in ("1", "2"):
        write(tmp_path, f"rag_v2_{stamp}_tool_agent_m_dev_{RUN}_A.json", arm("A", False))
    found, why = gate.find_result(tmp_path, RUN, "A")
    assert found is None and "expected exactly one" in why[0]


@pytest.mark.parametrize(
    "bad", ["", "short", "has space in it", "../escape_attempt_1", "a*b_20261125_1"]
)
def test_a_malformed_run_id_is_refused(tmp_path: Path, bad: str) -> None:
    found, why = gate.find_result(tmp_path, bad, "A")
    assert found is None and "run id" in why[0]


# --- git preflight and the command ---------------------------------------------------------------


def test_preflight_needs_a_known_commit_and_a_clean_tree() -> None:
    assert gate.preflight_problems(CLEAN) == []
    assert any(
        "not clean" in p for p in gate.preflight_problems({"commit": HEAD, "tree_clean": False})
    )
    assert gate.preflight_problems({"commit": None, "tree_clean": None})


def run_main(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *argv: str, git: dict[str, Any] = CLEAN
) -> int:
    monkeypatch.setattr(gate, "git_state", lambda: git)
    return gate.main([*argv, "--results-dir", str(tmp_path)])


def test_the_command_exit_codes_follow_the_checks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_main(monkeypatch, tmp_path, "--preflight", "--run-id", RUN) == 0
    assert (
        run_main(
            monkeypatch,
            tmp_path,
            "--preflight",
            "--run-id",
            RUN,
            git={"commit": HEAD, "tree_clean": False},
        )
        == 1
    )
    ask = ("--run-id", RUN, "--strategy", "A", "--ids", *IDS)
    assert run_main(monkeypatch, tmp_path, *ask) == 1  # nothing written yet: missing
    write(tmp_path, f"rag_v2_1_tool_agent_m_dev_{RUN}_A.json", arm("A", False))
    assert run_main(monkeypatch, tmp_path, *ask) == 0
    assert run_main(monkeypatch, tmp_path, *ask, git={"commit": "d" * 40, "tree_clean": True}) == 1
    assert run_main(monkeypatch, tmp_path, *ask, git={"commit": HEAD, "tree_clean": False}) == 1
    pair = ("--run-id", RUN, "--pair", "--ids", *IDS)
    assert run_main(monkeypatch, tmp_path, *pair) == 1  # arm C2-cap3 missing
    write(
        tmp_path,
        f"rag_v2_2_tool_agent_m_dev_{RUN}_C2-cap3.json",
        arm("C2-cap3", True, started="2026-11-25T10:16:00"),
    )
    assert run_main(monkeypatch, tmp_path, *pair) == 0
    assert "PILOT GATE: ok" in capsys.readouterr().out


def test_preflight_refuses_a_run_id_that_already_has_results(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    write(tmp_path, f"rag_v2_1_tool_agent_m_dev_{RUN}_A.json", arm("A", False))
    assert run_main(monkeypatch, tmp_path, "--preflight", "--run-id", RUN) == 1
    assert (
        run_main(monkeypatch, tmp_path, "--preflight", "--run-id", "pilot_20261125_999999_1") == 0
    )
