"""Free checks around the two paid arms of the answer-quality pilot (ticket hybrid-retrieval-comparison/02).

    python -m evaluation.rag_eval.pilot_gate --preflight --run-id RUN
    python -m evaluation.rag_eval.pilot_gate --run-id RUN --strategy A|C2-cap3 --ids ID [ID ...] [--require-claim-trace]
    python -m evaluation.rag_eval.pilot_gate --run-id RUN --pair

Each paired evaluation has one unique run id (RUN). Both arms are started with ``--tag RUN_<strategy>``, and the
result file records that tag, so a result is found by its own run id: exactly one file must match, and its stored
tag, strategy, case set and commit must match too. The newest file of some earlier run is never picked up, and a
result that belongs to an older run is "missing", not "stale but fine".

These commands read local files and ``git`` only; they never call a provider and never print reply text. They
exit non-zero on any problem. They do not start anything themselves: the pilot's shell chain (``&&`` between
every step, see the ticket) stops where a command exits non-zero, so arm C2-cap3 starts only after arm A's result
passed ``--run-id RUN --strategy A``.
"""

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .manifest import git_state

FLAG = "retrieval_dual_query_enabled"
LABELS = {"A": False, "C2-cap3": True}
RESULTS = Path(__file__).resolve().parents[1] / "results"
RUN_ID = re.compile(r"[A-Za-z0-9_]{8,64}")
# Manifest fields that must be equal in both arms (everything that could change an answer or its price).
SAME_IN_BOTH_ARMS = (
    "commit",
    "tree_clean",
    "prompts",
    "indexing",
    "corpus",
    "dataset",
    "price_table_date",
    "concurrency",
    "libraries",
    "case_ids",
)


def tag_for(run_id: str, strategy: str) -> str:
    return f"{run_id}_{strategy}"


def preflight_problems(state: dict[str, Any]) -> list[str]:
    """The paid paired evaluation needs a known commit and a clean working tree (ignored files do not count)."""
    if state.get("commit") is None or state.get("tree_clean") is None:
        return ["the git state cannot be read"]
    if not state["tree_clean"]:
        return [
            "the working tree is not clean: commit or stash first, so the manifest names the code that ran"
        ]
    return []


def find_result(results: Path, run_id: str, strategy: str) -> tuple[Path | None, list[str]]:
    """The one result file written by this run's arm. Zero or several matches is a problem, never a guess."""
    if not RUN_ID.fullmatch(run_id):
        return None, [f"run id {run_id!r} must be 8 to 64 letters, digits or underscores"]
    found = sorted(results.glob(f"*_{tag_for(run_id, strategy)}.json"))
    if not found:
        return None, [
            f"no result file for run {run_id} arm {strategy}: the arm failed, was stopped or did not run"
        ]
    if len(found) > 1:
        return None, [
            f"{len(found)} result files match run {run_id} arm {strategy}; expected exactly one"
        ]
    return found[0], []


def load(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a result file")
    return data


def arm_problems(
    data: dict[str, Any],
    strategy: str,
    ids: Sequence[str],
    *,
    run_id: str,
    head: str | None,
) -> list[str]:
    """Why this saved result is not a complete, correctly labelled arm of this run (empty list: it is)."""
    problems: list[str] = []
    manifest = data.get("manifest") or {}
    if data.get("tag") != tag_for(run_id, strategy):
        problems.append(
            f"the result's own tag is {data.get('tag')!r}, not this run's {tag_for(run_id, strategy)!r}"
        )
    if head is None or manifest.get("commit") != head:
        problems.append("the result was produced by a different commit than the current HEAD")
    if manifest.get("tree_clean") is not True:
        problems.append("the result was produced from a working tree that was not clean")
    declared = manifest.get("retrieval_strategy") or {}
    if declared != {"label": strategy, "selected_explicitly": True}:
        problems.append(
            f"manifest strategy is {declared!r}, expected {strategy!r} selected explicitly"
        )
    if (manifest.get("settings") or {}).get(FLAG) is not LABELS[strategy]:
        problems.append(f"manifest setting {FLAG} does not match {strategy}")
    if data.get("pipeline") != "tool_agent":
        problems.append(f"pipeline is {data.get('pipeline')!r}, not tool_agent")
    recorded = manifest.get("case_ids")
    run_ids = [r.get("id") for r in data.get("rows", [])]
    # The run keeps the dataset's order, not the order of --ids: compare as sets, rows against the manifest.
    if (
        not isinstance(recorded, list)
        or sorted(recorded) != sorted(ids)
        or run_ids != recorded
        or len(set(run_ids)) != len(run_ids)
    ):
        problems.append("the cases run are not exactly the pilot cases")
    summary = data.get("summary") or {}
    if summary.get("incomplete") or summary.get("cap_stopped"):
        problems.append("the run was stopped by the spend cap (incomplete)")
    bad = [str(r.get("id")) for r in data.get("rows", []) if r.get("error") or r.get("cap_stopped")]
    if bad:
        problems.append(
            f"{len(bad)} case(s) ended in an error or were cap-stopped: {', '.join(bad)}"
        )
    if any(r.get("accounting") is None for r in data.get("rows", [])):
        problems.append("a row has no accounting")
    return problems


def _saw_evidence(trace: dict[str, Any]) -> bool:
    """Did any search or tool call of the case return chunks? Only then the agent has evidence to check against."""
    if any(search.get("chunks") for search in trace.get("searches") or []):
        return True
    return any(
        (call.get("result") or {}).get("chunk_ids") for call in trace.get("tool_calls") or []
    )


def claim_trace_problems(data: dict[str, Any]) -> list[str]:
    """Are the claim-check diagnostics there where a check must have run? (``--require-claim-trace``)

    A row is expected to hold at least one record when it finished a tool-agent run (``COMPLETED``) after the
    agent retrieved chunks and the claim check was enabled: the graph checks every final answer that has evidence.
    A row without evidence, a run that ended in a failure or by the intent gate, a cap-stopped row, and a disabled
    check are legitimate without records. A record whose outcome is ``unchecked`` (skipped or failed open) is
    legitimate when it says why; a record with no outcome never finished. Messages name case ids only.
    """
    problems: list[str] = []
    if (data.get("diagnostics") or {}).get("claim_check_trace") is not True:
        return ["the result was written without --trace-claim-check: no claim-check diagnostics"]
    enabled = (data.get("manifest", {}).get("settings") or {}).get("claim_check_enabled", True)
    for row in data.get("rows", []):
        if row.get("cap_stopped") or row.get("trace") is None:
            continue
        case = str(row.get("id"))
        trace = row["trace"]
        if "claim_checks" not in trace:
            problems.append(f"case {case}: the trace has no claim_checks block")
            continue
        records = trace["claim_checks"]
        execution = row.get("execution") or {}
        expected = (
            enabled
            and execution.get("path") == "tool_agent"
            and execution.get("outcome") == "COMPLETED"
            and _saw_evidence(trace)
        )
        if expected and not records:
            problems.append(
                f"case {case}: evidence was retrieved but there is no claim-check record"
            )
        for record in records:
            outcome = record.get("outcome") or {}
            if not outcome.get("result"):
                problems.append(
                    f"case {case}: claim-check record {record.get('index')} is incomplete"
                )
            elif outcome.get("result") == "unchecked" and not outcome.get("fail_open_reason"):
                problems.append(f"case {case}: an unchecked record gives no fail_open_reason")
    return problems


def pair_problems(a: dict[str, Any], c2: dict[str, Any]) -> list[str]:
    """Why the two arms are not a fair pair."""
    ma, mc = a.get("manifest") or {}, c2.get("manifest") or {}
    problems = [
        f"manifest {key} differs between the arms"
        for key in SAME_IN_BOTH_ARMS
        if ma.get(key) != mc.get(key)
    ]
    sa, sc = ma.get("settings") or {}, mc.get("settings") or {}
    differing = sorted(k for k in {*sa, *sc} if sa.get(k) != sc.get(k))
    if differing != [FLAG]:
        problems.append(f"settings differ in {differing}, expected only [{FLAG!r}]")
    if a.get("model") != c2.get("model"):
        problems.append("chat model differs between the arms")
    if not (str(a.get("started")) < str(c2.get("started"))):
        problems.append("arm C2-cap3 did not start after arm A")
    return problems


def report(problems: list[str]) -> int:
    for problem in problems:
        print(f"PILOT GATE: {problem}", file=sys.stderr)
    print("PILOT GATE: ok" if not problems else "PILOT GATE: STOP, do not continue")
    return 1 if problems else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--preflight", action="store_true", help="check git: known commit, clean tree"
    )
    parser.add_argument(
        "--run-id", help="the unique id of this paired evaluation (also the --tag prefix)"
    )
    parser.add_argument("--strategy", choices=sorted(LABELS))
    parser.add_argument("--ids", nargs="*", default=[])
    parser.add_argument(
        "--pair",
        action="store_true",
        help="check both arms of the run and that they are a fair pair",
    )
    parser.add_argument(
        "--require-claim-trace",
        action="store_true",
        help="also require the claim-check diagnostics (the run used --trace-claim-check) where a check must have run",
    )
    parser.add_argument("--results-dir", type=Path, default=RESULTS)
    args = parser.parse_args(argv)
    state = git_state()
    if args.preflight:
        problems = preflight_problems(state)
        if (
            args.run_id
        ):  # a reused run id would leave two files for one arm, found only after the spend
            if not RUN_ID.fullmatch(args.run_id):
                problems.append(
                    f"run id {args.run_id!r} must be 8 to 64 letters, digits or underscores"
                )
            elif any(args.results_dir.glob(f"*_{args.run_id}_*.json")):
                problems.append(
                    f"result files for run id {args.run_id} already exist: use a new run id"
                )
        return report(problems)
    if not args.run_id:
        parser.error("--run-id is required")
    head = state.get("commit")
    if args.pair and args.require_claim_trace:
        parser.error("--require-claim-trace checks one arm: use it with --strategy, not --pair")
    if args.pair:
        if not args.ids:
            parser.error("--pair needs --ids")
        paths, problems = {}, preflight_problems(state)
        for strategy in LABELS:
            path, found = find_result(args.results_dir, args.run_id, strategy)
            problems += found
            if path is not None:
                paths[strategy] = load(path)
                problems += arm_problems(
                    paths[strategy], strategy, args.ids, run_id=args.run_id, head=head
                )
        if len(paths) == len(LABELS):
            problems += pair_problems(paths["A"], paths["C2-cap3"])
        return report(problems)
    if not args.strategy or not args.ids:
        parser.error("give --strategy and --ids")
    path, problems = find_result(args.results_dir, args.run_id, args.strategy)
    if path is not None:
        problems += preflight_problems(state)
        data = load(path)
        problems += arm_problems(data, args.strategy, args.ids, run_id=args.run_id, head=head)
        if args.require_claim_trace:
            problems += claim_trace_problems(data)
    return report(problems)


if __name__ == "__main__":
    raise SystemExit(main())
