"""Evaluation-only direct TypeSafe transport; no Jev-org wire assumptions."""

import asyncio
import re
import json
import math
from time import perf_counter
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import BACKEND_ROOT, REPO_ROOT
from app.routing.providers.jev import assemble, assembly_diagnostics, parse_answers, serialize_state
from app.routing.providers.jev_criteria import CRITERIA_VERSION, questions
from app.routing.semantic import ObservationStatus, ProviderObservation, RoutingInput


class TypeSafeSettings(BaseSettings):
    typesafe_api_key: SecretStr = Field(default=SecretStr(""), exclude=True)
    typesafe_base_url: str = "https://api.typesafe.ai"
    typesafe_model: str = "jev-latest"
    typesafe_timeout_seconds: float = Field(default=15, gt=0, le=60)
    model_config = SettingsConfigDict(
        env_file=(str(REPO_ROOT / ".env"), str(BACKEND_ROOT / ".env")),
        extra="ignore",
        env_ignore_empty=True,
    )

    @field_validator("typesafe_model")
    @classmethod
    def allowed_model(cls, value: str) -> str:
        if value != "jev-latest":
            raise ValueError("This comparison uses jev-latest only")
        return value

    @field_validator("typesafe_base_url")
    @classmethod
    def safe_url(cls, value: str) -> str:
        url = urlsplit(value)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path not in ("", "/")
        ):
            raise ValueError("TypeSafe base must be an HTTPS origin")
        return value.rstrip("/")


# Official docs and five observed alias resolutions identify this stable version.
# A new resolution must be reviewed explicitly instead of accepting arbitrary models.
RETURNED_MODELS = frozenset({"jev-latest", "jev-1.13.0"})

ERROR_CODES = {
    "Invalid TypeSafe body": "BODY_NOT_OBJECT",
    "Missing returned model": "MODEL_MISSING_OR_NULL",
    "Unexpected returned model": "MODEL_UNEXPECTED",
    "Missing answers": "ANSWERS_MISSING_OR_NOT_OBJECT",
    "Missing Choice confidence": "CHOICE_CONFIDENCE_MISSING",
    "Answer IDs do not match": "ANSWER_IDS_MISMATCH",
    "Invalid answer type": "ANSWER_TYPE_INVALID",
    "Probability must be numeric": "PROBABILITY_NOT_NUMERIC",
    "Invalid probability": "PROBABILITY_OUT_OF_RANGE_OR_NONFINITE",
    "Invalid distribution labels": "DISTRIBUTION_LABELS_INVALID",
    "Distribution is not normalized": "DISTRIBUTION_NOT_NORMALIZED",
    "Invalid selected label": "CHOICE_UNKNOWN_OR_NOT_MAXIMUM",
    "Missing usage": "USAGE_MISSING_OR_NOT_OBJECT",
    "Invalid token usage": "TOKEN_COUNT_INVALID",
    "Missing mode": "MODE_MISSING",
    "CLARIFY requires a clarification reason": "CLARIFICATION_REASON_REQUIRED",
    "Required operation slot is empty": "OPERATION_SLOT_REQUIRED",
    "Oversized response": "RESPONSE_TOO_LARGE",
}


def finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def structural_snapshot(data: Any) -> dict[str, str]:
    """Allowlisted bounded evidence; no raw strings, unknown keys or error text."""
    specs = questions()
    summary: dict[str, Any] = {"body_type": type(data).__name__}
    safe: dict[str, Any] = {}
    present: list[str] = []
    if isinstance(data, dict):
        summary["fields"] = {
            name: type(data[name]).__name__
            for name in ("model", "answers", "usage")
            if name in data
        }
        model = data.get("model")
        if isinstance(model, str) and (
            model in RETURNED_MODELS
            or model == "jev-preview"
            or re.fullmatch(r"jev-\d+\.\d+(?:\.\d+)?", model)
        ):
            safe["model"] = model
        raw = data.get("answers")
        if isinstance(raw, dict):
            present = sorted(name for name in specs if name in raw)
            summary["unknown_answer_count"] = len(raw) - len(present)
            summary["answer_shapes"] = {}
            safe["answers"] = {}
            for name in present:
                answer = raw[name]
                summary["answer_shapes"][name] = {"container": type(answer).__name__}
                if not isinstance(answer, dict):
                    continue
                summary["answer_shapes"][name]["fields"] = {
                    k: type(answer[k]).__name__
                    for k in ("type", "choice", "confidence", "noul", "probabilities")
                    if k in answer
                }
                clean: dict[str, Any] = {}
                if answer.get("type") in ("choice", "noul", "score"):
                    clean["type"] = answer["type"]
                selected = answer.get("choice")
                options = specs[name].get("criteria", {})
                if isinstance(selected, str) and selected in options:
                    clean["choice"] = selected
                for key in ("confidence", "noul"):
                    value = answer.get(key)
                    if finite_number(value):
                        clean[key] = value
                distribution = answer.get("probabilities")
                if isinstance(distribution, dict):
                    clean["probabilities"] = {
                        label: value
                        for label, value in distribution.items()
                        if label in options and finite_number(value)
                    }
                    summary["answer_shapes"][name]["probability_label_count"] = len(distribution)
                safe["answers"][name] = clean
        usage = data.get("usage")
        if isinstance(usage, dict):
            safe["usage"] = {
                name: value
                for name, value in usage.items()
                if name in ("input_tokens", "output_tokens")
                and (value is None or (isinstance(value, int) and not isinstance(value, bool)))
            }
    return {
        "answer_ids_present": json.dumps(present),
        "response_schema_summary": json.dumps(summary, sort_keys=True),
        "sanitized_provider_snapshot": json.dumps(safe, sort_keys=True),
    }


def validate_typesafe(data: Any, base: dict[str, Any] | None = None) -> dict[str, Any]:
    base = {} if base is None else base
    evidence = base.setdefault("provenance", {})
    evidence.update(structural_snapshot(data))
    evidence["validation_stage"] = "body"
    if not isinstance(data, dict):
        raise ValueError("Invalid TypeSafe body")
    returned_model = data.get("model")
    evidence["validation_stage"] = "model"
    if returned_model is None:
        raise ValueError("Missing returned model")
    if not isinstance(returned_model, str) or returned_model not in RETURNED_MODELS:
        raise ValueError("Unexpected returned model")
    base["model_version"] = returned_model
    evidence["validation_stage"] = "answers"
    raw = data.get("answers")
    if not isinstance(raw, dict):
        raise ValueError("Missing answers")
    for name, spec in questions().items():
        if spec["type"] == "choice" and (
            not isinstance(raw.get(name), dict) or "confidence" not in raw[name]
        ):
            raise ValueError("Missing Choice confidence")
    answers = parse_answers(raw, rounding_aware=True)
    base["answers"] = answers
    evidence["validation_stage"] = "usage"
    usage = data.get("usage")
    if not isinstance(usage, dict):
        raise ValueError("Missing usage")
    sanitized = {}
    for name in ("input_tokens", "output_tokens"):
        if name in usage and usage[name] is not None:
            value = usage[name]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("Invalid token usage")
            sanitized[name] = value
    base["usage"] = sanitized
    evidence["validation_stage"] = "assembly"
    prediction = assemble(answers)
    base["prediction"] = prediction
    base["assembly_diagnostics"] = assembly_diagnostics(answers, prediction)
    evidence["validation_stage"] = "complete"
    return base


class TypeSafeJevRouter:
    def __init__(self, settings: TypeSafeSettings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self.client = client

    async def route(self, request: RoutingInput, *, idempotency_key: str) -> ProviderObservation:
        # Protocol parameter retained; no undocumented idempotency header or recovery.
        state, truncated = serialize_state(request)
        base: dict[str, Any] = dict(
            provider="api.typesafe.ai",
            model=self.settings.typesafe_model,
            criteria_version=CRITERIA_VERSION,
            history_truncated=truncated,
        )
        key = self.settings.typesafe_api_key.get_secret_value().strip()
        if not key:
            return ProviderObservation(status=ObservationStatus.UNAVAILABLE, **base)
        started = perf_counter()
        base.update(calls=1, post_attempts=1, new_model_decisions=None)
        try:

            async def call(client: httpx.AsyncClient) -> httpx.Response:
                return await client.post(
                    self.settings.typesafe_base_url + "/v1/systemone",
                    json={
                        "model": self.settings.typesafe_model,
                        "state": state,
                        "questions": questions(),
                    },
                    headers={"Authorization": "Bearer " + key},
                    timeout=self.settings.typesafe_timeout_seconds,
                    follow_redirects=False,
                )

            async def send() -> httpx.Response:
                if self.client is not None:
                    return await call(self.client)
                async with httpx.AsyncClient(trust_env=False) as client:
                    return await call(client)

            response = await asyncio.wait_for(
                send(), timeout=self.settings.typesafe_timeout_seconds
            )
            base["http_status"] = response.status_code
            if response.status_code != 200:
                base["new_model_decisions"] = 0
                status = {
                    401: ObservationStatus.AUTH_ERROR,
                    422: ObservationStatus.INVALID_RESPONSE,
                    429: ObservationStatus.RATE_LIMITED,
                }.get(
                    response.status_code,
                    ObservationStatus.UNAVAILABLE
                    if response.status_code >= 500
                    else ObservationStatus.INVALID_RESPONSE,
                )
                return ProviderObservation(
                    status=status, latency_ms=(perf_counter() - started) * 1000, **base
                )
            base["new_model_decisions"] = 1
            base["provenance"] = {
                "validation_stage": "response_size",
                "response_bytes": str(len(response.content)),
            }
            if len(response.content) > 1000000:
                raise ValueError("Oversized response")
            base["provenance"]["validation_stage"] = "json"
            validate_typesafe(response.json(), base)
            return ProviderObservation(
                status=ObservationStatus.SUCCESS,
                latency_ms=(perf_counter() - started) * 1000,
                **base,
            )
        except (TimeoutError, httpx.TimeoutException):
            status = ObservationStatus.TIMEOUT
        except httpx.TransportError:
            status = ObservationStatus.UNAVAILABLE
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            status = ObservationStatus.INVALID_RESPONSE
            evidence = base.setdefault("provenance", {})
            if evidence.get("validation_stage") == "json":
                code = "JSON_INVALID"
            elif isinstance(exc, ValueError):
                # Only fixed internal messages map to codes; never persist exception text.
                code = ERROR_CODES.get(str(exc), "VALIDATION_FAILED")
            else:
                code = "FIELD_SHAPE_INVALID"
            evidence["validation_error_code"] = code
        return ProviderObservation(
            status=status, latency_ms=(perf_counter() - started) * 1000, **base
        )
