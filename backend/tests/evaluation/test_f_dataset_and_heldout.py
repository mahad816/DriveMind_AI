"""M1-08-F: case-file access and held-out boundaries of the evaluation commands.

Everything here is fabricated: temporary folders stand in for ``evaluation/datasets`` and for the sealed store, and
the "protected" text is a marker no real file holds. No sealed file is read, no provider is called and no database is
opened. A test that would reach the provider fails through the tripwire fixture.

Defects covered (each reproduced before the fix):

* ``load_cases`` joined the name onto the datasets folder, so ``cli run --dataset`` followed an absolute path, ``..``
  or a symlink to any file, including a sealed one.
* ``cli run --split held_out`` accepted ``--threshold`` and ``--relative`` (tuning against the held-out pool).
* ``cli run`` let an error raised while reading or validating the sealed file leave with its message.
* ``cli rescore`` of a held-out result file quoted a held-out case id in a ``KeyError``.
"""

import argparse
import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

import pytest

from evaluation.rag_eval import cli, dataset, pools, review_gate
from evaluation.rag_eval.meter import CostMeter

MARKER = "ZQ-FABRICATED-PROTECTED-TEXT-0042"


@pytest.fixture(autouse=True)
def no_provider_call(monkeypatch: pytest.MonkeyPatch) -> None:
    from openai.resources.chat.completions import AsyncCompletions
    from openai.resources.embeddings import AsyncEmbeddings

    async def tripwire(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a provider call was attempted")

    monkeypatch.setattr(AsyncEmbeddings, "create", tripwire)
    monkeypatch.setattr(AsyncCompletions, "create", tripwire)


@pytest.fixture
def datasets_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "datasets"
    folder.mkdir()
    (folder / "ok.json").write_text(json.dumps({"cases": [{"id": "a", "split": "dev"}]}))
    monkeypatch.setattr(dataset, "DATA", folder)
    return folder


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    """A fabricated 'sealed' file outside the datasets folder."""
    folder = tmp_path / "outside"
    folder.mkdir()
    path = folder / "sealed.json"
    path.write_text(json.dumps({"cases": [{"id": MARKER, "split": "held_out"}]}))
    return path


# ---- dataset access --------------------------------------------------------------------------------------


def test_a_bare_name_inside_the_folder_loads(datasets_dir: Path):
    assert dataset.load_cases("ok.json")["cases"][0]["id"] == "a"
    assert dataset.load_many(["ok.json"])["cases"][0]["id"] == "a"


@pytest.mark.parametrize(
    "name",
    [
        "../outside/sealed.json",
        "sub/ok.json",
        "..",
        ".",
        "",
        "ok.txt",
        "ok",
        "..\\ok.json",
        "a\x00.json",
    ],
)
def test_names_that_are_not_bare_json_file_names_are_refused(datasets_dir: Path, name: str):
    with pytest.raises(ValueError, match="not a case file"):
        dataset.load_cases(name)
    with pytest.raises(ValueError, match="not a case file"):
        dataset.load_many([name])


def test_an_absolute_path_is_refused_and_the_target_is_never_read(
    datasets_dir: Path, outside: Path
):
    with pytest.raises(ValueError, match="not a case file") as caught:
        dataset.load_many([str(outside)])
    # the message may repeat the name the caller typed, never what is inside the file
    assert MARKER not in str(caught.value)


def test_a_symlink_to_a_file_outside_the_folder_is_refused(datasets_dir: Path, outside: Path):
    os.symlink(outside, datasets_dir / "link.json")
    with pytest.raises(ValueError, match="not a case file") as caught:
        dataset.load_cases("link.json")
    assert MARKER not in str(caught.value) and str(outside.parent) not in str(caught.value)


def test_any_symlink_is_refused_even_inside_the_folder(datasets_dir: Path):
    os.symlink(datasets_dir / "ok.json", datasets_dir / "alias.json")
    with pytest.raises(ValueError, match="not a case file"):
        dataset.load_cases("alias.json")


def test_a_missing_file_is_a_plain_refusal_not_a_path_leak(datasets_dir: Path):
    with pytest.raises(ValueError, match="not a case file") as caught:
        dataset.load_cases("nope.json")
    assert str(datasets_dir) not in str(caught.value)


def stub_for_run(monkeypatch: pytest.MonkeyPatch, events: list[str]) -> None:
    monkeypatch.setattr(cli, "corpus_files", lambda **_: events.append("corpus") or [])
    monkeypatch.setattr(cli, "verify", lambda _f: None)
    monkeypatch.setattr(cli, "CostMeter", lambda *_a, **_k: pytest.fail("no spend"))


def run_args(**changes: Any) -> argparse.Namespace:
    base: dict[str, Any] = dict(
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


def test_cli_run_refuses_an_outside_dataset_before_any_spend(
    datasets_dir: Path, outside: Path, monkeypatch: pytest.MonkeyPatch
):
    stub_for_run(monkeypatch, [])
    with pytest.raises(SystemExit, match="not a case file") as caught:
        asyncio.run(cli.run(run_args(split="dev", dataset=[str(outside)])))
    assert MARKER not in str(caught.value)


def test_rescore_refuses_an_outside_dataset_named_in_a_saved_file(
    datasets_dir: Path, outside: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    stub_for_run(monkeypatch, [])
    saved = tmp_path / "result.json"
    saved.write_text(json.dumps({"rows": [], "model": "m", "datasets": [str(outside)]}))
    args = run_args(command="rescore", file=str(saved), frozen=False, store=None)
    with pytest.raises(SystemExit, match="not a case file") as caught:
        asyncio.run(cli.rescore(args))
    assert MARKER not in str(caught.value)


def test_rescore_never_reads_a_held_out_result_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    stub_for_run(monkeypatch, [])
    saved = tmp_path / "heldout_result.json"
    saved.write_text(
        json.dumps({"split": "held_out", "rows": [{"id": MARKER}], "model": "m", "datasets": []})
    )
    args = run_args(command="rescore", file=str(saved), frozen=False, store=None)
    with pytest.raises(SystemExit, match="held-out") as caught:
        asyncio.run(cli.rescore(args))
    assert MARKER not in str(caught.value) and caught.value.__cause__ is None


# ---- held-out tuning flags -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "flags", [{"threshold": 0.3}, {"relative": 0.5}, {"threshold": 0.1, "relative": 0.2}]
)
def test_the_held_out_run_refuses_threshold_overrides_before_reading_anything(
    flags: dict[str, float], monkeypatch: pytest.MonkeyPatch
):
    events: list[str] = []
    stub_for_run(monkeypatch, events)
    monkeypatch.setattr(cli, "held_out_path", lambda: pytest.fail("the sealed path was looked up"))
    with pytest.raises(SystemExit, match="held-out") as caught:
        asyncio.run(cli.run(run_args(**flags)))
    assert "--threshold" in str(caught.value) or "--relative" in str(caught.value)
    assert events == []  # not even the corpus was read


def test_threshold_overrides_stay_allowed_on_development(monkeypatch: pytest.MonkeyPatch):
    events: list[str] = []
    stub_for_run(monkeypatch, events)
    monkeypatch.setattr(cli, "load_many", lambda _n: {"cases": []})
    monkeypatch.setattr(cli, "validate", lambda *_a, **_k: [])
    monkeypatch.setattr(cli, "files_to_check", lambda *_a: [])
    with pytest.raises(SystemExit, match="No cases selected"):  # got past the flag check
        asyncio.run(cli.run(run_args(split="dev", threshold=0.3, relative=0.4)))


# ---- sealed source and attestation -----------------------------------------------------------------------


class Sealed:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        folder = tmp_path / "sealed_store"
        folder.mkdir()
        self.path = folder / "sealed.json"
        self.path.write_text(json.dumps({"cases": [{"id": MARKER, "split": "held_out"}]}))
        monkeypatch.setenv(pools.HELD_OUT_ENV, str(self.path))
        self.digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.manifest = tmp_path / "freeze.json"
        self.manifest.write_text(json.dumps({"held_out": {"sha256": self.digest}}))
        monkeypatch.setattr(pools, "FREEZE_MANIFEST", self.manifest)

    def attest(self, **changes: Any) -> None:
        record: dict[str, Any] = {
            "version": review_gate.VERSION,
            "sealed_sha256": self.digest,
            "freeze_held_out_sha256": self.digest,
            "sheet_sha256": self.digest,
            "reviewed": 36,
            "correct": 36,
            "gold_wrong": 0,
            "attested_at": "2026-01-01T00:00:00+00:00",
        }
        review_gate.attestation_path(self.path).write_text(json.dumps({**record, **changes}))


@pytest.fixture
def sealed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Sealed:
    monkeypatch.delenv("OPENAI_LOG", raising=False)
    return Sealed(tmp_path, monkeypatch)


@pytest.fixture
def library_log_level() -> Any:
    """Set a library logger's level through ``setLevel`` (it clears the logger's isEnabledFor cache) and restore it."""
    saved: list[tuple[logging.Logger, int]] = []

    def set_level(name: str, level: int) -> None:
        logger = logging.getLogger(name)
        saved.append((logger, logger.level))
        logger.setLevel(level)

    yield set_level
    for logger, level in reversed(saved):
        logger.setLevel(level)


def tamper(s: Sealed) -> None:
    s.attest()
    s.path.write_text(s.path.read_text() + " ")  # the sealed file changed after the review


@pytest.mark.parametrize(
    ("prepare", "expected"),
    [
        (lambda s: None, "no Owner review attestation"),
        (tamper, "changed since"),
        (lambda s: review_gate.attestation_path(s.path).write_text("{not json"), "unreadable"),
        (lambda s: s.attest(version=99), "malformed"),
        (lambda s: s.attest(gold_wrong=1), "completed review"),
        (lambda s: s.attest(reviewed=5, correct=5), "completed review"),
    ],
    ids=["missing", "stale", "unreadable", "malformed", "gold-wrong", "too-few"],
)
def test_the_held_out_run_needs_a_valid_attestation_and_leaks_nothing_without_one(
    sealed: Sealed, monkeypatch: pytest.MonkeyPatch, prepare: Any, expected: str
):
    prepare(sealed)
    stub_for_run(monkeypatch, [])
    with pytest.raises(review_gate.ReviewRequired, match=expected) as caught:
        asyncio.run(cli.run(run_args()))
    assert MARKER not in str(caught.value)


def test_a_missing_sealed_file_stops_with_a_plain_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    stub_for_run(monkeypatch, [])
    monkeypatch.setenv(pools.HELD_OUT_ENV, str(tmp_path / "gone" / "sealed.json"))
    with pytest.raises(SystemExit, match="STOPPED") as caught:
        asyncio.run(cli.run(run_args()))
    assert caught.value.__cause__ is None


def test_a_sealed_path_inside_the_repository_is_refused_by_the_run(
    monkeypatch: pytest.MonkeyPatch,
):
    stub_for_run(monkeypatch, [])
    inside = pools.REPO_ROOT / "backend" / "evaluation" / "datasets" / "rag_v2_cases.json"
    monkeypatch.setenv(pools.HELD_OUT_ENV, str(inside))
    with pytest.raises(SystemExit, match="repository"):
        asyncio.run(cli.run(run_args()))


def test_an_error_while_reading_the_sealed_file_leaves_by_class_name_only(
    sealed: Sealed, monkeypatch: pytest.MonkeyPatch
):
    stub_for_run(monkeypatch, [])

    def broken(_path: Path) -> Any:
        raise RuntimeError(f"cannot parse {MARKER}")

    monkeypatch.setattr(cli, "load_held_out", broken)
    with pytest.raises(SystemExit) as caught:
        asyncio.run(cli.run(run_args()))
    assert "RuntimeError" in str(caught.value) and MARKER not in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


def test_an_error_while_validating_the_sealed_cases_leaves_by_class_name_only(
    sealed: Sealed, monkeypatch: pytest.MonkeyPatch
):
    stub_for_run(monkeypatch, [])
    monkeypatch.setattr(cli, "load_held_out", lambda _p: {"cases": []})

    def broken(*_a: Any, **_k: Any) -> Any:
        raise KeyError(MARKER)

    monkeypatch.setattr(cli, "validate", broken)
    with pytest.raises(SystemExit) as caught:
        asyncio.run(cli.run(run_args()))
    assert "KeyError" in str(caught.value) and MARKER not in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


# ---- third-party logging ---------------------------------------------------------------------------------


def test_the_openai_sdk_writes_request_bodies_to_its_debug_log():
    """The reason for the guard below: at DEBUG the SDK logs 'Request options' with the request body, which for the
    held-out pool is the question text. The evaluation code never sets DEBUG itself (checked by the next test)."""
    import inspect

    from openai import _base_client

    source = inspect.getsource(_base_client.BaseClient._build_request)
    assert "Request options" in source and '"json_data"' not in source.split("exclude=")[1][:200]


@pytest.mark.parametrize(
    "name", ["openai", "httpx", "httpcore", "qdrant_client", "sqlalchemy.engine"]
)
def test_a_held_out_run_refuses_while_a_library_logs_at_debug(
    sealed: Sealed, monkeypatch: pytest.MonkeyPatch, library_log_level: Any, name: str
):
    sealed.attest()
    stub_for_run(monkeypatch, [])
    library_log_level(name, logging.DEBUG)
    with pytest.raises(SystemExit, match="logging") as caught:
        asyncio.run(cli.run(run_args()))
    assert MARKER not in str(caught.value)


def test_a_held_out_run_refuses_when_the_sdk_log_variable_asks_for_debug(
    sealed: Sealed, monkeypatch: pytest.MonkeyPatch
):
    sealed.attest()
    stub_for_run(monkeypatch, [])
    monkeypatch.setenv("OPENAI_LOG", "debug")
    with pytest.raises(SystemExit, match="OPENAI_LOG"):
        asyncio.run(cli.run(run_args()))


def test_the_evaluation_package_never_configures_debug_logging():
    root = Path(cli.__file__).parent
    offenders = [
        p.name
        for p in root.glob("*.py")
        if any(w in p.read_text() for w in ("basicConfig", "logging.DEBUG", "OPENAI_LOG"))
        and p.name != "pools.py"  # the guard itself names them
    ]
    assert offenders == []


# ---- result files beside the sealed file -----------------------------------------------------------------


def test_the_cost_meter_is_importable_without_a_key():
    assert CostMeter(1.0).cap_usd == 1.0


# ---- the private result folder and files -----------------------------------------------------------------


def mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


@pytest.fixture
def open_umask() -> Any:
    """A permissive umask, so that only explicit modes can make the folder and files private."""
    previous = os.umask(0o000)
    yield
    os.umask(previous)


def test_a_new_private_folder_is_owner_only_even_under_an_open_umask(
    tmp_path: Path, open_umask: None
):
    from evaluation.rag_eval.sealing import private_folder

    folder = private_folder(tmp_path / "heldout_results")
    assert mode(folder) == 0o700


def test_an_existing_loose_folder_is_tightened(tmp_path: Path, open_umask: None):
    from evaluation.rag_eval.sealing import private_folder

    folder = tmp_path / "heldout_results"
    folder.mkdir(mode=0o755)
    folder.chmod(0o755)
    assert mode(private_folder(folder)) == 0o700


def test_a_private_file_is_owner_only_from_its_creation_and_when_overwritten(
    tmp_path: Path, open_umask: None, monkeypatch: pytest.MonkeyPatch
):
    from evaluation.rag_eval import sealing

    modes: list[int] = []
    real_open = os.open

    def spy(path: Any, flags: int, mode_arg: int = 0o777, **kw: Any) -> int:
        modes.append(mode_arg)
        return real_open(path, flags, mode_arg, **kw)

    monkeypatch.setattr(sealing.os, "open", spy)
    target = tmp_path / "result.json"
    target.write_text("old")
    target.chmod(0o644)  # a file that already exists with loose permissions
    sealing.write_private(target, "new")
    assert modes == [0o600] and mode(target) == 0o600 and target.read_text() == "new"
    fresh = tmp_path / "fresh.json"
    sealing.write_private(fresh, "x")
    assert modes == [0o600, 0o600] and mode(fresh) == 0o600


def test_the_probe_report_goes_into_a_private_folder_made_before_the_write(
    tmp_path: Path, open_umask: None, monkeypatch: pytest.MonkeyPatch
):
    from evaluation.rag_eval import probe_pools, sealing

    sealed_file = tmp_path / "store" / "sealed.json"
    sealed_file.parent.mkdir()
    sealed_file.write_text("{}")
    loose = sealed_file.parent / cli.HELD_OUT_RESULTS
    loose.mkdir(mode=0o755)
    loose.chmod(0o755)
    seen: list[int] = []
    real = sealing.write_private

    def spy(path: Path, text: str) -> None:
        seen.append(
            mode(path.parent)
        )  # the folder's mode at the moment the confidential file is written
        real(path, text)

    monkeypatch.setattr(probe_pools, "write_private", spy)
    written = probe_pools.write_sealed_report(
        {"held_out": {"n": 1}}, sealed_file, "20260101_000000"
    )
    assert seen == [0o700] and mode(written.parent) == 0o700 and mode(written) == 0o600
