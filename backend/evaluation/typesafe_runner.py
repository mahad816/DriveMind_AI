"""Six-case direct TypeSafe comparison only; never full benchmark execution."""

import argparse
import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any
import uuid

from app.routing.providers.jev_criteria import CONTEXT_VERSION, CRITERIA_VERSION, questions
from app.routing.providers.typesafe import TypeSafeJevRouter, TypeSafeSettings, validate_typesafe
from app.routing.semantic import ObservationStatus, ProviderObservation, SemanticRouter
from evaluation.jev_cache import (
    FROZEN_HASH,
    QUESTION_SCHEMA_VERSION,
    criteria_hash,
    digest,
    input_for,
    wire_response,
)
from evaluation.jev_metrics import score_jev
from evaluation.jev_runner import SMOKE_IDS, frozen_cases
from evaluation.routing_runner import DEFAULT_DATASET, DEFAULT_OUTPUT, git_output
from evaluation.routing_dataset import RoutingCase


def identity(case: RoutingCase, settings: TypeSafeSettings) -> dict[str, str]:
    return {
        "provider": "api.typesafe.ai",
        "base_url": settings.typesafe_base_url,
        "model": settings.typesafe_model,
        "dataset_hash": FROZEN_HASH,
        "dataset_version": "routing-1.0",
        "criteria_version": CRITERIA_VERSION,
        "criteria_hash": criteria_hash(),
        "context_version": CONTEXT_VERSION,
        "question_schema_version": QUESTION_SCHEMA_VERSION,
        "case_id": case.id,
        "input_hash": digest(input_for(case).model_dump(mode="json")),
    }


def cached_observations(
    directory: Path, cases: list[RoutingCase], settings: TypeSafeSettings
) -> dict[str, ProviderObservation]:
    result: dict[str, ProviderObservation] = {}
    for path in sorted(directory.glob("typesafe_shadow_smoke_*.json")):
        try:
            if path.is_symlink() or path.stat().st_size > 10000000:
                continue
            raw = json.loads(path.read_text())
            if raw.get("artifact_version") != "typesafe-shadow-1.0":
                continue
            for entry in raw["cases"]:
                case = next((c for c in cases if c.id == entry.get("id")), None)
                if case is None or entry.get("identity") != identity(case, settings):
                    continue
                previous = entry["observation"]
                if (
                    previous.get("provider") != "api.typesafe.ai"
                    or previous.get("http_status") != 200
                ):
                    continue
                data = wire_response(previous)
                data["model"] = previous.get("model_version")
                validated = validate_typesafe(data)
                validated["provenance"]["source_artifact"] = path.name
                obs = ProviderObservation(
                    status=ObservationStatus.SUCCESS,
                    provider="api.typesafe.ai",
                    model=settings.typesafe_model,
                    criteria_version=CRITERIA_VERSION,
                    latency_ms=previous["latency_ms"],
                    calls=previous["calls"],
                    http_status=200,
                    **validated,
                )
                result.setdefault(case.id, obs)
        except (ValueError, OSError, KeyError, TypeError, AttributeError):
            continue
    return result


async def run_smoke(
    settings: TypeSafeSettings, output: Path, router: SemanticRouter | None = None
) -> tuple[dict[str, Any], Path]:
    cases = [c for c in frozen_cases(DEFAULT_DATASET) if c.id in SMOKE_IDS]
    cache = cached_observations(output, cases, settings)
    provider = router or TypeSafeJevRouter(settings)
    observations = []
    records: list[dict[str, Any]] = []
    result: dict[str, Any] = {}
    path: Path | None = None
    new_calls = posts = 0
    for case in cases:
        reused = case.id in cache
        obs = (
            cache[case.id]
            if reused
            else await provider.route(
                input_for(case), idempotency_key="unused-typesafe-protocol-parameter"
            )
        )
        observations.append(obs)
        records.append(
            {
                "id": case.id,
                "identity": identity(case, settings),
                "gold": case.model_dump(mode="json"),
                "reused": reused,
                "observation": obs.model_dump(mode="json"),
            }
        )
        if not reused:
            posts += obs.post_attempts
            new_calls += obs.new_model_decisions or 0
        # Persist after every case; interrupted runs need not duplicate paid calls.
        result = {
            "artifact_version": "typesafe-shadow-1.0",
            "timestamp": datetime.now(UTC).isoformat(),
            "git_revision": git_output("rev-parse", "HEAD"),
            "git_dirty": bool(git_output("status", "--porcelain")),
            "provider": "api.typesafe.ai",
            "requested_model": settings.typesafe_model,
            "dataset_sha256": FROZEN_HASH,
            "criteria_version": CRITERIA_VERSION,
            "criteria_hash": criteria_hash(),
            "case_count": len(records),
            "planned_case_count": 6,
            "new_calls": new_calls,
            "post_attempts": posts,
            "reused_observations": sum(r["reused"] for r in records),
            "model_comparison_limitation": "jev-org uses jev-1.13; direct uses jev-latest. Semantic differences cannot be attributed solely to provider path.",
            "metrics": score_jev(cases[: len(records)], observations),
            "cases": records,
        }
        output.mkdir(parents=True, exist_ok=True)
        path = output / f"typesafe_shadow_smoke_{uuid.uuid4().hex}.json"
        with path.open("x") as handle:
            json.dump(result, handle, indent=2, sort_keys=True)
        if obs.status != ObservationStatus.SUCCESS:
            break
        if not reused:
            await asyncio.sleep(1.1)
    if path is None:
        raise ValueError("No smoke cases found")
    return result, path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-typesafe", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        settings = TypeSafeSettings()
        cases = [c for c in frozen_cases(DEFAULT_DATASET) if c.id in SMOKE_IDS]
        cache = cached_observations(args.output_dir, cases, settings)
        has_key = bool(settings.typesafe_api_key.get_secret_value().strip())
        print(
            json.dumps(
                {
                    "model": settings.typesafe_model,
                    "case_ids": list(SMOKE_IDS),
                    "question_count": len(questions()),
                    "key_configured": has_key,
                    "maximum_posts": 6 - len(cache),
                    "reused": len(cache),
                    "execute": args.execute_typesafe,
                }
            )
        )
        if not args.execute_typesafe:
            print("Dry run: zero provider calls.")
            return 0
        if not has_key:
            print("TYPESAFE_API_KEY absent; no calls made.")
            return 2
        result, path = asyncio.run(run_smoke(settings, args.output_dir))
        print(f"Artifact: {path}; cases: {result['case_count']}; new calls: {result['new_calls']}")
        return 0 if result["case_count"] == 6 and not result["metrics"]["errors"] else 1
    except (ValueError, OSError):
        print("TypeSafe preflight failed; inspect configuration. No secret values printed.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
