"""Fresh or checkpoint-resumed TypeSafe measurement; explicit opt-in, no retries."""

import argparse
import asyncio
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any
import uuid

from app.routing.providers.typesafe import TypeSafeJevRouter, TypeSafeSettings
from app.routing.providers.jev_criteria import CRITERIA_VERSION, CONTEXT_VERSION, questions
from app.routing.semantic import ProviderObservation, SemanticRouter
from evaluation.jev_cache import FROZEN_HASH, QUESTION_SCHEMA_VERSION, criteria_hash, input_for
from evaluation.jev_runner import frozen_cases
from evaluation.routing_runner import DEFAULT_DATASET, DEFAULT_OUTPUT, BACKEND_ROOT, git_output
from evaluation.typesafe_runner import identity
from evaluation.typesafe_analysis import analysis
from evaluation.typesafe_replay import replay_checkpoint
from app.routing.providers.probability_validation import VALIDATION_VERSION

EXPECTED_CRITERIA_HASH = "0ead6ccaaa4a749753ecacff937b1ef9611859fb832de7558228108e1b0f6a10"
SOURCE_FILES = [
    *sorted((BACKEND_ROOT / "app/routing").rglob("*.py")),
    BACKEND_ROOT / "evaluation/jev_metrics.py",
    BACKEND_ROOT / "evaluation/routing_metrics.py",
    BACKEND_ROOT / "evaluation/typesafe_analysis.py",
    BACKEND_ROOT / "evaluation/typesafe_full.py",
    BACKEND_ROOT / "evaluation/typesafe_replay.py",
    BACKEND_ROOT / "evaluation/routing_dataset.py",
    BACKEND_ROOT / "evaluation/datasets/routing_v1.json",
]


def hashes() -> dict[str, str]:
    return {
        str(p.relative_to(BACKEND_ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in SOURCE_FILES
    }


def preflight(settings: TypeSafeSettings) -> dict[str, Any]:
    cases = frozen_cases(DEFAULT_DATASET)
    if (
        git_output("branch", "--show-current") != "experiment/jev-router"
        or criteria_hash() != EXPECTED_CRITERIA_HASH
        or CRITERIA_VERSION != "jev-routing-criteria-v1"
        or CONTEXT_VERSION != "bounded-history-v1"
        or QUESTION_SCHEMA_VERSION != "jev-routing-questions-1.0"
        or len(questions()) != 11
        or len(cases) != 120
        or settings.typesafe_base_url != "https://api.typesafe.ai"
        or settings.typesafe_model != "jev-latest"
        or git_output("diff", "--name-only", "HEAD")
    ):
        raise ValueError("Frozen identity or production-tree mismatch")
    return {
        "dataset_sha256": FROZEN_HASH,
        "criteria_hash": criteria_hash(),
        "criteria_version": CRITERIA_VERSION,
        "question_schema_version": QUESTION_SCHEMA_VERSION,
        "question_count": 11,
        "context_version": CONTEXT_VERSION,
        "source_hashes": hashes(),
        "provider": "api.typesafe.ai",
        "requested_model": "jev-latest",
        "base_url": settings.typesafe_base_url,
        "key_configured": bool(settings.typesafe_api_key.get_secret_value().strip()),
        "git_revision": git_output("rev-parse", "HEAD"),
        "git_dirty": bool(git_output("status", "--porcelain")),
        "case_count": 120,
        "fresh": True,
        "maximum_posts": 120,
    }


def acceptable_checkpoint(observation: dict[str, Any], allow_structural_invalid: bool) -> bool:
    """Execution policy only: never repair a contradictory semantic prediction."""
    return observation["status"] == "SUCCESS" or bool(
        allow_structural_invalid
        and observation["status"] == "INVALID_RESPONSE"
        and observation.get("http_status") == 200
        and observation.get("model_version") == "jev-1.13.0"
        and observation.get("provenance", {}).get("validation_stage") == "assembly"
        and observation.get("provenance", {}).get("validation_error_code")
        in {"OPERATION_SLOT_REQUIRED", "CLARIFICATION_REASON_REQUIRED"}
    )


async def run_full(
    settings: TypeSafeSettings,
    output: Path,
    router: SemanticRouter | None = None,
    resume_from: Path | None = None,
    allow_structural_invalid: bool = False,
) -> tuple[dict[str, Any], Path]:
    frozen = preflight(settings)
    cases = frozen_cases(DEFAULT_DATASET)
    provider = router or TypeSafeJevRouter(settings)
    records = replay_checkpoint(resume_from, settings) if resume_from else []
    if any(not acceptable_checkpoint(r["observation"], allow_structural_invalid) for r in records):
        raise ValueError("Retained response remains invalid; stop before POST")
    reused = len(records)
    frozen.update(
        fresh=not bool(resume_from),
        reused_existing=reused,
        maximum_posts=len(cases) - reused,
        validation_version=VALIDATION_VERSION,
        allow_structural_invalid=allow_structural_invalid,
    )
    observations = [ProviderObservation.model_validate(r["observation"]) for r in records]
    run_id = uuid.uuid4().hex
    output.mkdir(parents=True, exist_ok=True)
    journal = output / f"typesafe_full_{run_id}.jsonl"
    artifact = output / f"typesafe_full_{run_id}.json"
    started = datetime.now(UTC).isoformat()
    # Immutable source fingerprints are checked before every call. No automatic retry.
    with journal.open("x") as handle:
        for retained in records:
            handle.write(json.dumps(retained, sort_keys=True) + "\n")
        handle.flush()
        for case in cases[reused:]:
            if hashes() != frozen["source_hashes"]:
                raise ValueError("Infrastructure changed during measurement; stop")
            obs = await provider.route(input_for(case), idempotency_key="unused-native-typesafe")
            observations.append(obs)
            record: dict[str, Any] = {
                "id": case.id,
                "identity": identity(case, settings),
                "gold": case.model_dump(mode="json"),
                "fresh": True,
                "observation": obs.model_dump(mode="json"),
            }
            records.append(record)
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
            if len(records) % 10 == 0 or obs.status.value != "SUCCESS":
                print(f"Progress {len(records)}/120: {case.id} {obs.status.value}", flush=True)
            if obs.provider != "api.typesafe.ai" or obs.model != "jev-latest":
                raise ValueError("Wrong provider identity; stop")
            if not acceptable_checkpoint(record["observation"], allow_structural_invalid):
                raise ValueError(
                    "Provider/infrastructure failure checkpointed; stop before next POST"
                )
            await asyncio.sleep(1.1)
    if hashes() != frozen["source_hashes"]:
        raise ValueError("Infrastructure changed during measurement; stop")
    report = analysis(cases, observations)
    result = {
        "artifact_version": "typesafe-full-1.0",
        "validation_version": VALIDATION_VERSION,
        "run_id": run_id,
        "started_at": started,
        "finished_at": datetime.now(UTC).isoformat(),
        "preflight": frozen,
        "cases": records,
        "analysis": report,
        "operational": {
            "http_requests": sum(
                o.post_attempts + o.status_get_attempts for o in observations[reused:]
            ),
            "post_attempts": sum(o.post_attempts for o in observations[reused:]),
            "reused_observations": reused,
            "reused_existing": reused,
            "new_decisions": len(observations) - reused,
            "new_model_decisions": sum(o.new_model_decisions or 0 for o in observations[reused:]),
            "unknown_decision_outcomes": sum(
                o.new_model_decisions is None for o in observations[reused:]
            ),
            "resolved_models": sorted({o.model_version for o in observations if o.model_version}),
            "max_latency_ms": max(o.latency_ms for o in observations),
        },
        "cost_policy": {
            "usd_per_million_input_tokens": 0.042,
            "pricing_source": "https://docs.typesafe.ai/models",
            "estimate_usd": report["core"]["usage"]["input_tokens"] * 0.042 / 1000000
            if report["core"]["usage"]["input_tokens"] is not None
            else None,
            "note": "List-price estimate on reported input usage, not an invoice; missing usage makes this incomplete.",
        },
    }
    with artifact.open("x") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
    return result, artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-typesafe", action="store_true")
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Required for live measurement; ignores all smoke/cache observations",
    )
    parser.add_argument("--resume-from", type=Path)
    parser.add_argument(
        "--allow-structural-invalid",
        action="store_true",
        help="Preserve measured assembly contradictions without retrying them",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        settings = TypeSafeSettings()
        manifest = preflight(settings)
        if args.resume_from:
            retained = replay_checkpoint(args.resume_from, settings)
            if any(
                not acceptable_checkpoint(r["observation"], args.allow_structural_invalid)
                for r in retained
            ):
                raise ValueError("Retained response remains invalid")
            manifest.update(
                fresh=False,
                reused_existing=len(retained),
                maximum_posts=120 - len(retained),
                next_case=frozen_cases(DEFAULT_DATASET)[len(retained)].id
                if len(retained) < 120
                else None,
            )
        print(json.dumps(manifest), flush=True)
        if not args.execute_typesafe:
            print("Preflight only: zero API calls.")
            return 0
        if args.fresh == bool(args.resume_from) or not manifest["key_configured"]:
            print(
                "Live run requires exactly one of --fresh/--resume-from and configured TYPESAFE_API_KEY."
            )
            return 2
        _, path = asyncio.run(
            run_full(
                settings,
                args.output_dir,
                resume_from=args.resume_from,
                allow_structural_invalid=args.allow_structural_invalid,
            )
        )
        print(f"Full artifact: {path}", flush=True)
        return 0
    except (ValueError, OSError):
        print(
            "Full-run preflight/infrastructure failure; stopped without retries. Inspect checkpoint journal.",
            flush=True,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
