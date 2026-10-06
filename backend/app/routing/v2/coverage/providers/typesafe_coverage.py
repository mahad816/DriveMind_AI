"""Native direct TypeSafe coverage adapter. Explicit opt-in; no retries."""

import asyncio
import math
from time import perf_counter
from typing import Any
import json

import httpx
from pydantic import ValidationError

from app.routing.providers.typesafe import TypeSafeSettings, RETURNED_MODELS
from app.routing.providers.probability_validation import validate_distribution
from .. import CoverageInput, CoverageResult, CoverageObservation, CoverageVerdict, CoverageUsage
from ..contracts import contract_identity, verify_lock
from ..criteria import questions

MAX_REQUEST_BYTES = 48000
MAX_RESPONSE_BYTES = 1000000


def parse_response(
    data: Any, *, identity: str, http_status: int = 200, latency_ms: float = 0
) -> CoverageObservation:
    base = {
        "contract_identity": identity,
        "http_status": http_status,
        "latency_ms": latency_ms,
        "post_attempts": 1,
    }

    def failure(code: str) -> CoverageObservation:
        return CoverageObservation.model_validate(
            {**base, "status": "INVALID_RESPONSE", "error_code": code}
        )

    if not isinstance(data, dict):
        return failure("INVALID_ANSWERS")
    if not isinstance(data.get("model"), str) or data["model"] not in RETURNED_MODELS:
        return failure("INVALID_MODEL")
    base["returned_model"] = data["model"]
    if not isinstance(data.get("usage"), dict):
        return failure("INVALID_USAGE")
    try:
        base["usage"] = CoverageUsage.model_validate(
            {k: data["usage"][k] for k in ("input_tokens", "output_tokens") if k in data["usage"]}
        )
    except ValidationError:
        return failure("INVALID_USAGE")
    answers = data.get("answers")
    if not isinstance(answers, dict) or set(answers) != {"COVERAGE"}:
        return failure("INVALID_ANSWERS")
    answer = answers["COVERAGE"]
    if not isinstance(answer, dict) or answer.get("type") != "choice":
        return failure("INVALID_ANSWERS")
    distribution = answer.get("probabilities")
    selected = answer.get("choice")
    confidence = answer.get("confidence")
    try:
        if (
            not isinstance(distribution, dict)
            or set(distribution) != {v.value for v in CoverageVerdict}
            or not isinstance(selected, str)
            or selected not in distribution
        ):
            raise ValueError("labels")
        for value in [*distribution.values(), confidence]:
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 <= value <= 1
            ):
                raise ValueError("probability")
        validate_distribution(distribution, selected)
        return CoverageObservation.model_validate(
            {
                **base,
                "status": "SUCCESS",
                "selected": selected,
                "confidence": confidence,
                "probabilities": [
                    {"verdict": v.value, "probability": distribution[v.value]}
                    for v in CoverageVerdict
                ],
            }
        )
    except (ValueError, TypeError, OverflowError):
        return failure("INVALID_PROBABILITIES")


class TypeSafeCoverageVerifier:
    def __init__(self, settings: TypeSafeSettings, client: httpx.AsyncClient | None = None) -> None:
        if (
            settings.typesafe_base_url != "https://api.typesafe.ai"
            or settings.typesafe_model != "jev-latest"
        ):
            raise ValueError("direct TypeSafe required")
        self.settings = settings
        self.client = client

    async def verify(self, coverage: CoverageInput, *, execute: bool = False) -> CoverageResult:
        identity = contract_identity()

        def result(observation: CoverageObservation) -> CoverageResult:
            return CoverageResult(
                verdict=observation.selected,
                observation=observation,
                input_identity=coverage.input_identity,
                interpretation_identity=coverage.interpretation_identity,
                context_identity=coverage.context_identity,
                contract_identity=identity,
            )

        def unavailable(code: str, status: str = "NOT_EXECUTED") -> CoverageResult:
            return result(
                CoverageObservation.model_validate(
                    {"status": status, "error_code": code, "contract_identity": identity}
                )
            )

        try:
            CoverageInput.model_validate_json(coverage.model_dump_json())
        except ValidationError:
            return unavailable("INPUT_IDENTITY_MISMATCH", "INVALID_RESPONSE")
        if not verify_lock() or coverage.contract_identity != identity:
            return unavailable("CONTRACT_MISMATCH", "INVALID_RESPONSE")
        if not execute:
            return unavailable("EXECUTION_NOT_AUTHORIZED")
        key = self.settings.typesafe_api_key.get_secret_value().strip()
        if not key:
            return unavailable("MISSING_KEY", "PROVIDER_ERROR")
        payload = {
            "model": self.settings.typesafe_model,
            "state": coverage.provider_state(),
            "questions": questions(),
        }
        if (
            len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())
            > MAX_REQUEST_BYTES
        ):
            return unavailable("REQUEST_TOO_LARGE", "INVALID_RESPONSE")
        started = perf_counter()

        async def send(client: httpx.AsyncClient) -> httpx.Response:
            return await client.post(
                self.settings.typesafe_base_url + "/v1/systemone",
                json=payload,
                headers={"Authorization": "Bearer " + key},
                timeout=self.settings.typesafe_timeout_seconds,
                follow_redirects=False,
            )

        async def request() -> httpx.Response:
            if self.client is not None:
                return await send(self.client)
            async with httpx.AsyncClient(trust_env=False) as client:
                return await send(client)

        try:
            response = await asyncio.wait_for(
                request(), timeout=self.settings.typesafe_timeout_seconds
            )
            base = {
                "contract_identity": identity,
                "http_status": response.status_code,
                "post_attempts": 1,
            }
            if response.status_code != 200:
                observation = CoverageObservation.model_validate(
                    {
                        **base,
                        "status": "PROVIDER_ERROR",
                        "error_code": "AUTH_ERROR"
                        if response.status_code == 401
                        else "RATE_LIMITED"
                        if response.status_code == 429
                        else "HTTP_ERROR",
                    }
                )
            elif len(response.content) > MAX_RESPONSE_BYTES:
                observation = CoverageObservation.model_validate(
                    {**base, "status": "INVALID_RESPONSE", "error_code": "RESPONSE_TOO_LARGE"}
                )
            else:
                try:
                    data = response.json()
                except ValueError:
                    observation = CoverageObservation.model_validate(
                        {**base, "status": "INVALID_RESPONSE", "error_code": "INVALID_JSON"}
                    )
                else:
                    observation = parse_response(data, identity=identity)
        except (TimeoutError, httpx.TimeoutException):
            observation = CoverageObservation(
                status="PROVIDER_ERROR",
                error_code="TIMEOUT",
                contract_identity=identity,
                post_attempts=1,
            )
        except httpx.TransportError:
            observation = CoverageObservation(
                status="PROVIDER_ERROR",
                error_code="TRANSPORT_ERROR",
                contract_identity=identity,
                post_attempts=1,
            )
        observation = CoverageObservation.model_validate(
            {**observation.model_dump(), "latency_ms": (perf_counter() - started) * 1000}
        )
        if contract_identity() != identity:
            return unavailable("CONTRACT_MISMATCH", "INVALID_RESPONSE")
        return result(observation)
