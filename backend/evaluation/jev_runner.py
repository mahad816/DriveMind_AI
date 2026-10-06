"""Explicit opt-in native Jev shadow evaluation with frozen gold and smoke gate."""

import argparse
import asyncio
from datetime import datetime, UTC
import hashlib
import json
from pathlib import Path
from typing import Any
import uuid

from app.routing.providers.jev import JevRouter, JevSettings, idempotency_key
from app.routing.providers.jev_criteria import CRITERIA_VERSION, CONTEXT_VERSION, questions
from app.routing.semantic import ObservationStatus, ProviderObservation
from evaluation.jev_metrics import exact_correct, score_jev
from evaluation.jev_cache import (
    FROZEN_HASH,
    QUESTION_SCHEMA_VERSION,
    case_identity,
    criteria_hash,
    find_reusable,
    input_for,
)
from evaluation.routing_baseline import observe_rules
from evaluation.routing_dataset import RoutingCase, load_routing_dataset
from evaluation.routing_metrics import score_routing
from evaluation.routing_runner import DEFAULT_DATASET, DEFAULT_OUTPUT, git_output

SMOKE_IDS = (
    "routing-001",
    "routing-019",
    "routing-039",
    "routing-051",
    "routing-071",
    "routing-101",
)


def frozen_cases(path: Path) -> list[RoutingCase]:
    if hashlib.sha256(path.read_bytes()).hexdigest() != FROZEN_HASH:
        raise ValueError("Frozen dataset hash mismatch")
    return load_routing_dataset(path).cases


def smoke_cache(path: Path, settings: JevSettings) -> dict[str, ProviderObservation]:
    raw = json.loads(path.read_text())
    if raw.get("stage") != "smoke":
        raise ValueError("Smoke artifact stage mismatch")
    cases = [c for c in frozen_cases(DEFAULT_DATASET) if c.id in SMOKE_IDS]
    cached = find_reusable(path.parent, cases, settings, paths=[path])
    if set(cached) != set(SMOKE_IDS):
        raise ValueError("Smoke observations must all validate")
    if len({o.model_version for o in cached.values()}) != 1:
        raise ValueError("Smoke model versions differ")
    return cached


async def execute(
    cases: list[RoutingCase],
    settings: JevSettings,
    *,
    stage: str,
    cache: dict[str, ProviderObservation] | None = None,
    router: JevRouter | None = None,
    spacing_seconds: float = 1.1,
) -> dict[str, Any]:
    provider = router or JevRouter(settings)
    cached = cache or {}
    results: list[ProviderObservation] = []
    completed: list[RoutingCase] = []
    new_calls = post_attempts = status_get_attempts = recovered_requests = unknown_decisions = 0
    versions = {o.model_version for o in cached.values()}
    stopped = None
    for case in cases:
        reused = case.id in cached
        if reused:
            obs = cached[case.id]
        else:
            obs = await provider.route(
                input_for(case),
                idempotency_key=idempotency_key(
                    "routing-1.0:" + FROZEN_HASH, case.id, settings.jev_model, input_for(case)
                ),
            )
            post_attempts += obs.post_attempts
            status_get_attempts += obs.status_get_attempts
            recovered_requests += obs.recovered_idempotent
            if obs.new_model_decisions is None:
                unknown_decisions += 1
            else:
                new_calls += obs.new_model_decisions
        results.append(obs)
        completed.append(case)
        if obs.model_version:
            versions.add(obs.model_version)
        # Stop on any provider/assembly problem: never spend through a broken contract.
        if obs.status == ObservationStatus.INVALID_RESPONSE:
            stopped = "invalid_response"
            break
        if obs.status == ObservationStatus.IDEMPOTENCY_CONFLICT:
            stopped = (
                "idempotency_body_mismatch"
                if obs.idempotency_error == "idempotency_key_reused"
                else "idempotency_conflict_unresolved"
            )
            break
        if obs.status != ObservationStatus.SUCCESS:
            stopped = "provider_failure"
            break
        if len(versions) > 1:
            stopped = "model_drift"
            break
        if not reused and spacing_seconds:
            await asyncio.sleep(spacing_seconds)
    baseline = [observe_rules(c) for c in completed]
    comparison = []
    for case, rule, obs in zip(completed, baseline, results, strict=True):
        rule_ok = (
            case.expected_mode.value == "SINGLE"
            and rule.rule_route == case.expected_requests[0].capability
        )
        jev_ok = bool(
            obs.prediction
            and obs.status == ObservationStatus.SUCCESS
            and case.expected_mode.value == "SINGLE"
            and obs.prediction.mode.value == "SINGLE"
            and len(obs.prediction.requests) == 1
            and obs.prediction.requests[0].capability == case.expected_requests[0].capability
        )
        comparison.append(
            {
                "id": case.id,
                "single_route_comparison": (
                    "both_win"
                    if rule_ok and jev_ok
                    else "rule_win"
                    if rule_ok
                    else "jev_win"
                    if jev_ok
                    else "both_fail"
                )
                if case.expected_mode.value == "SINGLE"
                else None,
                "jev_exact_labels_correct": exact_correct(case, obs),
            }
        )
    return {
        "artifact_version": "jev-shadow-1.1",
        "stage": stage,
        "timestamp": datetime.now(UTC).isoformat(),
        "git_revision": git_output("rev-parse", "HEAD"),
        "git_dirty": bool(git_output("status", "--porcelain")),
        "dataset_sha256": FROZEN_HASH,
        "dataset_version": "routing-1.0",
        "criteria_version": CRITERIA_VERSION,
        "criteria_hash": criteria_hash(),
        "context_version": CONTEXT_VERSION,
        "question_schema_version": QUESTION_SCHEMA_VERSION,
        "model": settings.jev_model,
        "base_url": settings.jev_base_url,
        "timeout_seconds": settings.jev_timeout_seconds,
        "case_count": len(completed),
        "planned_case_count": len(cases),
        "stopped_reason": stopped,
        "stopped_observation_status": results[-1].status.value if stopped else None,
        "new_calls": new_calls,
        "new_model_decisions": new_calls,
        "post_attempts": post_attempts,
        "status_get_attempts": status_get_attempts,
        "recovered_idempotent_requests": recovered_requests,
        "unknown_model_decision_outcomes": unknown_decisions,
        "reused_artifact_observations": sum(c.id in cached for c in completed),
        "reused_observations": sum(c.id in cached for c in completed),
        "rule_metrics": score_routing(completed, baseline),
        "jev_metrics": score_jev(completed, results),
        "comparison": comparison,
        "cases": [
            {
                "id": c.id,
                "gold": c.model_dump(mode="json"),
                "identity": case_identity(c, settings),
                "rule": r.model_dump(mode="json"),
                "jev": o.model_dump(mode="json"),
            }
            for c, r, o in zip(completed, baseline, results, strict=True)
        ],
    }


def write_artifact(result: dict[str, Any], output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    path = output / f"jev_shadow_{result['stage']}_{uuid.uuid4().hex}.json"
    with path.open("x") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-jev", action="store_true")
    parser.add_argument("--stage", choices=("smoke", "full"), default="smoke")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--smoke-artifact", type=Path)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        settings = JevSettings()
        cases = frozen_cases(args.dataset)
        if args.stage == "smoke":
            cases = [c for c in cases if c.id in SMOKE_IDS]
        if args.limit is not None:
            if not 1 <= args.limit <= len(cases):
                raise ValueError("Invalid case limit")
            cases = cases[: args.limit]
        cache = find_reusable(args.output_dir, cases, settings)
        key_present = bool(settings.jev_api_key.get_secret_value().strip())
        print(
            json.dumps(
                {
                    "stage": args.stage,
                    "planned_cases": [c.id for c in cases],
                    "maximum_post_calls": len(cases) - len(cache),
                    "reusable_observations": len(cache),
                    "question_count": len(questions()),
                    "model": settings.jev_model,
                    "key_configured": key_present,
                    "execute": args.execute_jev,
                    "maximum_credit_fallback": len(cases) - len(cache),
                }
            )
        )
        if not args.execute_jev:
            print("Dry run: zero external calls. Use --execute-jev to opt in.")
            return 0
        if not key_present:
            print("JEV_API_KEY absent: no external calls. Configure it server-side, never in chat.")
            return 2
        if args.stage == "full":
            if args.smoke_artifact is None:
                raise ValueError("Full evaluation requires a validated smoke artifact")
            cache.update(smoke_cache(args.smoke_artifact, settings))
        result = asyncio.run(execute(cases, settings, stage=args.stage, cache=cache))
        path = write_artifact(result, args.output_dir)
        print(
            f"Artifact: {path}; new calls: {result['new_calls']}; stopped: {result['stopped_reason']}"
        )
        return 0 if result["stopped_reason"] is None else 1
    except (ValueError, OSError):
        # Configuration errors may contain secret input; never print exception text.
        print("Preflight failed: check configuration, frozen dataset, limit, and smoke artifact.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
