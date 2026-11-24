"""Run ticket 04's real paid-command block (answer-reliability) against stand-in commands.

Same method as ``test_pilot_chain``: ``uv`` is a shim, ``cli run`` is a fake that writes (or does not write) a result
file, ``pilot_gate`` runs for real against a temporary folder with a patched git state. No provider call, no store.
What is under test is control flow only: a failure of run 1 at any step must never start run 2, and the block must
report failure through its exit status.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.evaluation.test_pilot_chain import BACKEND, SHIM
from tests.evaluation.test_pilot_gate import HEAD, arm

TICKET = BACKEND.parent / "docs/tickets/answer-reliability/04-targeted-real-model-validation.md"


def chain_block() -> str:
    text = TICKET.read_text()
    start = text.index("# RELIABILITY-CHAIN")
    return text[start : text.index("```", start)]


def run_chain(
    tmp_path: Path, *, fake: str = "ok", tree_clean: bool = True
) -> tuple[int, list[str]]:
    shim_dir, results = tmp_path / "bin", tmp_path / "results"
    shim_dir.mkdir()
    results.mkdir()
    shim = shim_dir / "uv"
    shim.write_text(SHIM.format(python=sys.executable, backend=str(BACKEND)))
    shim.chmod(0o755)
    template = tmp_path / "template.json"
    data = arm("A", False)
    data["diagnostics"] = {"claim_check_trace": True}
    template.write_text(json.dumps(data))
    log = tmp_path / "log.txt"
    log.write_text("")
    env = {
        **os.environ,
        "PATH": f"{shim_dir}{os.pathsep}{os.environ['PATH']}",
        "CHAIN_LOG": str(log),
        "CHAIN_RESULTS": str(results),
        "CHAIN_TEMPLATE": str(template),
        "FAKE_A": fake,
        "FAKE_GIT": json.dumps({"commit": HEAD, "tree_clean": tree_clean}),
    }
    done = subprocess.run(
        ["bash", "-c", chain_block()],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return done.returncode, log.read_text().splitlines()


def test_the_block_is_fail_fast_capped_and_uses_the_claim_trace_gate() -> None:
    block = chain_block()
    assert "--cap 0.15" in block and block.count("--cap") == 1
    assert (
        "--repeats 1" in block
        and "--trace-claim-check" in block
        and "--require-claim-trace" in block
    )
    assert "set -e" not in block and "ls -t" not in block and "break" not in block
    assert "exit 1" in block and block.count("&& uv run") == 2
    assert "--split dev" in block and "held_out" not in block and "--retrieval-strategy A" in block


def test_two_good_runs_are_two_separate_gated_runs(tmp_path: Path) -> None:
    code, log = run_chain(tmp_path)
    assert code == 0
    assert log == ["gate --preflight", "cli A", "gate --strategy"] * 2


@pytest.mark.parametrize(
    "mode",
    [
        "fail",
        "silent_nofile",
        "incomplete",
        "error_row",
        "wrong_commit",
        "dirty_manifest",
        "wrong_ids",
        "wrong_tag",
        "wrong_strategy",
    ],
)
def test_a_failed_first_run_never_starts_a_second_paid_run_and_the_block_fails(
    tmp_path: Path, mode: str
) -> None:
    code, log = run_chain(tmp_path, fake=mode)
    assert code != 0
    assert log.count("cli A") == 1


def test_a_dirty_tree_stops_before_any_paid_command(tmp_path: Path) -> None:
    code, log = run_chain(tmp_path, tree_clean=False)
    assert code != 0 and log == ["gate --preflight"]
