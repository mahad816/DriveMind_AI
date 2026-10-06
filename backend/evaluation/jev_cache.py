"""Exact-identity, read-only persistent observation recovery for Jev evaluation."""

import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from app.routing.providers.jev import (
    JevSettings,
    idempotency_key,
    serialize_state,
    validate_response,
)
from app.routing.providers.jev_criteria import CONTEXT_VERSION, CRITERIA_VERSION, questions
from app.routing.semantic import ObservationStatus, ProviderObservation, RoutingInput
from evaluation.routing_dataset import RoutingCase

FROZEN_HASH = "4831a76ee7e782e968a0224e6b935729712ba21e2eb25617a2cddbe268549884"
QUESTION_SCHEMA_VERSION = "jev-routing-questions-1.0"


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def source_timestamp(raw: dict[str, Any], previous: dict[str, Any]) -> str:
    provenance = previous.get("provenance", {})
    value = (
        provenance.get("original_timestamp", raw.get("timestamp"))
        if isinstance(provenance, dict)
        else raw.get("timestamp")
    )
    try:
        return datetime.fromisoformat(value).isoformat() if isinstance(value, str) else "unknown"
    except ValueError:
        return "unknown"


def input_for(case: RoutingCase) -> RoutingInput:
    return RoutingInput(
        question=case.question,
        history=tuple(t.model_dump() for t in case.history),
        history_window_complete=case.history_window_complete,
    )


def criteria_hash() -> str:
    return digest(questions())


def case_identity(case: RoutingCase, settings: JevSettings) -> dict[str, str]:
    request = input_for(case)
    state, _ = serialize_state(request)
    return {
        "case_id": case.id,
        "input_hash": digest(request.model_dump(mode="json")),
        "state_hash": digest(state),
        "context_version": CONTEXT_VERSION,
        "question_schema_version": QUESTION_SCHEMA_VERSION,
        "idempotency_key": idempotency_key(
            "routing-1.0:" + FROZEN_HASH, case.id, settings.jev_model, request
        ),
    }


def wire_response(observation: dict[str, Any]) -> dict[str, Any]:
    """Restore wire-shaped raw answers; never trust a stored prediction/status."""
    answers = {}
    for name, answer in observation["answers"].items():
        if not isinstance(answer, dict):
            raise ValueError("Invalid saved answer")
        if answer.get("noul") is not None:
            answers[name] = {"type": "noul", "noul": answer["noul"]}
        else:
            answers[name] = {
                "type": "choice",
                "choice": answer.get("selected"),
                "probabilities": answer.get("probabilities"),
            }
            if answer.get("confidence") is not None:
                answers[name]["confidence"] = answer["confidence"]
    response = {
        "model": observation["model"],
        "model_version": observation["model_version"],
        "answers": answers,
        "usage": observation.get("usage", {}),
    }
    if observation.get("upstream_latency_ms") is not None:
        response["latency_ms"] = observation["upstream_latency_ms"]
    if observation.get("request_id") is not None:
        response["id"] = observation["request_id"]
    return response


def matching_artifact(raw: dict[str, Any], settings: JevSettings) -> bool:
    if not all(
        raw.get(key) == value
        for key, value in {
            "dataset_sha256": FROZEN_HASH,
            "dataset_version": "routing-1.0",
            "criteria_version": CRITERIA_VERSION,
            "criteria_hash": criteria_hash(),
            "model": settings.jev_model,
            "base_url": settings.jev_base_url,
        }.items()
    ):
        return False
    if (
        raw.get("context_version", CONTEXT_VERSION) != CONTEXT_VERSION
        or raw.get("question_schema_version", QUESTION_SCHEMA_VERSION) != QUESTION_SCHEMA_VERSION
    ):
        return False
    if raw.get("artifact_version") == "jev-shadow-1.0":
        # Explicit legacy migration: this artifact version uniquely used bounded-history-v1
        # and the current 11-question schema. Gold/input and question hash still must match.
        return True
    return (
        raw.get("artifact_version") == "jev-shadow-1.1"
        and raw.get("context_version") == CONTEXT_VERSION
        and raw.get("question_schema_version") == QUESTION_SCHEMA_VERSION
    )


def find_reusable(
    directory: Path,
    cases: list[RoutingCase],
    settings: JevSettings,
    *,
    paths: list[Path] | None = None,
) -> dict[str, ProviderObservation]:
    wanted = {c.id: c for c in cases}
    found: dict[str, ProviderObservation] = {}
    candidates = paths if paths is not None else sorted(directory.glob("jev_shadow_*.json"))
    # Stable content identity, not timestamps, determines preference.
    ranked = []
    for path in candidates:
        try:
            if path.is_symlink() or path.stat().st_size > 10000000:
                continue
            data = path.read_bytes()
            raw = json.loads(data)
            if not isinstance(raw, dict) or not matching_artifact(raw, settings):
                continue
            ranked.append(
                (
                    raw.get("artifact_version") != "jev-shadow-1.1",
                    hashlib.sha256(data).hexdigest(),
                    path,
                    raw,
                )
            )
        except (ValueError, OSError, TypeError):
            continue
    for _, artifact_hash, path, raw in sorted(ranked, key=lambda r: (r[0], r[1], str(r[2]))):
        entries = raw.get("cases")
        if not isinstance(entries, list):
            continue
        for entry in entries:
            try:
                if not isinstance(entry, dict) or entry.get("id") not in wanted:
                    continue
                case = wanted[entry["id"]]
                if RoutingCase.model_validate(entry["gold"]).model_dump() != case.model_dump():
                    continue
                if raw["artifact_version"] == "jev-shadow-1.1" and entry.get(
                    "identity"
                ) != case_identity(case, settings):
                    continue
                previous = entry["jev"]
                if (
                    not isinstance(previous, dict)
                    or previous.get("http_status") not in (200, 409)
                    or previous.get("provider") != "jev-ai.org"
                    or previous.get("criteria_version") != CRITERIA_VERSION
                ):
                    continue
                if previous.get("http_status") == 409 and not previous.get("recovered_idempotent"):
                    continue
                validated = validate_response(wire_response(previous), settings.jev_model)
                obs = ProviderObservation(
                    status=ObservationStatus.SUCCESS,
                    provider="jev-ai.org",
                    model=settings.jev_model,
                    criteria_version=CRITERIA_VERSION,
                    latency_ms=previous["latency_ms"],
                    http_status=previous["http_status"],
                    calls=previous.get("calls", 1),
                    history_truncated=previous.get("history_truncated", False),
                    recovered_idempotent=previous.get("recovered_idempotent", False),
                    provenance={
                        "source_artifact": path.name,
                        "source_sha256": artifact_hash,
                        "original_timestamp": source_timestamp(raw, previous),
                        "original_status": str(ObservationStatus(previous["status"]).value),
                    },
                    **validated,
                )
                if not obs.latency_ms >= 0 or not math.isfinite(obs.latency_ms):
                    continue
                found.setdefault(case.id, obs)
            except (ValueError, TypeError, KeyError, AttributeError):
                continue
    return found
