"""Offline rule routing baseline: python -m evaluation.routing_runner."""

import argparse
from datetime import datetime, UTC
import hashlib
import json
from pathlib import Path
import subprocess
import uuid
from typing import Any

from evaluation.routing_baseline import observe_rules
from evaluation.routing_dataset import load_routing_dataset
from evaluation.routing_metrics import score_routing

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = BACKEND_ROOT / "evaluation/datasets/routing_v1.json"
DEFAULT_OUTPUT = BACKEND_ROOT / "evaluation/results"


def git_output(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=BACKEND_ROOT, text=True).strip()


def run_routing(dataset_path: Path, output_dir: Path) -> tuple[dict[str, Any], Path]:
    dataset = load_routing_dataset(dataset_path)
    observations = [observe_rules(case) for case in dataset.cases]
    timestamp = datetime.now(UTC)
    result = {
        "artifact_version": "routing-baseline-1.0",
        "timestamp": timestamp.isoformat(),
        "git_revision": git_output("rev-parse", "HEAD"),
        "git_branch": git_output("branch", "--show-current"),
        "git_dirty": bool(git_output("status", "--porcelain")),
        "dataset_id": dataset.dataset_id,
        "dataset_version": dataset.schema_version,
        "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "case_count": dataset.case_count,
        "adapter": "legacy-first-pass-rules-v1",
        "source_sha256": {
            str(path.relative_to(BACKEND_ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in [
                *sorted((BACKEND_ROOT / "app/routing").glob("*.py")),
                *sorted((BACKEND_ROOT / "evaluation").glob("routing_*.py")),
                BACKEND_ROOT / "app/retrieval/query_router.py",
                BACKEND_ROOT / "app/retrieval/conversation_intent.py",
                BACKEND_ROOT / "app/retrieval/filename_targets.py",
                BACKEND_ROOT / "app/services/conversation_history.py",
            ]
        },
        "metrics": score_routing(dataset.cases, observations),
        "cases": [
            {
                "id": case.id,
                "gold": case.model_dump(mode="json"),
                "prediction": prediction.model_dump(mode="json"),
                "single_route_correct": (
                    prediction.rule_route == case.expected_requests[0].capability
                    if case.expected_mode.value == "SINGLE"
                    else None
                ),
            }
            for case, prediction in zip(dataset.cases, observations, strict=True)
        ],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / (
        f"routing_v1_rules_{timestamp.strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}.json"
    )
    with destination.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result, destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result, destination = run_routing(args.dataset, args.output_dir)
    metrics = result["metrics"]
    print(
        f"Cases: {result['case_count']} | SINGLE routes: "
        f"{metrics['single_correct']}/{metrics['single_count']} | "
        f"Compound omissions: {metrics['compound_omitted_operations']}/"
        f"{metrics['compound_expected_operations']} | "
        f"Clarification miss rate: {metrics['clarification_miss_rate']}"
    )
    print(f"Artifact: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
