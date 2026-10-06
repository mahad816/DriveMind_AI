"""Offline revalidation of exact-identity paid TypeSafe checkpoints."""

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from app.routing.providers.probability_validation import VALIDATION_VERSION
from app.routing.providers.jev_criteria import questions
from app.routing.providers.typesafe import TypeSafeSettings, validate_typesafe, ERROR_CODES
from app.routing.semantic import ProviderObservation, ObservationStatus
from evaluation.jev_runner import frozen_cases
from evaluation.routing_runner import DEFAULT_DATASET, DEFAULT_OUTPUT
from evaluation.typesafe_runner import identity
from evaluation.typesafe_analysis import analysis


def replay_checkpoint(path: Path, settings: TypeSafeSettings) -> list[dict[str, Any]]:
    if path.is_symlink() or path.stat().st_size > 10000000:
        raise ValueError("Unsafe checkpoint")
    text = path.read_text()
    if path.suffix == ".jsonl":
        records = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        artifact = json.loads(text)
        if artifact.get("artifact_version") not in (
            "typesafe-full-1.0",
            "typesafe-full-aborted-1.0",
            "typesafe-offline-replay-1.0",
        ):
            raise ValueError("Unknown checkpoint format")
        records = artifact["cases"]
    cases = frozen_cases(DEFAULT_DATASET)
    if not records or len(records) > len(cases):
        raise ValueError("Invalid checkpoint count")
    result = []
    for case, record in zip(cases, records, strict=False):
        if (
            record["id"] != case.id
            or record["identity"] != identity(case, settings)
            or record["gold"] != case.model_dump(mode="json")
        ):
            raise ValueError("Checkpoint input/configuration mismatch")
        previous = ProviderObservation.model_validate(record["observation"])
        if (
            previous.http_status != 200
            or previous.provider != "api.typesafe.ai"
            or previous.model != "jev-latest"
        ):
            raise ValueError("Checkpoint has unrecoverable provider outcome")
        snapshot = previous.provenance.get("sanitized_provider_snapshot")
        if not snapshot:
            raise ValueError("Missing retained provider evidence")
        # Sanitization drops unknown labels: require the retained schema evidence
        # to prove that no unknown wire fields were hidden by that allowlist.
        summary = json.loads(previous.provenance["response_schema_summary"])
        if summary.get("unknown_answer_count") != 0:
            raise ValueError("Checkpoint contains unknown answer IDs")
        shapes = summary.get("answer_shapes", {})
        for name, spec in questions().items():
            if spec["type"] == "choice" and shapes.get(name, {}).get(
                "probability_label_count"
            ) != len(spec["criteria"]):
                raise ValueError("Checkpoint distribution shape mismatch")
        # Never use the historical derived prediction, parsed answers, or status.
        base = previous.model_dump()
        base.update(prediction=None, answers={}, assembly_diagnostics=None, usage={})
        base["provenance"] = {
            **previous.provenance,
            "source_checkpoint": path.name,
            "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "validation_version": VALIDATION_VERSION,
            "original_status": previous.status.value,
        }
        try:
            validate_typesafe(json.loads(snapshot), base)
            base["status"] = ObservationStatus.SUCCESS
            base["provenance"].pop("validation_error_code", None)
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            base["status"] = ObservationStatus.INVALID_RESPONSE
            base["provenance"]["validation_error_code"] = ERROR_CODES.get(
                str(exc), "VALIDATION_FAILED"
            )
        result.append(
            {
                **record,
                "fresh": False,
                "observation": ProviderObservation(**base).model_dump(mode="json"),
            }
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path)
    args = parser.parse_args()
    records = replay_checkpoint(args.checkpoint, TypeSafeSettings())
    cases = frozen_cases(DEFAULT_DATASET)[: len(records)]
    report = {
        "artifact_version": "typesafe-offline-replay-1.0",
        "timestamp": datetime.now(UTC).isoformat(),
        "validation_version": VALIDATION_VERSION,
        "source_sha256": hashlib.sha256(args.checkpoint.read_bytes()).hexdigest(),
        "reused_existing": len(records),
        "new_decisions": 0,
        "http_requests": 0,
        "cases": records,
        "analysis": analysis(
            cases, [ProviderObservation.model_validate(r["observation"]) for r in records]
        ),
    }
    path = DEFAULT_OUTPUT / (args.checkpoint.stem + ".replay.json")
    with path.open("x") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
    print(f"Offline replay: {len(records)} cases; zero calls; {path}")


if __name__ == "__main__":
    main()
