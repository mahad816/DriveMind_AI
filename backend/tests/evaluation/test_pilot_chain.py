"""Run the ticket's real paid-command block against stand-in commands: arm C2-cap3 must never start unless arm A
succeeded and its own, current result passed the gate.

``uv`` is replaced by a shim on PATH. ``cli run`` becomes a fake that writes (or does not write) a result file in a
temporary folder; ``pilot_gate`` runs for real against that folder with a patched git state. No provider call,
no store, no paid work: the block's control flow is what is under test.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.evaluation.test_pilot_gate import HEAD, arm

BACKEND = Path(__file__).resolve().parents[2]
TICKET = BACKEND.parent / "docs/tickets/hybrid-retrieval-comparison/02-answer-quality-pilot.md"
SHIM = """#!{python}
import json, os, sys, datetime
sys.path.insert(0, {backend!r})
args = sys.argv[1:]
assert args[:3] == ["run", "python", "-m"], args
module, rest = args[3], args[4:]
log = open(os.environ["CHAIN_LOG"], "a")
results = os.environ["CHAIN_RESULTS"]
if module == "evaluation.rag_eval.cli":
    strategy = rest[rest.index("--retrieval-strategy") + 1]
    tag = rest[rest.index("--tag") + 1]
    start = rest.index("--ids") + 1
    ids = []
    for word in rest[start:]:
        if word.startswith("--"):
            break
        ids.append(word)
    log.write("cli " + strategy + "\\n"); log.flush()
    mode = os.environ["FAKE_A"] if strategy == "A" else os.environ.get("FAKE_C2", "ok")
    if mode == "fail":
        sys.exit(1)
    if mode == "silent_nofile":  # a cap abort that exits 0 and wrote nothing
        sys.exit(0)
    data = json.load(open(os.environ["CHAIN_TEMPLATE"]))
    data["tag"] = tag
    data["started"] = datetime.datetime.now(datetime.UTC).isoformat()
    label = "A" if strategy == "A" else "C2-cap3"
    data["manifest"]["retrieval_strategy"] = {{"label": label, "selected_explicitly": True}}
    data["manifest"]["settings"]["retrieval_dual_query_enabled"] = label != "A"
    data["manifest"]["case_ids"] = ids
    data["rows"] = [{{"id": i, "error": None, "accounting": {{"total": {{}}}}}} for i in ids]
    if mode == "incomplete":
        data["summary"] = {{"incomplete": True, "cap_stopped": 2}}
    if mode == "error_row":
        data["rows"][0]["error"] = "TimeoutError"
    if mode == "wrong_commit":
        data["manifest"]["commit"] = "d" * 40
    if mode == "dirty_manifest":
        data["manifest"]["tree_clean"] = False
    if mode == "wrong_ids":
        data["manifest"]["case_ids"] = ids[:-1]
        data["rows"] = data["rows"][:-1]
    if mode == "wrong_tag":
        data["tag"] = "pilot_20250101_000000_1_" + label
    if mode == "wrong_strategy":
        data["manifest"]["retrieval_strategy"]["label"] = "C2-cap3" if label == "A" else "A"
    name = "rag_v2_20261125_101500_tool_agent_gpt-5.4-nano_dev_" + tag + ".json"
    open(os.path.join(results, name), "w").write(json.dumps(data))
    sys.exit(0)
log.write("gate " + " ".join(a for a in rest if a in ("--preflight", "--pair", "--strategy")) + "\\n"); log.flush()
from evaluation.rag_eval import pilot_gate
pilot_gate.git_state = lambda: json.loads(os.environ["FAKE_GIT"])
sys.exit(pilot_gate.main(rest + ["--results-dir", results]))
"""


def chain_block() -> str:
    text = TICKET.read_text()
    start = text.index("# PILOT-CHAIN")
    return text[start : text.index("```", start)]


def run_chain(
    tmp_path: Path,
    *,
    fake_a: str = "ok",
    fake_c2: str = "ok",
    git: dict[str, Any] | None = None,
    planted: dict[str, dict[str, Any]] | None = None,
) -> tuple[int, list[str], Path]:
    """``planted``: result files that already sit in the results folder before the chain starts."""
    shim_dir, results = tmp_path / "bin", tmp_path / "results"
    shim_dir.mkdir()
    results.mkdir()
    for name, content in (planted or {}).items():
        (results / name).write_text(json.dumps(content))
    shim = shim_dir / "uv"
    shim.write_text(SHIM.format(python=sys.executable, backend=str(BACKEND)))
    shim.chmod(0o755)
    template = tmp_path / "template.json"
    template.write_text(json.dumps(arm("A", False)))
    log = tmp_path / "log.txt"
    log.write_text("")
    env = {
        **os.environ,
        "PATH": f"{shim_dir}{os.pathsep}{os.environ['PATH']}",
        "CHAIN_LOG": str(log),
        "CHAIN_RESULTS": str(results),
        "CHAIN_TEMPLATE": str(template),
        "FAKE_A": fake_a,
        "FAKE_C2": fake_c2,
        "FAKE_GIT": json.dumps(git or {"commit": HEAD, "tree_clean": True}),
    }
    done = subprocess.run(
        ["bash", "-c", chain_block()],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return done.returncode, log.read_text().splitlines(), results


def test_the_block_is_one_fail_fast_chain_with_both_caps_and_a_unique_run_id() -> None:
    block = chain_block()
    assert block.count("--cap 0.25") == 2 and "--cap 0.5" not in block
    assert block.count("&& uv run") == 5 and "ls -t" not in block and "set -e" not in block
    assert '--tag "${RUN}_A"' in block and '--tag "${RUN}_C2-cap3"' in block
    assert block.count("--retrieval-strategy") == 2 and "--repeats 1" in block


def test_a_successful_arm_a_permits_arm_c2_cap3_and_the_pair_is_checked(tmp_path: Path) -> None:
    code, log, results = run_chain(tmp_path)
    assert code == 0
    assert log == [
        "gate --preflight",
        "cli A",
        "gate --strategy",
        "cli C2-cap3",
        "gate --strategy",
        "gate --pair",
    ]
    assert len(list(results.glob("*.json"))) == 2


@pytest.mark.parametrize(
    "mode",
    [
        "fail",  # arm A exits non-zero
        "silent_nofile",  # exits 0 but wrote nothing (e.g. a cap abort); an older result exists too
        "incomplete",
        "error_row",
        "wrong_commit",
        "dirty_manifest",
        "wrong_ids",
        "wrong_tag",
        "wrong_strategy",
    ],
)
def test_a_failed_missing_stale_or_mismatched_arm_a_never_permits_arm_c2_cap3(
    tmp_path: Path, mode: str
) -> None:
    # An older, complete result of the same arm, strategy and commit sits in the folder: not this run's.
    old_run = "pilot_20250101_000000_1"
    old = {f"rag_v2_old_tool_agent_m_dev_{old_run}_A.json": arm("A", False, run=old_run)}
    code, log, _ = run_chain(tmp_path, fake_a=mode, planted=old)
    assert code != 0
    assert "cli C2-cap3" not in log and "cli A" in log


def test_a_failed_arm_c2_cap3_ends_the_chain_before_the_pair_check(tmp_path: Path) -> None:
    code, log, _ = run_chain(tmp_path, fake_c2="fail")
    assert code != 0 and log[-1] == "cli C2-cap3" and "gate --pair" not in log


def test_a_dirty_working_tree_stops_the_chain_before_any_paid_command(tmp_path: Path) -> None:
    code, log, results = run_chain(tmp_path, git={"commit": HEAD, "tree_clean": False})
    assert code != 0 and log == ["gate --preflight"]
    assert list(results.glob("*.json")) == []
