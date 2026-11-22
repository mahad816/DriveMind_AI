"""M1-07-F: paid held-out evaluation needs an Owner review attestation bound to the sealed file's checksum.

Free: no key, no network, no container. Every sealed file, sheet and attestation here is FABRICATED in tmp_path;
the real sealed pool, the real review sheet and the real freeze manifest are never read or written. The marker
text below is invented and appears in no committed dataset.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from evaluation.rag_eval import cli, coverage, pools, review_gate

MARKER = "zq-fabricated-gate-marker"
CONFIRM = review_gate.CONFIRM_PHRASE


def fabricated_case(i: int) -> dict[str, Any]:
    return {
        "id": f"gate{i:03d}",
        "split": "held_out",
        "schema": 3,
        "category": "x",
        "language": "en",
        "expected_behavior": "answer",
        "question": f"{MARKER} question {i}?",
        "reference_answer": f"{MARKER} answer {i}",
        "expected_files": ["v1/fleet_register.xlsx"],
        "evidence_anchors": [{"file": "v1/fleet_register.xlsx", "quote": f"{MARKER} quote {i}"}],
        "must_include": [],
        "must_not_include": [],
        "computed": False,
    }


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Area:
    def __init__(self, root: Path, count: int = 40):
        self.dir = root / "owner-only"
        self.dir.mkdir()
        self.sealed = self.dir / "sealed.json"
        self.manifest = root / "freeze.json"
        self.sheet = self.dir / "sheet.md"
        self.write_sealed(count)
        self.seal()

    def write_sealed(self, count: int = 40) -> None:
        cases = [fabricated_case(i) for i in range(count)]
        self.sealed.write_text(json.dumps({"cases": cases}))

    def seal(self) -> None:
        self.manifest.write_text(json.dumps({"held_out": {"sha256": sha(self.sealed)}}))

    def write_sheet(self, size: int = 36, ticks: str = "correct") -> list[str]:
        cases = json.loads(self.sealed.read_text())["cases"]
        sample = pools.sample_for_review(cases, size=size, seed=1)
        text = pools.render_review_sheet(sample)
        if ticks == "correct":
            text = text.replace("- [ ] correct", "- [x] correct")
        self.sheet.write_text(text)
        return [str(c["id"]) for c in sample]

    def attest(self, **kw: Any) -> dict[str, Any]:
        return review_gate.write_attestation(
            self.sheet,
            self.sealed,
            manifest_path=self.manifest,
            owner_confirmed=kw.pop("owner_confirmed", True),
            **kw,
        )

    def load(self, **kw: Any) -> dict[str, Any]:
        return pools.load_held_out(self.sealed, **kw)


@pytest.fixture
def area(tmp_path, monkeypatch):
    built = Area(tmp_path)
    monkeypatch.setattr(pools, "FREEZE_MANIFEST", built.manifest)
    monkeypatch.setenv(pools.HELD_OUT_ENV, str(built.sealed))
    return built


def attestation_path(area: Area) -> Path:
    return review_gate.attestation_path(area.sealed)


# --- the weakness: nothing stops a load of the sealed pool without a review --------------------------


def test_default_load_refuses_without_an_attestation(area):
    with pytest.raises(review_gate.ReviewRequired) as caught:
        area.load()
    assert MARKER not in str(caught.value) and "gate0" not in str(caught.value)


def test_free_loaders_still_work_without_an_attestation(area):
    assert len(area.load(require_review=False)["cases"]) == 40
    assert coverage.held_out_view()[2] == "the sealed file"
    assert (
        sum(
            pools.write_review_sheet(
                area.dir.parent / "outside" / "s.md", held_out=area.sealed
            ).values()
        )
        == 30
    )


# --- a valid attestation passes; each defect refuses -------------------------------------------------


def test_a_matching_attestation_passes(area):
    area.write_sheet()
    record = area.attest()
    assert record["reviewed"] == 36 and record["gold_wrong"] == 0 and record["correct"] == 36
    assert len(area.load()["cases"]) == 40
    assert oct(attestation_path(area).stat().st_mode & 0o777) == "0o600"
    assert record["sealed_sha256"] == sha(area.sealed) == record["freeze_held_out_sha256"]


def test_attestation_holds_no_case_text_or_id(area):
    ids = area.write_sheet()
    area.attest()
    stored = attestation_path(area).read_text()
    assert MARKER not in stored and not any(i in stored for i in ids)


def test_amending_the_sealed_file_invalidates_the_attestation(area):
    area.write_sheet()
    area.attest()
    area.write_sealed(41)  # an amendment changes the bytes
    with pytest.raises(review_gate.ReviewRequired, match="changed since"):
        area.load()
    area.seal()  # and re-sealing the manifest alone does not revive the old approval
    with pytest.raises(review_gate.ReviewRequired, match="changed since"):
        area.load()


def test_manifest_checksum_mismatch_refuses(area):
    area.write_sheet()
    area.attest()
    area.manifest.write_text(json.dumps({"held_out": {"sha256": "0" * 64}}))
    with pytest.raises(review_gate.ReviewRequired, match="freeze"):
        area.load()


@pytest.mark.parametrize(
    "damage",
    [
        lambda p: p.write_text("{not json"),
        lambda p: p.write_text("[]"),
        lambda p: p.write_text(json.dumps({"version": 1})),
        lambda p: p.write_text(""),
    ],
    ids=["garbled", "wrong-type", "missing-fields", "empty"],
)
def test_corrupted_attestation_refuses(area, damage):
    area.write_sheet()
    area.attest()
    damage(attestation_path(area))
    with pytest.raises(review_gate.ReviewRequired):
        area.load()


@pytest.mark.parametrize(
    "field,value",
    [
        ("reviewed", 29),
        ("gold_wrong", 1),
        ("correct", 5),
        ("sealed_sha256", "f" * 64),
        ("version", 2),
    ],
)
def test_a_tampered_field_refuses(area, field, value):
    area.write_sheet()
    area.attest()
    path = attestation_path(area)
    record = json.loads(path.read_text())
    record[field] = value
    path.write_text(json.dumps(record))
    with pytest.raises(review_gate.ReviewRequired):
        area.load()


def test_attestation_for_another_sealed_file_does_not_transfer(area, tmp_path):
    area.write_sheet()
    area.attest()
    other_root = tmp_path / "other"
    other_root.mkdir()
    other = Area(other_root, count=41)  # a different sealed file, sealed in its own manifest
    other_attestation = review_gate.attestation_path(other.sealed)
    other_attestation.write_text(attestation_path(area).read_text())
    with pytest.raises(review_gate.ReviewRequired, match="changed since"):
        pools.load_held_out(other.sealed, manifest_path=other.manifest)


# --- the attest command refuses an unfinished or foreign review --------------------------------------


def test_attest_requires_owner_confirmation(area):
    area.write_sheet()
    with pytest.raises(review_gate.ReviewRefused, match="confirm"):
        area.attest(owner_confirmed=False)
    assert not attestation_path(area).exists()


def test_attest_refuses_an_unticked_case(area):
    area.write_sheet()
    area.sheet.write_text(area.sheet.read_text().replace("- [x] correct", "- [ ] correct", 1))
    with pytest.raises(review_gate.ReviewRefused, match="exactly one"):
        area.attest()
    assert not attestation_path(area).exists()


def test_attest_refuses_a_doubly_ticked_case(area):
    area.write_sheet()
    area.sheet.write_text(area.sheet.read_text().replace("- [ ] gold wrong", "- [x] gold wrong", 1))
    with pytest.raises(review_gate.ReviewRefused, match="exactly one"):
        area.attest()


def test_attest_refuses_a_gold_wrong_case(area):
    area.write_sheet()
    area.sheet.write_text(
        area.sheet.read_text().replace(
            "- [x] correct    - [ ] gold wrong", "- [ ] correct    - [x] gold wrong", 1
        )
    )
    with pytest.raises(review_gate.ReviewRefused, match="gold wrong"):
        area.attest()
    assert not attestation_path(area).exists()


def test_attest_refuses_fewer_than_thirty_cases(area):
    area.write_sheet(size=29)
    with pytest.raises(review_gate.ReviewRefused, match="at least 30"):
        area.attest()


def test_attest_refuses_a_sheet_for_another_sealed_file(area):
    area.write_sheet()
    area.write_sealed(40)
    area.sealed.write_text(area.sealed.read_text().replace(f"{MARKER} answer", "something else"))
    area.seal()
    with pytest.raises(review_gate.ReviewRefused, match="does not correspond"):
        area.attest()


def test_attest_refuses_an_unknown_case(area):
    area.write_sheet()
    area.sheet.write_text(area.sheet.read_text().replace("gate", "gzte", 1))
    with pytest.raises(review_gate.ReviewRefused, match="does not correspond"):
        area.attest()


def test_attest_refuses_a_duplicated_case(area):
    area.write_sheet()
    text = area.sheet.read_text()
    first = "## " + text.split("\n## ")[1]  # the first case block
    area.sheet.write_text(text + "\n" + first)
    with pytest.raises(review_gate.ReviewRefused, match="duplicate"):
        area.attest()


def test_attest_refuses_when_the_freeze_does_not_match_the_sealed_file(area):
    area.write_sheet()
    area.manifest.write_text(json.dumps({"held_out": {"sha256": "0" * 64}}))
    with pytest.raises(review_gate.ReviewRefused, match="freeze"):
        area.attest()


def test_attest_refuses_a_sheet_inside_the_repository(area):
    inside = pools.REPO_ROOT / "docs" / "zq-sheet-never-written.md"
    with pytest.raises(review_gate.ReviewRefused, match="repository"):
        review_gate.write_attestation(
            inside, area.sealed, manifest_path=area.manifest, owner_confirmed=True
        )
    assert not inside.exists()


# --- the CLI entry points ----------------------------------------------------------------------------


def test_paid_run_entry_point_refuses_before_any_spend(area, monkeypatch):
    """`cli run --split held_out` loads the pool through the gate, so it stops with no spend and no case text."""
    import argparse

    args = argparse.Namespace(
        split="held_out",
        ids=None,
        category=None,
        limit=None,
        repeats=1,
        dataset=None,
        with_messy=False,
    )
    monkeypatch.setattr(cli, "corpus_files", lambda **_: [])
    monkeypatch.setattr(cli, "verify", lambda _files: None)
    import asyncio

    with pytest.raises(review_gate.ReviewRequired) as caught:
        asyncio.run(cli.run(args))
    assert MARKER not in str(caught.value)


def run_module(
    args: list[str], area: Area, stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, pools.HELD_OUT_ENV: str(area.sealed)}
    return subprocess.run(
        [sys.executable, "-I", "-m", "evaluation.rag_eval.pools", *args],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_attest_command_refuses_without_a_terminal(area):
    area.write_sheet()
    done = run_module(["attest-review", str(area.sheet)], area, stdin=CONFIRM + "\n")
    assert done.returncode != 0
    assert "terminal" in (done.stdout + done.stderr)
    assert MARKER not in done.stdout + done.stderr
    assert not attestation_path(area).exists()


def test_help_text_names_the_gate_and_never_writes_one():
    doc = pools.__doc__ or ""
    assert "attest-review" in doc and re.search(r"Owner", doc)


class FakeTerminal:
    def isatty(self) -> bool:
        return True


def test_attest_command_needs_the_typed_phrase_then_writes(area, capsys):
    area.write_sheet()
    args = (area.sheet, area.sealed, area.manifest)
    assert review_gate.attest_command(*args, stdin=FakeTerminal(), ask=lambda _p: "yes") == 1
    assert not attestation_path(area).exists()
    assert review_gate.attest_command(*args, stdin=FakeTerminal(), ask=lambda _p: CONFIRM) == 0
    assert attestation_path(area).exists() and len(area.load()["cases"]) == 40
    shown = capsys.readouterr().out
    assert MARKER not in shown and "gate0" not in shown


def test_attest_command_refuses_a_pipe(area):
    area.write_sheet()

    class Pipe:
        def isatty(self) -> bool:
            return False

    code = review_gate.attest_command(
        area.sheet, area.sealed, area.manifest, stdin=Pipe(), ask=lambda _p: CONFIRM
    )
    assert code == 2 and not attestation_path(area).exists()
