"""Frozen synthetic smoke; explicit live opt-in, continuous paid-response journal."""

import argparse
import asyncio
import json
import subprocess
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

import httpx

from app.routing.providers.typesafe import TypeSafeSettings
from app.routing.v2.checkpoints import read_checkpoint, reuse_stage1
from app.routing.v2.contracts import manifest, verify_lock
from app.routing.v2.options import generate_options
from app.routing.v2.preparation import PreparationFailure, prepare
from app.routing.v2.providers.typesafe import TypeSafeV2Router, request_fits
from app.routing.v2.questions import stage1_questions, stage2_questions
from app.routing.v2.resolved import IndexedFile
from app.routing.v2.resolver import resolve
from evaluation.v2_smoke_fixture import SmokeCase, fixture_hash, load_fixtures

FROZEN_HASH = "4922c315c898d97268131465b0160ca8f462accafce76f780122efa2af4ce7f0"
SEMANTIC_ERRORS = {
    "DUPLICATE_OPTION_SELECTION",
    "DUPLICATE_SEMANTIC_PROVENANCE",
    "REQUEST_ORDER_REVERSED",
}


class SyntheticMetadata:
    def __init__(self, case: SmokeCase) -> None:
        self.files = case.metadata

    async def list_visible_indexed_files(self, user_id: UUID) -> tuple[IndexedFile, ...]:
        return tuple(f for f in self.files if f.user_id == user_id)


def preflight() -> dict[str, Any]:
    branch = subprocess.check_output(["git", "branch", "--show-current"], text=True).strip()
    if branch != "experiment/jev-router" or not verify_lock() or fixture_hash() != FROZEN_HASH:
        raise ValueError("branch/contract/fixture integrity failure")
    cases = []
    for case in load_fixtures().cases:
        envelope = prepare(case.question, case.state)
        if isinstance(envelope, PreparationFailure):
            raise ValueError(f"{case.id}: {envelope.reason}")
        registry = generate_options(envelope)
        if isinstance(registry, PreparationFailure):
            raise ValueError(f"{case.id}: {registry.reason}")
        if not request_fits(envelope, stage1_questions()) or any(
            not request_fits(envelope, stage2_questions(registry, n)) for n in (1, 2, 3)
        ):
            raise ValueError(f"{case.id}: request size failure")
        cases.append(
            {
                "id": case.id,
                "envelope_hash": envelope.identity_hash,
                "registry_hash": registry.identity_hash,
                "options": len(registry.options),
            }
        )
    settings = TypeSafeSettings()
    return {
        "branch": branch,
        "fixture_hash": FROZEN_HASH,
        "contract": manifest(),
        "provider": settings.typesafe_base_url,
        "model": settings.typesafe_model,
        "key_configured": bool(settings.typesafe_api_key.get_secret_value().strip()),
        "cases": cases,
        "maximum_posts": 30,
    }


def system_failure(status: str, error: str | None) -> bool:
    return status in {
        "PREPARATION_ERROR",
        "STAGE1_PROVIDER_ERROR",
        "STAGE1_INVALID_RESPONSE",
        "STAGE2_PROVIDER_ERROR",
        "STAGE2_INVALID_RESPONSE",
        "BINDING_VALIDATION_ERROR",
    } or (status == "DOMAIN_TRANSLATION_ERROR" and error not in SEMANTIC_ERRORS)


async def run(execute: bool = False) -> Path | None:
    info = preflight()
    print(json.dumps(info), flush=True)
    if not execute:
        print("Dry run: zero provider calls.")
        return None
    if not info["key_configured"]:
        raise ValueError("Configure TYPESAFE_API_KEY in ignored backend/.env")
    directory = Path(__file__).parent / "results" / ("v2_smoke_" + uuid4().hex)
    directory.mkdir()
    artifact: dict[str, Any] = {"preflight": info, "cases": [], "stop_reason": None}
    path = directory / "result.json"
    async with httpx.AsyncClient(trust_env=False) as client:
        router = TypeSafeV2Router(TypeSafeSettings(), client)
        for case, identity in zip(load_fixtures().cases, info["cases"], strict=True):
            envelope = prepare(case.question, case.state)
            if isinstance(envelope, PreparationFailure):
                raise ValueError("preparation changed after preflight")
            registry = generate_options(envelope)
            if (
                isinstance(registry, PreparationFailure)
                or envelope.identity_hash != identity["envelope_hash"]
                or registry.identity_hash != identity["registry_hash"]
            ):
                raise ValueError("frozen input changed after preflight")
            started = perf_counter()
            result = await router.interpret(
                envelope, execute=True, checkpoint_path=directory / (case.id + ".stage1.json")
            )
            record: dict[str, Any] = {
                "id": case.id,
                "expected": case.model_dump(mode="json"),
                "observation": result.telemetry_record(include_synthetic_domain=True),
                "routing_latency_ms": (perf_counter() - started) * 1000,
                "option_registry": registry.model_dump(mode="json"),
                "prepared_input": envelope.model_dump(mode="json"),
            }
            with (directory / "journal.jsonl").open("a") as journal:
                journal.write(json.dumps(record) + "\n")
            artifact["cases"].append(record)
            path.write_text(json.dumps(artifact, indent=2))
            try:
                if result.stage1_checkpoint:
                    reuse_stage1(
                        envelope, registry, read_checkpoint(directory / (case.id + ".stage1.json"))
                    )
                    record["checkpoint_replay_valid"] = True
                if result.interpretation:
                    resolution = await resolve(
                        result.interpretation,
                        trusted_input=envelope.input,
                        state=case.state,
                        user_id=case.user_id,
                        metadata=SyntheticMetadata(case),
                    )
                    record["resolution"] = resolution.model_dump(mode="json")
                if system_failure(result.status, result.error_code):
                    artifact["stop_reason"] = result.status + ":" + str(result.error_code)
            except Exception as exc:
                artifact["stop_reason"] = "LOCAL_SYSTEM_ERROR:" + type(exc).__name__
            path.write_text(json.dumps(artifact, indent=2))
            print(case.id, result.status, result.error_code, flush=True)
            if artifact["stop_reason"]:
                break
            await asyncio.sleep(1.1)
    print("Artifact:", path)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-typesafe", action="store_true")
    asyncio.run(run(parser.parse_args().execute_typesafe))


if __name__ == "__main__":
    main()
