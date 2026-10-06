"""Development-only coverage evaluation. No held-out flag or semantic retries."""

import argparse
import asyncio
import json
import os
import subprocess
from collections import Counter
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

import httpx

from app.routing.providers.typesafe import TypeSafeSettings
from app.routing.v2.contracts import digest
from app.routing.v2.coverage import CoverageResult
from app.routing.v2.coverage.contracts import contract_identity, verify_lock
from app.routing.v2.coverage.providers.typesafe_coverage import (
    TypeSafeCoverageVerifier,
    parse_response,
)
from evaluation.coverage_dataset import CoverageCase, ROOT, load, sha

DATASET_SHA = "e1100fff7923a13bc831fb1940f9eb39b2a172cbc82b22c53c30a9ce2c67f888"
FIXTURE_SHA = "de9bdd210a5615d1e4b81444d450031024aec64fd92adacbbc4f64309f399082"
CONTRACT = "0bd05c2d48990bbb0defb031f2804a5422be697b1379b928069de419f57fd3dd"
TARGETS = {
    "false_preserved_max": 0,
    "gold_non_preserved_count": 18,
    "preserved_recall_min": 0.90,
    "gold_preserved_count": 14,
    "http_success_min": 1.0,
    "valid_response_min": 1.0,
    "structural_invalid_max": 0,
}


def save(path: Path, data: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w") as handle:
        handle.write(json.dumps(data, ensure_ascii=False, indent=2))
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def preflight() -> tuple[tuple[CoverageCase, ...], dict[str, Any]]:
    if (
        subprocess.check_output(["git", "branch", "--show-current"], text=True).strip()
        != "experiment/jev-router"
    ):
        raise ValueError("BRANCH_MISMATCH")
    if (
        sha(ROOT / "coverage_v1.json") != DATASET_SHA
        or sha(ROOT / "coverage_v1_fixtures.json") != FIXTURE_SHA
        or not verify_lock()
        or contract_identity() != CONTRACT
    ):
        raise ValueError("FROZEN_IDENTITY_MISMATCH")
    dataset, _ = load()
    development = tuple(c for c in dataset.cases if c.split == "development")
    if len(development) != 32 or Counter(c.expected_verdict.value for c in development) != {
        "PRESERVED": 14,
        "MISMATCH": 18,
    }:
        raise ValueError("DEVELOPMENT_COUNTS_MISMATCH")
    settings = TypeSafeSettings()
    if (
        settings.typesafe_base_url != "https://api.typesafe.ai"
        or settings.typesafe_model != "jev-latest"
    ):
        raise ValueError("PROVIDER_MISMATCH")
    identities = [{"case_id": c.id, "input_identity": c.input.input_identity} for c in development]
    info = {
        "dataset_sha256": DATASET_SHA,
        "fixture_sha256": FIXTURE_SHA,
        "coverage_contract_identity": CONTRACT,
        "split": "development",
        "case_count": 32,
        "gold_counts": {"PRESERVED": 14, "MISMATCH": 18, "UNCERTAIN": 0},
        "targets": TARGETS,
        "provider": "https://api.typesafe.ai/v1/systemone",
        "model": "jev-latest",
        "key_configured": bool(settings.typesafe_api_key.get_secret_value().strip()),
        "cases": identities,
    }
    return development, info


def call_identity(case: CoverageCase, run_identity: str) -> str:
    if case.split != "development":
        raise ValueError("HELD_OUT_FORBIDDEN")
    return digest(
        {
            "run": run_identity,
            "case_id": case.id,
            "split": case.split,
            "input_identity": case.input.input_identity,
            "interpretation_identity": case.input.interpretation_identity,
            "context_identity": case.input.context_identity,
            "contract_identity": CONTRACT,
            "provider": "typesafe-direct",
            "model": "jev-latest",
        }
    )


def revalidate_cached(record: dict[str, Any], case: CoverageCase, identity: str) -> CoverageResult:
    if (
        record["call_identity"] != identity
        or record["observation_identity"] != digest(record["result"])
        or record["case_id"] != case.id
        or record["split"] != "development"
    ):
        raise ValueError("CHECKPOINT_CORRUPTION_OR_MISMATCH")
    result = CoverageResult.model_validate(record["result"])
    if (
        result.input_identity,
        result.interpretation_identity,
        result.context_identity,
        result.contract_identity,
    ) != (
        case.input.input_identity,
        case.input.interpretation_identity,
        case.input.context_identity,
        CONTRACT,
    ):
        raise ValueError("CHECKPOINT_INPUT_MISMATCH")
    observation = result.observation
    if observation.status != "SUCCESS" or observation.http_status != 200:
        raise ValueError("FAILED_OBSERVATION_NOT_AUTOMATICALLY_RESUBMITTED")
    body = {
        "model": observation.returned_model,
        "usage": observation.usage.model_dump(),
        "answers": {
            "COVERAGE": {
                "type": "choice",
                "choice": observation.selected,
                "confidence": observation.confidence,
                "probabilities": {
                    p.verdict.value: p.probability for p in observation.probabilities
                },
            }
        },
    }
    parsed = parse_response(
        body,
        identity=CONTRACT,
        http_status=observation.http_status,
        latency_ms=observation.latency_ms,
    )
    if parsed != observation:
        raise ValueError("CHECKPOINT_REVALIDATION_FAILED")
    return result


async def evaluate_case(
    verifier: TypeSafeCoverageVerifier, case: CoverageCase, directory: Path, run_identity: str
) -> tuple[dict[str, Any], bool]:
    identity = call_identity(case, run_identity)
    path = directory / (case.id + ".json")
    pending = directory / (case.id + ".pending.json")
    if path.exists():
        record = json.loads(path.read_text())
        revalidate_cached(record, case, identity)
        return record, True
    if pending.exists():
        raise ValueError("UNRESOLVED_POST_OUTCOME_NO_RESUBMISSION")
    save(pending, {"case_id": case.id, "split": "development", "call_identity": identity})
    result = await verifier.verify(case.input, execute=True)
    record = {
        "case_id": case.id,
        "split": "development",
        "call_identity": identity,
        "input_identity": case.input.input_identity,
        "observation_identity": digest(result.model_dump(mode="json")),
        "result": result.model_dump(mode="json"),
        "selected_probability": result.observation.selected_probability,
        "top_two_margin": result.observation.top_two_margin,
        "gold": case.expected_verdict.value,
        "family": case.family,
        "source_routing_case": case.source_routing_case,
        "original_question": case.input.original_question,
        "proposed_interpretation": case.input.interpretation.model_dump(mode="json"),
    }
    save(path, record)
    return record, False


async def run(execute: bool = False, resume: Path | None = None) -> Path | None:
    cases, info = preflight()
    run_identity = digest({k: v for k, v in info.items() if k != "key_configured"})
    print(json.dumps({k: v for k, v in info.items() if k != "cases"}), flush=True)
    if not execute:
        print("Dry run: ZERO provider calls; held-out execution unavailable.")
        return None
    if not info["key_configured"]:
        raise ValueError("MISSING_TYPESAFE_API_KEY")
    directory = resume or Path(__file__).parent / "results" / (
        "coverage_development_" + uuid4().hex
    )
    if resume:
        if json.loads((directory / "identity.json").read_text())["identity"] != run_identity:
            raise ValueError("RUN_IDENTITY_MISMATCH")
    else:
        directory.mkdir()
        save(directory / "identity.json", {"identity": run_identity, "preflight": info})
    artifact: dict[str, Any] = {
        "preflight": info,
        "cases": [],
        "accounting": {"new_calls": 0, "reused_calls": 0, "held_out_provider_calls": 0},
        "stop_reason": None,
        "started_perf_counter": perf_counter(),
    }
    invalid_probability_count = 0
    async with httpx.AsyncClient(trust_env=False) as client:
        verifier = TypeSafeCoverageVerifier(TypeSafeSettings(), client)
        for case in cases:
            reused = False
            try:
                if (
                    contract_identity() != CONTRACT
                    or sha(ROOT / "coverage_v1.json") != DATASET_SHA
                    or sha(ROOT / "coverage_v1_fixtures.json") != FIXTURE_SHA
                ):
                    raise ValueError("FROZEN_IDENTITY_CHANGED")
                record, reused = await evaluate_case(verifier, case, directory, run_identity)
                artifact["cases"].append(record)
                observation = record["result"]["observation"]
                artifact["accounting"]["reused_calls" if reused else "new_calls"] += (
                    1 if reused else observation["post_attempts"]
                )
                code = observation["error_code"]
                if code == "INVALID_PROBABILITIES":
                    invalid_probability_count += 1
                if (
                    code
                    in {
                        "AUTH_ERROR",
                        "MISSING_KEY",
                        "INVALID_JSON",
                        "INVALID_MODEL",
                        "INVALID_USAGE",
                        "INVALID_ANSWERS",
                        "RESPONSE_TOO_LARGE",
                        "INPUT_IDENTITY_MISMATCH",
                        "CONTRACT_MISMATCH",
                        "REQUEST_TOO_LARGE",
                    }
                    or invalid_probability_count >= 2
                ):
                    artifact["stop_reason"] = code
                print(case.id, record["result"]["verdict"], observation["status"], flush=True)
            except Exception as exc:
                artifact["stop_reason"] = "SYSTEM_ERROR:" + type(exc).__name__
            save(directory / "result.json", artifact)
            if artifact["stop_reason"]:
                break
            if not reused:
                await asyncio.sleep(0.25)
    artifact["elapsed_seconds"] = perf_counter() - artifact.pop("started_perf_counter")
    save(directory / "result.json", artifact)
    print("Artifact:", directory / "result.json", "Stop:", artifact["stop_reason"], flush=True)
    return directory / "result.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-typesafe", action="store_true")
    parser.add_argument("--resume", type=Path)
    args = parser.parse_args()
    asyncio.run(run(args.execute_typesafe, args.resume))


if __name__ == "__main__":
    main()
