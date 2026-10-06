"""Frozen held-out evaluation only; explicit opt-in, exact stage reuse, no retries."""

import argparse
import asyncio
import json
import os
import subprocess
from pathlib import Path
from time import perf_counter
from typing import Any, Literal
from uuid import UUID, uuid4

import httpx

from app.routing.providers.typesafe import TypeSafeSettings
from app.routing.v2.checkpoints import read_checkpoint, reuse_stage1
from app.routing.v2.contracts import digest, manifest, verify_lock
from app.routing.v2.observations import StageObservation
from app.routing.v2.options import generate_options, OptionRegistry
from app.routing.v2.preparation import prepare, PreparedEnvelope
from app.routing.v2.providers.typesafe import TypeSafeV2Router
from app.routing.v2.resolved import IndexedFile, ResolutionReport
from app.routing.v2.resolver import resolve
from app.routing.v2.wire import parse_stage
from evaluation.routing_v2_dataset import ROOT, LOCK_SHA, load, sha, validate_gold

DATASET_SHA = "06559a24355c021d1b95fa788d9fbc02702f84ef7b47799205f825dae0c6eaa5"
FIXTURE_SHA = "519c9779cb0c5c4fa47f0744001f56df6a67e41eb6296c285a3fdef9563f9df2"
TARGETS = {
    "structural_invalid_count": 0,
    "cardinality_accuracy_min": 0.95,
    "one_capability_operation_accuracy_min": 0.90,
    "compound_operation_recall_min": 0.90,
    "compound_exact_bundle_accuracy_min": 0.85,
    "supported_unsupported_accuracy_min": 0.90,
    "contextual_resolution_readiness_accuracy_min": 0.90,
    "collection_summary_routing_accuracy_min": 0.90,
    "false_readiness_rejection_rate_max": 0.05,
    "unsafe_ready_count": 0,
    "deterministic_safety_tests_accuracy": 1.0,
}


def save(path: Path, data: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w") as handle:
        handle.write(json.dumps(data, ensure_ascii=False, indent=2))
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


async def preflight() -> dict[str, Any]:
    branch = subprocess.check_output(["git", "branch", "--show-current"], text=True).strip()
    if (
        branch != "experiment/jev-router"
        or not verify_lock()
        or sha(Path("app/routing/v2/CONTRACT_LOCK.json")) != LOCK_SHA
        or sha(ROOT / "routing_v2.json") != DATASET_SHA
        or sha(ROOT / "routing_v2_fixtures.json") != FIXTURE_SHA
    ):
        raise ValueError("FROZEN_IDENTITY_MISMATCH")
    freeze = json.loads((ROOT / "routing_v2_freeze.json").read_text())
    if freeze["acceptance_targets"] != TARGETS:
        raise ValueError("ACCEPTANCE_TARGET_MISMATCH")
    validated = await validate_gold()
    dataset, fixtures = load()
    identities = []
    for case in dataset.cases:
        envelope = prepare(case.question, fixtures.states[case.state_fixture])
        if not isinstance(envelope, PreparedEnvelope):
            raise ValueError("PREPARATION_FAILURE")
        registry = generate_options(envelope)
        if not isinstance(registry, OptionRegistry):
            raise ValueError("OPTION_FAILURE")
        identities.append(
            {"id": case.id, "envelope": envelope.identity_hash, "options": registry.identity_hash}
        )
    settings = TypeSafeSettings()
    if (
        settings.typesafe_base_url != "https://api.typesafe.ai"
        or settings.typesafe_model != "jev-latest"
    ):
        raise ValueError("PROVIDER_CONFIG_MISMATCH")
    return {
        "branch": branch,
        "dataset_sha256": DATASET_SHA,
        "fixture_sha256": FIXTURE_SHA,
        "contract_lock_sha256": LOCK_SHA,
        "contract": manifest(),
        "targets": TARGETS,
        "provider": settings.typesafe_base_url,
        "requested_model": settings.typesafe_model,
        "key_configured": bool(settings.typesafe_api_key.get_secret_value().strip()),
        "gold_validation": validated,
        "cases": identities,
        "maximum_posts": 360,
    }


class JournalRouter(TypeSafeV2Router):
    """Saves each response before adapter translation; unknown paid outcomes block resume."""

    def __init__(
        self,
        settings: TypeSafeSettings,
        client: httpx.AsyncClient,
        directory: Path,
        run_identity: str,
    ) -> None:
        super().__init__(settings, client)
        self.directory = directory
        self.run_identity = run_identity
        self.case_id = ""
        self.accounting = {
            "new_stage1_posts": 0,
            "new_stage2_posts": 0,
            "reused_stage1": 0,
            "reused_stage2": 0,
        }

    async def stage(
        self,
        envelope: PreparedEnvelope,
        questions: dict[str, dict[str, Any]],
        stage: Literal[1, 2],
        *,
        execute: bool,
    ) -> StageObservation:
        identity = digest(
            {
                "run": self.run_identity,
                "case": self.case_id,
                "envelope": envelope.identity_hash,
                "questions": questions,
                "stage": stage,
            }
        )
        path = self.directory / f"{self.case_id}.stage{stage}.response.json"
        pending = self.directory / f"{self.case_id}.stage{stage}.pending.json"
        if path.exists():
            record = json.loads(path.read_text())
            if record["identity"] != identity or record["observation_hash"] != digest(
                record["observation"]
            ):
                raise ValueError("CORRUPTED_OR_INCOMPATIBLE_STAGE_CHECKPOINT")
            observation = StageObservation.model_validate(record["observation"])
            if observation.status == "SUCCESS":
                body = {
                    "model": observation.returned_model,
                    "usage": observation.usage.model_dump(),
                    "answers": {
                        a.answer_id: {
                            "type": "choice",
                            "choice": a.selected,
                            "confidence": a.confidence,
                            "probabilities": a.distribution(),
                        }
                        for a in observation.answers
                    },
                }
                if parse_stage(body, questions, stage).status != "SUCCESS":
                    raise ValueError("STAGE_CHECKPOINT_REVALIDATION_FAILED")
            self.accounting[f"reused_stage{stage}"] += 1
            return observation
        if pending.exists():
            raise ValueError("UNRESOLVED_POST_OUTCOME_NO_AUTOMATIC_RESUBMISSION")
        save(pending, {"identity": identity, "stage": stage})
        self.accounting[f"new_stage{stage}_posts"] += 1
        observation = await super().stage(envelope, questions, stage, execute=execute)
        payload = observation.model_dump(mode="json")
        save(
            path,
            {"identity": identity, "observation": payload, "observation_hash": digest(payload)},
        )
        return observation


async def run(execute: bool = False, resume: Path | None = None) -> Path | None:
    info = await preflight()
    identity = digest({k: v for k, v in info.items() if k != "key_configured"})
    directory = resume or Path(__file__).parent / "results" / ("routing_v2_full_" + uuid4().hex)
    retained_cases = 0
    if resume:
        if json.loads((directory / "identity.json").read_text())["identity"] != identity:
            raise ValueError("RUN_CHECKPOINT_IDENTITY_MISMATCH")
        retained_cases = len(list(directory.glob("v2-*.case.json")))
    print(
        json.dumps(
            {
                "dataset": DATASET_SHA,
                "fixtures": FIXTURE_SHA,
                "contract": LOCK_SHA,
                "provider": info["provider"],
                "model": info["requested_model"],
                "key_configured": info["key_configured"],
                "validated_cases": 180,
                "retained_cases": retained_cases,
                "new_calls_so_far": 0,
                "maximum_posts": 360,
            }
        ),
        flush=True,
    )
    if not execute:
        print("Dry run: zero provider calls.")
        return None
    if not info["key_configured"]:
        raise ValueError("MISSING_TYPESAFE_API_KEY")
    if not resume:
        directory.mkdir()
        save(directory / "identity.json", {"identity": identity, "preflight": info})
    dataset, fixtures = load()
    artifact: dict[str, Any] = {
        "identity": identity,
        "preflight": info,
        "cases": [],
        "stop_reason": None,
    }
    invalid_streak = 0
    async with httpx.AsyncClient(trust_env=False) as client:
        router = JournalRouter(TypeSafeSettings(), client, directory, identity)
        for case, expected in zip(dataset.cases, info["cases"], strict=True):
            router.case_id = case.id
            path = directory / (case.id + ".case.json")
            envelope = prepare(case.question, fixtures.states[case.state_fixture])
            if (
                not isinstance(envelope, PreparedEnvelope)
                or envelope.identity_hash != expected["envelope"]
            ):
                raise ValueError("PREPARED_INPUT_CHANGED")
            registry = generate_options(envelope)
            if (
                not isinstance(registry, OptionRegistry)
                or registry.identity_hash != expected["options"]
            ):
                raise ValueError("OPTION_REGISTRY_CHANGED")
            if path.exists():
                retained = json.loads(path.read_text())
                if (
                    retained["record_hash"] != digest(retained["record"])
                    or retained["record"]["run_identity"] != identity
                ):
                    raise ValueError("CORRUPTED_CASE_CHECKPOINT")
                retained_record = retained["record"]
                artifact["cases"].append(retained_record)
                router.accounting["reused_stage1"] += 1
                if len(retained_record["observation"]["stages"]) == 2:
                    router.accounting["reused_stage2"] += 1
                continue
            checkpoint = directory / (case.id + ".stage1.checkpoint.json")
            first = read_checkpoint(checkpoint) if checkpoint.exists() else None
            if first:
                reuse_stage1(envelope, registry, first)
                router.accounting["reused_stage1"] += 1
            started = perf_counter()
            record: dict[str, Any] = {"id": case.id}
            try:
                result = await router.interpret(
                    envelope,
                    execute=True,
                    resume=first,
                    checkpoint_path=None if first else checkpoint,
                )
                record = {
                    "id": case.id,
                    "run_identity": identity,
                    "observation": result.telemetry_record(include_synthetic_domain=True),
                    "routing_latency_ms": (perf_counter() - started) * 1000,
                    "prepared_input": envelope.model_dump(mode="json"),
                    "options": registry.model_dump(mode="json"),
                }
                # Retain paid decisions before any downstream resolution/scoring.
                save(directory / (case.id + ".translation.json"), record)
                if result.interpretation:
                    files = fixtures.snapshots[case.metadata_fixture]

                    class Metadata:
                        async def list_visible_indexed_files(
                            self, user_id: UUID
                        ) -> tuple[IndexedFile, ...]:
                            return tuple(
                                f.file
                                for f in files
                                if f.visible and f.indexed and f.file.user_id == user_id
                            )

                    resolution = await resolve(
                        result.interpretation,
                        trusted_input=envelope.input,
                        state=fixtures.states[case.state_fixture],
                        user_id=fixtures.user_id,
                        metadata=Metadata(),
                    )
                    record["resolution"] = resolution.model_dump(mode="json")
                    record["readiness"] = (
                        resolution.status if isinstance(resolution, ResolutionReport) else "FAILED"
                    )
                else:
                    record["readiness"] = (
                        "NOT_APPLICABLE" if result.status == "STAGE1_UNINTERPRETABLE" else "FAILED"
                    )
                save(path, {"record": record, "record_hash": digest(record)})
                artifact["cases"].append(record)
                invalid_streak = (
                    invalid_streak + 1
                    if any(s.status == "INVALID_RESPONSE" for s in result.stages)
                    else 0
                )
                if (
                    result.error_code == "AUTH_ERROR"
                    or invalid_streak >= 2
                    or result.status == "PREPARATION_ERROR"
                    or result.error_code
                    in {
                        "STALE_OPTION_REGISTRY",
                        "DOMAIN_INVARIANT",
                        "CONTRACT_CHANGED_DURING_REQUEST",
                        "CHECKPOINT_WRITE_ERROR",
                        "STAGE1_CHECKPOINT_MISMATCH",
                    }
                    or record["readiness"] == "FAILED"
                    and result.status == "SUCCESS"
                ):
                    artifact["stop_reason"] = result.status + ":" + str(result.error_code)
            except Exception as exc:
                artifact["stop_reason"] = "LOCAL_SYSTEM_ERROR:" + type(exc).__name__
            artifact["accounting"] = dict(router.accounting)
            save(directory / "result.json", artifact)
            print(
                case.id,
                record.get("observation", {}).get("status"),
                record.get("readiness"),
                flush=True,
            )
            if artifact["stop_reason"]:
                break
            await asyncio.sleep(0.25)
        artifact["accounting"] = dict(router.accounting)
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
