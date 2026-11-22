"""M1 ticket 05: the freeze manifest and amendment log make a silent edit of a frozen case file fail.

Free. Tampering happens on a copy of the real files in a temporary folder; the repository is never touched.
"""

import json
import shutil
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from evaluation.rag_eval import freeze, pools
from evaluation.rag_eval.dataset import DATA

TODAY = date(2026, 11, 23)


@pytest.fixture
def area(tmp_path: Path) -> dict[str, Path]:
    """A throwaway copy of the case files, the manifest and the log."""
    root = tmp_path / "datasets"
    root.mkdir()
    for name in json.loads((DATA / "m1_freeze.json").read_text())["files"]:
        shutil.copy(DATA / name, root / name)
    manifest, log = tmp_path / "m1_freeze.json", tmp_path / "m1_amendments.json"
    shutil.copy(DATA / "m1_freeze.json", manifest)
    shutil.copy(DATA / "m1_amendments.json", log)
    return {"root": root, "manifest": manifest, "log": log}


def problems(area: dict[str, Path], **extra: Any) -> list[str]:
    return freeze.check(
        json.loads(area["manifest"].read_text()),
        json.loads(area["log"].read_text()),
        area["root"],
        **extra,
    )


def edit(path: Path, case_id: str, **changes: Any) -> None:
    data = json.loads(path.read_text())
    next(c for c in data["cases"] if c["id"] == case_id).update(changes)
    path.write_text(json.dumps(data, indent=1) + "\n")


def amend(area: dict[str, Path], name: str, reason: str = "fixed gold", **kw: Any) -> None:
    freeze.amend(
        name,
        reason=reason,
        today=TODAY,
        root=area["root"],
        manifest_path=area["manifest"],
        log_path=area["log"],
        **kw,
    )


# --- the committed freeze -------------------------------------------------------------------------


def test_the_committed_freeze_is_intact():
    manifest = json.loads((DATA / "m1_freeze.json").read_text())
    log = json.loads((DATA / "m1_amendments.json").read_text())
    assert freeze.check(manifest, log, held_out_file=pools.held_out_path()) == []


def test_the_freeze_records_the_corpus_version_the_pool_mapping_and_every_case_file():
    manifest = json.loads((DATA / "m1_freeze.json").read_text())
    assert manifest["corpus_version"] == "m1-corpus-v1-a605f90dc57b" == freeze.corpus_version()
    assert (
        manifest["pools"]
        == pools.POOLS
        == {"dev": "development", "test": "regression", "held_out": "held_out"}
    )
    # The four legacy files, unchanged, then the files later tickets registered (ticket 06: its development file).
    assert list(manifest["files"]) == [*pools.LEGACY_FILES, "rag_v3_dev_cases.json"]
    assert sum(manifest["files"][n]["cases"] for n in pools.LEGACY_FILES) == 201
    for name, node in manifest["files"].items():
        assert node["sha256"] == freeze.sha256_of(DATA / name)  # the current checksum is the file's
        if name in pools.LEGACY_FILES:  # the four older files were never amended after the freeze
            assert node["sha256"] == node["frozen_sha256"]


def test_the_first_amendment_entries_come_from_the_results_history():
    log = json.loads((DATA / "m1_amendments.json").read_text())
    by_case = {i: e for e in log for i in e["case_ids"]}
    assert (
        by_case["vi08"]["file"] == "rag_v2_messy_cases.json"
        and "vi06" in by_case["vi06"]["case_ids"]
    )
    assert by_case["id10"]["file"] == "rag_v2_identifier_cases.json"
    assert (
        by_case["id10"]["sha256_before"] is None
        and by_case["id10"]["sha256_before_prefix"] == "1d9f4f05"
    )
    assert by_case["id10"]["sha256_after"].startswith("7f5f4dfd")
    # The first five entries are reconstructed from git and the results history; later ones are written as the
    # freeze tool records changes (ticket 06 added its development file as an "addition").
    assert [e["phase"] for e in log[:5]] == ["history"] * 5
    assert {e["phase"] for e in log[5:]} <= {"post_freeze"}
    for entry in log:
        assert entry["reason"] and entry["date"] and entry["sha256_after"]


# --- a silent edit fails; an amendment makes it pass ----------------------------------------------


def test_an_untouched_copy_passes(area):
    assert problems(area) == []


def test_editing_a_frozen_case_without_an_entry_fails(area):
    edit(area["root"] / "rag_v2_cases.json", "sf01", reference_answer="changed after the result")
    assert any("rag_v2_cases.json: changed since it was frozen" in p for p in problems(area))


def test_editing_the_manifest_to_match_does_not_hide_the_edit(area):
    name = "rag_v2_cases.json"
    edit(area["root"] / name, "sf01", reference_answer="changed after the result")
    manifest = json.loads(area["manifest"].read_text())
    manifest["files"][name]["sha256"] = freeze.sha256_of(area["root"] / name)
    area["manifest"].write_text(json.dumps(manifest))
    assert any("no amendment entry behind it" in p for p in problems(area))


def test_an_amendment_entry_makes_the_change_pass_and_a_second_silent_edit_fail_again(area):
    name = "rag_v2_cases.json"
    edit(area["root"] / name, "sf01", reference_answer="corrected gold")
    amend(area, name, case_ids=["sf01"], reason="gold named the wrong day")
    assert problems(area) == []
    entry = json.loads(area["log"].read_text())[-1]
    assert (
        entry["case_ids"] == ["sf01"]
        and entry["phase"] == "post_freeze"
        and entry["date"] == "2026-11-23"
    )
    assert entry["sha256_before"] != entry["sha256_after"] == freeze.sha256_of(area["root"] / name)
    edit(area["root"] / name, "sf02", reference_answer="another silent change")
    assert problems(area)
    amend(area, name, case_ids=["sf02"], reason="second correction")
    assert problems(area) == []
    assert json.loads(area["manifest"].read_text())["files"][name][
        "frozen_sha256"
    ] != freeze.sha256_of(area["root"] / name)


def test_deleting_a_log_entry_after_the_fact_fails(area):
    name = "rag_v2_cases.json"
    edit(area["root"] / name, "sf01", reference_answer="corrected gold")
    amend(area, name, case_ids=["sf01"])
    log = json.loads(area["log"].read_text())[:-1]
    area["log"].write_text(json.dumps(log))
    assert any("no amendment entry behind it" in p for p in problems(area))


def test_an_amendment_needs_a_change_and_a_reason(area):
    with pytest.raises(ValueError, match="has not changed"):
        amend(area, "rag_v2_cases.json")
    edit(area["root"] / "rag_v2_cases.json", "sf01", reference_answer="x")
    with pytest.raises(ValueError, match="reason"):
        amend(area, "rag_v2_cases.json", reason="  ")
    with pytest.raises(ValueError, match="kind"):
        amend(area, "rag_v2_cases.json", kind="tweak")
    assert any("changed since it was frozen" in p for p in problems(area))  # nothing was recorded


def test_a_broken_history_chain_is_reported(area):
    log = json.loads(area["log"].read_text())
    messy = [e for e in log if e["file"] == "rag_v2_messy_cases.json"]
    messy[1]["sha256_before"] = "0" * 64
    area["log"].write_text(json.dumps(log))
    assert any("history chain broken" in p for p in problems(area))


def test_a_malformed_entry_is_reported(area):
    log = json.loads(area["log"].read_text())
    log[0].update(reason=" ", sha256_after="short", date="soon")
    area["log"].write_text(json.dumps(log))
    found = problems(area)
    assert any("reason is required" in p for p in found) and any("full SHA-256" in p for p in found)


def test_a_wrong_corpus_version_or_pool_mapping_fails(area):
    manifest = json.loads(area["manifest"].read_text())
    manifest["corpus_version"] = "m1-corpus-v1-000000000000"
    manifest["pools"]["test"] = "held_out"
    area["manifest"].write_text(json.dumps(manifest))
    found = problems(area)
    assert any("corpus version" in p for p in found) and any("pool mapping" in p for p in found)


def test_a_new_case_file_must_be_registered_and_is_then_frozen(area):
    new = area["root"] / "m1_dev_cases_a.json"
    new.write_text(json.dumps({"cases": [{"id": "n01", "split": "dev"}]}))
    assert any("m1_dev_cases_a.json: case file not in the freeze" in p for p in problems(area))
    freeze.add_file(
        new.name,
        reason="first new development cases",
        today=TODAY,
        root=area["root"],
        manifest_path=area["manifest"],
        log_path=area["log"],
    )
    assert problems(area) == []
    assert json.loads(area["log"].read_text())[-1]["kind"] == "addition"
    new.write_text(json.dumps({"cases": [{"id": "n01", "split": "dev", "question": "edited"}]}))
    assert any("m1_dev_cases_a.json: changed since it was frozen" in p for p in problems(area))
    amend(area, new.name, case_ids=["n01"], reason="question reworded before any run")
    assert problems(area) == []


def test_an_unregistered_rag_v3_case_file_fails_like_any_other(area):
    """Ticket 06 named its file rag_v3_dev_cases.json; the guard for unlisted case files must cover that family."""
    (area["root"] / "rag_v3_extra_cases.json").write_text(json.dumps({"cases": []}))
    assert any("rag_v3_extra_cases.json: case file not in the freeze" in p for p in problems(area))


def test_a_missing_frozen_file_fails(area):
    (area["root"] / "rag_v2_trap_cases.json").unlink()
    assert any("frozen file is missing" in p for p in problems(area))


# --- the sealed file: checksum when present, skipped when not ---------------------------------------


def fabricated_held_out(path: Path, count: int = 14) -> None:
    cases = [
        {
            "id": f"ho{i:03d}",
            "split": "held_out",
            "schema": 3,
            "category": "x",
            "language": "en",
            "expected_behavior": "answer",
            "expected_files": ["v1/fleet_register.xlsx"],
            "evidence_anchors": [],
            "must_include": [],
            "must_not_include": [],
            "computed": False,
        }
        for i in range(count)
    ]
    path.write_text(json.dumps({"cases": cases}))


def test_sealing_records_a_checksum_and_counts_but_no_case_id(area, tmp_path):
    sealed = tmp_path / "outside" / "sealed.json"
    sealed.parent.mkdir()
    fabricated_held_out(sealed)
    freeze.seal_held_out(
        sealed,
        reason="sealed before any baseline run",
        today=TODAY,
        manifest_path=area["manifest"],
        log_path=area["log"],
    )
    manifest = json.loads(area["manifest"].read_text())["held_out"]
    assert manifest["sha256"] == manifest["frozen_sha256"] == freeze.sha256_of(sealed)
    assert manifest["cases"] == 14 and manifest["gate_group_counts"]["total"] == 14
    assert manifest["gate_group_counts"]["format_xlsx"] == 14
    committed = area["manifest"].read_text() + area["log"].read_text()
    assert "ho000" not in committed and "ho013" not in committed
    assert json.loads(area["log"].read_text())[-1]["case_ids"] == []
    assert problems(area, held_out_file=sealed) == []


def test_a_changed_held_out_file_fails_the_checksum_but_an_absent_file_is_skipped(area, tmp_path):
    sealed = tmp_path / "sealed.json"
    fabricated_held_out(sealed)
    freeze.seal_held_out(
        sealed, reason="sealed", today=TODAY, manifest_path=area["manifest"], log_path=area["log"]
    )
    assert problems(area) == []  # no file on this machine: nothing to verify, no failure
    fabricated_held_out(sealed, count=15)
    assert any(
        "held-out file changed since it was sealed" in p
        for p in problems(area, held_out_file=sealed)
    )
    freeze.seal_held_out(
        sealed,
        reason="added one case",
        today=TODAY,
        manifest_path=area["manifest"],
        log_path=area["log"],
    )
    assert problems(area, held_out_file=sealed) == []
    assert json.loads(area["log"].read_text())[-1]["kind"] == "correction"


def test_a_held_out_file_that_was_never_sealed_is_reported(area, tmp_path):
    sealed = tmp_path / "sealed.json"
    fabricated_held_out(sealed)
    assert any("records no checksum" in p for p in problems(area, held_out_file=sealed))


def test_the_real_held_out_file_matches_its_checksum_when_it_is_present():
    path = pools.held_out_path()
    if path is None:
        pytest.skip(f"{pools.HELD_OUT_ENV} is not set: no sealed file on this machine")
    manifest = json.loads((DATA / "m1_freeze.json").read_text())
    log = json.loads((DATA / "m1_amendments.json").read_text())
    assert freeze.check(manifest, log, held_out_file=path) == []
