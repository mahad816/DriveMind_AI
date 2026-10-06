"""Explicit exact-identity Stage-1 replay. No provider idempotency assumptions."""

from pathlib import Path
from typing import Any

from app.routing.v2.contracts import digest, source_hashes, VERSIONS
from app.routing.v2.preparation import PreparedEnvelope
from app.routing.v2.options import OptionRegistry
from app.routing.v2.questions import stage1_questions, stage2_questions
from app.routing.v2.observations import Fingerprint, Stage1Checkpoint, StageObservation
from app.routing.v2.wire import parse_stage


def identities(
    envelope: PreparedEnvelope, registry: OptionRegistry, count: int | None
) -> tuple[Fingerprint, ...]:
    values = {
        "envelope": envelope.identity_hash,
        "options": registry.identity_hash,
        "stage1_questions": digest(stage1_questions()),
        "stage2_questions": digest(stage2_questions(registry, count) if count else None),
        "versions": digest(VERSIONS),
        "provider_config": digest({"origin": "https://api.typesafe.ai", "model": "jev-latest"}),
        **source_hashes(),
    }
    return tuple(Fingerprint(name=name, value=value) for name, value in sorted(values.items()))


def revalidate(observation: StageObservation) -> StageObservation:
    if observation.stage != 1 or observation.status != "SUCCESS" or observation.http_status != 200:
        raise ValueError("checkpoint is not a successful Stage 1")
    body: dict[str, Any] = {
        "model": observation.returned_model,
        "usage": observation.usage.model_dump(),
        "answers": {
            answer.answer_id: {
                "type": "choice",
                "choice": answer.selected,
                "confidence": answer.confidence,
                "probabilities": answer.distribution(),
            }
            for answer in observation.answers
        },
    }
    if len(body["answers"]) != len(observation.answers):
        raise ValueError("duplicate checkpoint answer IDs")
    validated = parse_stage(body, stage1_questions(), 1, latency_ms=observation.latency_ms)
    if validated.status != "SUCCESS":
        raise ValueError("invalid retained Stage-1 response")
    # Preserve original latency and HTTP-attempt metadata; new-call accounting is separate.
    return StageObservation.model_validate(
        {**validated.model_dump(), "post_attempts": observation.post_attempts}
    )


def count_for(observation: StageObservation) -> int | None:
    return {"ONE": 1, "TWO": 2, "THREE": 3}.get(observation.answers[0].selected)


def make_checkpoint(
    envelope: PreparedEnvelope, registry: OptionRegistry, observation: StageObservation
) -> Stage1Checkpoint:
    validated = revalidate(observation)
    fingerprints = identities(envelope, registry, count_for(validated))
    return Stage1Checkpoint(
        identity_hash=digest([f.model_dump() for f in fingerprints]),
        fingerprints=fingerprints,
        response_hash=digest(validated.model_dump(mode="json")),
        observation=validated,
    )


def reuse_stage1(
    envelope: PreparedEnvelope, registry: OptionRegistry, checkpoint: Stage1Checkpoint
) -> StageObservation:
    checkpoint = Stage1Checkpoint.model_validate_json(checkpoint.model_dump_json())
    current = make_checkpoint(envelope, registry, checkpoint.observation)
    if current != checkpoint:
        raise ValueError("checkpoint identity or response integrity mismatch")
    return current.observation


def write_checkpoint(path: Path, checkpoint: Stage1Checkpoint) -> None:
    # Validate again before persistence; unknown/private provider strings cannot escape.
    validated = revalidate(checkpoint.observation)
    if digest(validated.model_dump(mode="json")) != checkpoint.response_hash:
        raise ValueError("checkpoint response integrity mismatch")
    if digest([f.model_dump() for f in checkpoint.fingerprints]) != checkpoint.identity_hash:
        raise ValueError("checkpoint identity integrity mismatch")
    # Contains IDs/distributions/hashes only, no raw question, filenames, auth, or body.
    with path.open("x", encoding="utf-8") as handle:
        handle.write(checkpoint.model_dump_json(indent=2))


def read_checkpoint(path: Path) -> Stage1Checkpoint:
    if path.is_symlink() or path.stat().st_size > 250000:
        raise ValueError("unsafe checkpoint")
    return Stage1Checkpoint.model_validate_json(path.read_text(encoding="utf-8"))
