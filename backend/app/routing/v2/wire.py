"""Validated sanitized TypeSafe Choice responses, reusable offline."""

import math
from typing import Any, Literal
from pydantic import ValidationError
from app.routing.providers.typesafe import RETURNED_MODELS
from app.routing.providers.probability_validation import validate_distribution
from app.routing.v2.observations import ChoiceObservation, StageObservation, TokenUsage


def probability(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("invalid probability")
    try:
        if not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("invalid probability")
        return float(value)
    except OverflowError:
        raise ValueError("invalid probability") from None


def parse_stage(
    data: Any,
    questions: dict[str, dict[str, Any]],
    stage: Literal[1, 2],
    *,
    latency_ms: float = 0,
    http_status: int = 200,
) -> StageObservation:
    base: dict[str, Any] = {
        "stage": stage,
        "status": "INVALID_RESPONSE",
        "http_status": http_status,
        "post_attempts": 1,
        "latency_ms": latency_ms,
    }
    if not isinstance(data, dict):
        return StageObservation(**base, error_code="INVALID_BODY")
    if not isinstance(data.get("model"), str) or data["model"] not in RETURNED_MODELS:
        return StageObservation(**base, error_code="MODEL_INVALID")
    base["returned_model"] = data["model"]
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return StageObservation(**base, error_code="USAGE_INVALID")
    try:
        base["usage"] = TokenUsage.model_validate(
            {k: usage[k] for k in ("input_tokens", "output_tokens") if k in usage}
        )
    except ValidationError:
        return StageObservation(**base, error_code="USAGE_INVALID")
    raw = data.get("answers")
    if not isinstance(raw, dict) or set(raw) != set(questions):
        return StageObservation(**base, error_code="ANSWER_IDS_INVALID")
    parsed = []
    try:
        for name, spec in questions.items():
            answer = raw[name]
            if not isinstance(answer, dict) or answer.get("type") != "choice":
                raise ValueError("invalid choice")
            probabilities = answer.get("probabilities")
            if not isinstance(probabilities, dict) or set(probabilities) != set(spec["criteria"]):
                raise ValueError("invalid labels")
            selected = answer.get("choice")
            if not isinstance(selected, str) or selected not in probabilities:
                raise ValueError("invalid selected")
            distribution = {k: probability(v) for k, v in probabilities.items()}
            confidence = probability(answer.get("confidence"))
            validate_distribution(distribution, selected)
            parsed.append(
                ChoiceObservation(
                    answer_id=name,
                    selected=selected,
                    probabilities=tuple(distribution.items()),
                    confidence=confidence,
                )
            )
    except (ValueError, TypeError, KeyError):
        return StageObservation(**base, error_code="ANSWER_INVALID", answers=tuple(parsed))
    base["status"] = "SUCCESS"
    return StageObservation(**base, answers=tuple(parsed))
