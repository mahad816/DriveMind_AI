"""M1 ticket 05: the held-out pool reaches summaries, logs and committed output only as aggregates.

Free. The held-out file here is fabricated and lives in a temporary folder outside the repository.
"""

import argparse
import asyncio
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from evaluation.rag_eval import cli, pools, review_gate, runner
from evaluation.rag_eval.dataset import DATA
from evaluation.rag_eval.schema_v3 import gate_groups
from evaluation.rag_eval.score import summarise
from evaluation.rag_eval.sealing import (
    MIN_CELL,
    committed_view,
    leaks,
    reduce_row,
    sealed_summary,
    small_cells,
)

SECRET_REPLY = "SECRET-REPLY the vault code is 4711"
SECRET_QUESTION = "SECRET-QUESTION what is the vault code"
IDS = [f"ho{i:03d}" for i in range(30)]


def fabricated_cases() -> list[dict[str, Any]]:
    """30 held-out cases: 30 total, 24 tabular answers, 4 ambiguous (a small group), 2 critical (smaller)."""
    cases = []
    for i, case_id in enumerate(IDS):
        ambiguous = i >= 26
        cases.append(
            {
                "id": case_id,
                "split": "held_out",
                "schema": 3,
                "category": "table_lookup",
                "language": "en",
                "question": f"{SECRET_QUESTION} {case_id}",
                "expected_behavior": "clarify" if ambiguous else "answer",
                "expected_files": [] if ambiguous else ["v1/fleet_register.xlsx"],
                "evidence_anchors": [],
                "must_include": [],
                "must_not_include": [],
                "computed": False,
                "critical": i in {0, 1},
                "pool": "held_out",
            }
        )
    return cases


def fabricated_rows(cases: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    rows = []
    for i, case in enumerate(cases or fabricated_cases()):
        row = runner.base_row(
            case, reply=SECRET_REPLY, cited_files=["v1/fleet_register.xlsx"], latency_s=1.5
        )
        row.update(
            cited=[
                {
                    "chunk_id": "c",
                    "file": "v1/fleet_register.xlsx",
                    "score": 0.9,
                    "snippet": "SECRET-SNIPPET",
                }
            ],
            overall={"pass": i % 3 != 0},
            strict={"deterministic": i % 4 != 0, "graded": None},
            refusal={"ok": True, "reason": "SECRET-REASON"},
            answer={
                "correct": True,
                "missing": ["SECRET-FACT"],
                "forbidden_present": ["SECRET-FORBIDDEN"],
            },
            execution={
                "path": "tool_agent",
                "agent_queries": ["SECRET-QUERY"],
                "search_count": 2,
                "tool_names": ["search"],
            },
            trace={"searches": [{"query": "SECRET-QUERY"}]},
            accounting={"cost_usd": 0.002, "calls": 3},
            cause={"primary": "retrieval", "secondary": []},
            outcome="correct",
            outcome_group="answerable",
            status="scored",
        )
        rows.append(row)
    return rows


SECRETS = ("SECRET", "4711", *IDS)


def assert_sealed(text: str) -> None:
    assert not leaks(text, IDS), "a held-out case id reached the output"
    assert not any(s in text for s in ("SECRET", "4711", "vault code")), (
        "held-out text reached the output"
    )


# --- the summariser -------------------------------------------------------------------------------------


def test_the_summariser_shows_held_out_rows_only_as_a_total_and_gate_groups():
    summary = summarise(fabricated_rows())
    assert summary["pool"] == "held_out" and summary["cases"] == 30
    assert summary["total"]["n"] == 30
    groups = summary["groups"]
    assert groups["format_xlsx"]["n"] == 26
    assert groups["ambiguous"] == {"suppressed": f"fewer than {MIN_CELL} cases"}
    assert groups["critical"] == {"suppressed": f"fewer than {MIN_CELL} cases"}
    assert not small_cells(summary)
    assert (
        "by_category" not in summary and "rollups" not in summary
    )  # category cells are never shown
    assert_sealed(json.dumps(summary))


def test_a_cell_of_ten_is_shown_and_a_cell_of_nine_is_not():
    cases = fabricated_cases()
    for case in cases:
        case.update(
            expected_behavior="answer", expected_files=["v1/fleet_register.xlsx"], critical=False
        )
    for case in cases[:10]:
        case["critical"] = True
    for case in cases[10:19]:
        case["expected_files"] = ["v1/driver_handbook.docx"]
    rows = fabricated_rows(cases)
    groups = sealed_summary(rows)["groups"]
    assert groups["critical"]["n"] == 10
    assert groups["format_docx"] == {"suppressed": "fewer than 10 cases"}  # 9 cases
    assert groups["format_xlsx"]["n"] == 21


def test_a_rate_resting_on_fewer_than_ten_decided_rows_is_suppressed_too():
    rows = fabricated_rows()
    for row in rows[:25]:
        row["strict"] = {
            "deterministic": None,
            "graded": None,
        }  # undecided: the strict rate has n = 5
    summary = sealed_summary(rows)
    assert summary["total"]["n"] == 30 and summary["total"]["strict"] == {
        "suppressed": "fewer than 10 cases"
    }
    assert not small_cells(summary)


def test_fewer_than_ten_held_out_rows_give_no_total_at_all():
    summary = summarise(fabricated_rows()[:7])
    assert (
        summary["total"] == {"suppressed": "fewer than 10 cases"}
        and summary["groups"]["format_xlsx"] == summary["total"]
    )


def test_mixed_pools_summarise_normally_and_add_the_sealed_view():
    dev = {
        "id": "d1",
        "split": "dev",
        "question": "a question",
        "language": "en",
        "expected_behavior": "answer",
        "category": "single_fact",
        "expected_files": [],
        "evidence_anchors": [],
        "must_include": [],
        "must_not_include": [],
        "computed": False,
    }
    dev_row = runner.score_row(dev, runner.base_row(dev, reply="r"))
    dev_row["overall"] = {"pass": True}
    summary = summarise([dev_row, *fabricated_rows()])
    assert summary["cases"] == 1 and "single_fact" in summary["by_category"]
    assert summary["held_out"]["cases"] == 30
    assert_sealed(json.dumps(summary))


def test_rows_know_their_pool_and_gate_groups():
    row = runner.base_row({**fabricated_cases()[0]})
    assert (
        row["pool"] == "held_out"
        and "critical" in row["gates"]
        and row["gates"] == sorted(row["gates"])
    )


# --- reduced rows and the committed baseline ---------------------------------------------------------


def test_a_reduced_row_has_no_reply_question_query_or_snippet_and_keeps_the_numbers():
    row = fabricated_rows()[0]
    reduced = reduce_row(row)
    dumped = json.dumps(reduced)
    assert not any(s in dumped for s in ("SECRET", "4711", "vault code"))
    assert (
        reduced["id"] == "ho000" and reduced["pool"] == "held_out" and reduced["latency_s"] == 1.5
    )
    assert reduced["cited_files"] == ["v1/fleet_register.xlsx"] and reduced["accounting"] == {
        "cost_usd": 0.002,
        "calls": 3,
    }
    assert reduced["strict"]["deterministic"] is False and reduced["overall"]["pass"] is False
    assert reduced["cause"]["primary"] == "retrieval" and reduced["execution"]["search_count"] == 2
    assert "reply" not in reduced and "question" not in reduced and "trace" not in reduced


def test_the_committed_view_carries_no_held_out_row_and_no_small_cell():
    dev = [
        {**r, "pool": "development", "split": "dev", "id": f"dv{i}"}
        for i, r in enumerate(fabricated_rows()[:12])
    ]
    view = committed_view([*dev, *fabricated_rows()])
    text = json.dumps(view)
    assert len(view["rows"]) == 12 and all(r["pool"] == "development" for r in view["rows"])
    assert_sealed(text)
    assert not small_cells(view["held_out"])
    assert committed_view(dev)["held_out"] is None


# --- the checks themselves must be able to fail -------------------------------------------------------


def test_the_leak_and_small_cell_checks_catch_what_they_are_for():
    assert leaks('{"id": "ho007"}', IDS) == ["ho007"]
    assert leaks("ho0071 and xho007", IDS) == []  # whole tokens only
    assert small_cells({"groups": {"critical": {"n": 4, "legacy": {"n": 4}}}}) == [
        "/groups/critical",
        "/groups/critical/legacy",
    ]
    assert small_cells({"groups": {"critical": {"suppressed": "fewer than 10 cases"}}}) == []
    unsafe = {"rows": fabricated_rows()[:2]}  # what a careless writer would commit
    assert leaks(json.dumps(unsafe), IDS) and "SECRET-REPLY" in json.dumps(unsafe)


def test_no_committed_file_names_a_held_out_case_when_the_real_file_is_present():
    path = pools.held_out_path()
    if path is None:
        pytest.skip(f"{pools.HELD_OUT_ENV} is not set: no sealed file on this machine")
    ids = [c["id"] for c in pools.load_held_out(path, require_review=False)["cases"]]
    root = pools.REPO_ROOT
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.split()
    # the amendment log names case ids by design (a moved case is a development case); everything else must not
    skip = {"backend/evaluation/datasets/m1_amendments.json"}
    for name in tracked:
        file = root / name
        if name in skip or not file.is_file() or file.suffix not in {".md", ".json", ".txt", ".py"}:
            continue
        assert not leaks(file.read_text(errors="ignore"), ids), name


# --- the real command path: stdout, log and written files ---------------------------------------------


def run_args(**changes: Any) -> argparse.Namespace:
    base = dict(
        cap=5.0,
        plan=False,
        repeats=1,
        pipelines=["tool_agent"],
        split="held_out",
        category=None,
        limit=None,
        ids=None,
        dataset=["rag_v2_cases.json"],
        threshold=None,
        relative=None,
        tag=None,
        no_claim_check=False,
        model=None,
        concurrency=1,
        with_messy=False,
    )
    return argparse.Namespace(**{**base, **changes})


@pytest.fixture
def sealed_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    outside = tmp_path / "outside"
    outside.mkdir()
    path = outside / "sealed.json"
    path.write_text(json.dumps({"cases": fabricated_cases()}))
    monkeypatch.setenv(pools.HELD_OUT_ENV, str(path))
    # A genuine, matching Owner attestation (fabricated): the paid run path is gated since M1-07-F.
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = tmp_path / "freeze.json"
    manifest.write_text(json.dumps({"held_out": {"sha256": digest}}))
    monkeypatch.setattr(pools, "FREEZE_MANIFEST", manifest)
    review_gate.attestation_path(path).write_text(
        json.dumps(
            {
                "version": review_gate.VERSION,
                "sealed_sha256": digest,
                "freeze_held_out_sha256": digest,
                "sheet_sha256": digest,
                "reviewed": 36,
                "correct": 36,
                "gold_wrong": 0,
                "attested_at": "2026-01-01T00:00:00+00:00",
            }
        )
    )
    return path


def stub_pipeline(monkeypatch: pytest.MonkeyPatch, seen: list[list[str]]) -> None:
    async def fake(
        settings: Any, cases: Any, files: Any, pipeline: str, **kw: Any
    ) -> dict[str, Any]:
        seen.append([c["id"] for c in cases])
        rows = fabricated_rows([runner.prepare_case(c, 0) for c in cases])
        return {
            "pipeline": pipeline,
            "model": "stub",
            "started": "now",
            "summary": summarise(list(rows)),
            "rows": rows,
        }

    monkeypatch.setattr(cli, "run_pipeline", fake)
    monkeypatch.setattr(cli, "corpus_files", lambda **_: [])
    monkeypatch.setattr(cli, "validate", lambda *a, **k: [])


def test_a_held_out_run_prints_and_writes_only_aggregates(sealed_file, monkeypatch, capsys):
    seen: list[list[str]] = []
    stub_pipeline(monkeypatch, seen)
    asyncio.run(cli.run(run_args()))
    out = capsys.readouterr().out
    assert seen == [IDS] and "held_out" in out and "total" in out
    assert_sealed(out)
    written = list((sealed_file.parent / cli.HELD_OUT_RESULTS).glob("*.json"))
    assert len(written) == 1 and pools.REPO_ROOT not in written[0].parents
    assert written[0].stat().st_mode & 0o777 == 0o600  # owner only, like the probe's sealed report
    assert (
        written[0].parent.stat().st_mode & 0o777 == 0o700
    )  # the folder too, made before the write
    saved = json.loads(written[0].read_text())
    assert not any(s in written[0].read_text() for s in ("SECRET", "4711", "vault code"))
    assert [r["id"] for r in saved["rows"]] == IDS and "reply" not in saved["rows"][0]
    assert saved["summary"]["pool"] == "held_out" and not small_cells(saved["summary"])
    assert saved["manifest"]["dataset"]["held_out_sha256"] and saved["datasets"] == []


def test_all_never_runs_the_held_out_pool(sealed_file, monkeypatch, capsys):
    seen: list[list[str]] = []
    stub_pipeline(monkeypatch, seen)
    monkeypatch.setattr(
        cli,
        "load_many",
        lambda names: {
            "cases": [*fabricated_cases(), {**fabricated_cases()[0], "id": "dv1", "split": "dev"}]
        },
    )
    asyncio.run(cli.run(run_args(split="all")))
    assert seen == [["dv1"]]
    assert not (sealed_file.parent / cli.HELD_OUT_RESULTS).exists()


@pytest.mark.parametrize(
    "flag", [{"ids": ["ho001"]}, {"category": ["table_lookup"]}, {"limit": 3}, {"repeats": 2}]
)
def test_the_held_out_pool_refuses_to_be_probed_or_repeated(sealed_file, flag):
    with pytest.raises(SystemExit, match="whole and once per checkpoint"):
        asyncio.run(cli.run(run_args(**flag)))


def test_a_held_out_run_without_the_sealed_file_stops(monkeypatch):
    monkeypatch.delenv(pools.HELD_OUT_ENV, raising=False)
    with pytest.raises(SystemExit, match=pools.HELD_OUT_ENV):
        asyncio.run(cli.run(run_args()))


def test_an_invalid_held_out_file_reports_a_count_and_no_case_text(sealed_file, monkeypatch):
    monkeypatch.setattr(cli, "corpus_files", lambda **_: [])
    monkeypatch.setattr(
        cli,
        "validate",
        lambda *a, **k: [f"{IDS[3]}: evidence quote not found verbatim: {SECRET_QUESTION!r}"],
    )
    with pytest.raises(SystemExit) as stopped:
        asyncio.run(cli.run(run_args()))
    assert "1 problem(s)" in str(stopped.value)
    assert_sealed(str(stopped.value))


def test_the_split_flag_offers_the_pools_by_name():
    assert set(pools.SPLIT_CHOICES) == {"dev", "test", "regression", "held_out", "all"}
    assert (DATA / "m1_freeze.json").exists() and gate_groups(fabricated_cases()[0])
