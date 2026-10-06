"""Native Jev HTTP adapter, used exclusively by offline/shadow evaluation."""

import asyncio
import hashlib
import json
import math
import re
from time import perf_counter
from typing import Any
from urllib.parse import urlsplit, urljoin

import httpx
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import BACKEND_ROOT, REPO_ROOT
from app.routing.contract import Capability, ClarificationReason, Operation, RoutingMode
from app.routing.providers.jev_criteria import CONTEXT_VERSION, CRITERIA_VERSION, questions
from app.routing.semantic import (
    AssemblyDiagnostics,
    DecisionAnswer,
    ObservationStatus,
    ProviderObservation,
    RoutingInput,
    SemanticPrediction,
    SemanticRequest,
)


class JevSettings(BaseSettings):
    """Separate settings so production configuration is unchanged."""

    jev_api_key: SecretStr = Field(default=SecretStr(""), exclude=True)
    jev_base_url: str = "https://jev-ai.org/api/v1"
    jev_model: str = "jev-1.13"
    jev_timeout_seconds: float = Field(default=15, gt=0, le=60)
    model_config = SettingsConfigDict(
        env_file=(str(REPO_ROOT / ".env"), str(BACKEND_ROOT / ".env")),
        extra="ignore",
        env_ignore_empty=True,
    )

    @field_validator("jev_model")
    @classmethod
    def pinned_model(cls, value: str) -> str:
        if value != "jev-1.13":
            raise ValueError("Only pinned jev-1.13 is supported in this experiment")
        return value

    @field_validator("jev_base_url")
    @classmethod
    def safe_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Jev base URL must be HTTPS without credentials/query/fragment")
        return value.rstrip("/")


def serialize_state(request: RoutingInput) -> tuple[dict[str, Any], bool]:
    history: list[dict[str, str]] = []
    remaining = 6000
    truncated = len(request.history) > 6
    for turn in reversed(request.history[-6:]):
        if set(turn) != {"role", "text"} or turn["role"] not in ("user", "assistant"):
            raise ValueError("Invalid history turn")
        text = turn["text"][: min(2000, remaining)]
        truncated |= len(text) != len(turn["text"])
        if text:
            history.insert(0, {"role": turn["role"], "text": text})
        remaining -= len(text)
    return {
        "CURRENT QUESTION": request.question,
        "RECENT CONVERSATION CONTEXT": history,
        "history_window_complete": request.history_window_complete and not truncated,
        "history_truncated": truncated,
    }, truncated


def idempotency_key(dataset_version: str, case_id: str, model: str, request: RoutingInput) -> str:
    state, _ = serialize_state(request)
    material = [
        dataset_version,
        case_id,
        CRITERIA_VERSION,
        model,
        CONTEXT_VERSION,
        state,
        questions(),
    ]
    digest = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
    return "drivemind-routing:" + digest


def probability(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Probability must be numeric")
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("Invalid probability")
    return float(value)


def parse_answers(raw: Any, *, rounding_aware: bool = False) -> dict[str, DecisionAnswer]:
    specs = questions()
    if not isinstance(raw, dict) or set(raw) != set(specs):
        raise ValueError("Answer IDs do not match")
    parsed = {}
    for name, spec in specs.items():
        answer = raw[name]
        if not isinstance(answer, dict) or answer.get("type") != spec["type"]:
            raise ValueError("Invalid answer type")
        if spec["type"] == "noul":
            parsed[name] = DecisionAnswer(noul=probability(answer.get("noul")))
            continue
        distribution = answer.get("probabilities")
        options = spec["criteria"]
        if not isinstance(distribution, dict) or set(distribution) != set(options):
            raise ValueError("Invalid distribution labels")
        distribution = {key: probability(value) for key, value in distribution.items()}
        selected = answer.get("choice")
        if not isinstance(selected, str) or selected not in options:
            raise ValueError("Invalid selected label")
        if rounding_aware:
            from app.routing.providers.probability_validation import validate_distribution

            validate_distribution(distribution, selected)
        else:
            if not math.isclose(sum(distribution.values()), 1, abs_tol=1e-5):
                raise ValueError("Distribution is not normalized")
            if distribution[selected] < max(distribution.values()) - 1e-8:
                raise ValueError("Invalid selected label")
        parsed[name] = DecisionAnswer(
            selected=selected,
            probabilities=distribution,
            confidence=probability(answer["confidence"]) if "confidence" in answer else None,
        )
    return parsed


def assemble(answers: dict[str, DecisionAnswer]) -> SemanticPrediction:
    """Only selected mode's required fields determine the domain decision."""
    selected_mode = answers["mode"].selected
    if selected_mode is None:
        raise ValueError("Missing mode")
    mode = RoutingMode(selected_mode)
    if mode == RoutingMode.CLARIFY:
        reason = answers["clarification"].selected
        if reason is None or reason == "NONE":
            raise ValueError("CLARIFY requires a clarification reason")
        return SemanticPrediction(mode=mode, clarification_reason=ClarificationReason(reason))
    count = 1 if mode == RoutingMode.SINGLE else 3
    requests = []
    for index in range(1, count + 1):
        selected = answers[f"operation_{index}"].selected
        if selected == "NONE" and mode == RoutingMode.COMPOUND and index == 3:
            continue
        if selected is None or selected == "NONE":
            raise ValueError("Required operation slot is empty")
        capability, operation = selected.split(":")
        requests.append(
            SemanticRequest(capability=Capability(capability), operation=Operation(operation))
        )
    return SemanticPrediction(mode=mode, requests=tuple(requests))


def assembly_diagnostics(
    answers: dict[str, DecisionAnswer], prediction: SemanticPrediction
) -> AssemblyDiagnostics:
    """Auxiliary disagreement is observational, never an execution threshold."""
    relevant = ["mode"]
    flags = []
    if prediction.mode == RoutingMode.CLARIFY:
        relevant.append("clarification")
        for index in range(1, 4):
            name = f"operation_{index}"
            if answers[name].selected != "NONE":
                flags.append(f"{name}_nonempty_when_clarify")
    else:
        count = 1 if prediction.mode == RoutingMode.SINGLE else 3
        relevant.extend(f"operation_{index}" for index in range(1, count + 1))
        if prediction.mode == RoutingMode.SINGLE:
            for name in ("operation_2", "operation_3"):
                if answers[name].selected != "NONE":
                    flags.append(f"{name}_nonempty_when_single")
        if answers["clarification"].selected != "NONE":
            flags.append("clarification_non_none_when_executable")
    selected_capabilities = {request.capability for request in prediction.requests}
    for capability in Capability:
        value = answers[f"has_{capability.value.lower()}"].noul
        # 0.5 is a diagnostic Bernoulli majority comparison, not a routing cutoff.
        if value is not None and value != 0.5:
            if (value > 0.5) != (capability in selected_capabilities):
                flags.append(f"presence_disagrees:{capability.value}")
    return AssemblyDiagnostics(
        relevant_answer_ids=tuple(relevant),
        unused_answer_ids=tuple(name for name in answers if name not in relevant),
        disagreement_flags=tuple(flags),
    )


def validate_response(data: Any, model: str, base: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate/sanitize provider data and reassemble with current semantics."""
    base = {} if base is None else base
    if not isinstance(data, dict) or data.get("model") != model:
        raise ValueError("Wrong model")
    version = data.get("model_version")
    if not isinstance(version, str) or not re.fullmatch(r"jev-1\.13-[0-9]{8}", version):
        raise ValueError("Invalid model version")
    base["model_version"] = version
    base["answers"] = parse_answers(data.get("answers"))
    usage = data.get("usage", {})
    if not isinstance(usage, dict):
        raise ValueError("Invalid usage")
    sanitized: dict[str, int | str] = {}
    for name in ("input_tokens", "output_tokens", "charged_tokens", "charged_credits"):
        if name in usage:
            value = usage[name]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("Invalid usage count")
            sanitized[name] = value
    if "wallet" in usage:
        if usage["wallet"] not in ("tokens", "credits"):
            raise ValueError("Invalid wallet")
        sanitized["wallet"] = usage["wallet"]
    base["usage"] = sanitized
    if "latency_ms" in data:
        latency = data["latency_ms"]
        if (
            isinstance(latency, bool)
            or not isinstance(latency, (int, float))
            or not math.isfinite(latency)
            or latency < 0
        ):
            raise ValueError("Invalid latency")
        base["upstream_latency_ms"] = latency
    prediction = assemble(base["answers"])
    base["assembly_diagnostics"] = assembly_diagnostics(base["answers"], prediction)
    if "id" in data:
        base["request_id"] = safe_request_id(data["id"])
    base["prediction"] = prediction
    return base


def safe_request_id(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"dec_[a-f0-9]{8,64}", value):
        raise ValueError("Invalid request identity")
    return value


class JevRouter:
    def __init__(self, settings: JevSettings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self.client = client

    async def recover_conflict(
        self, response: httpx.Response, base: dict[str, Any], started: float
    ) -> ProviderObservation:
        """One POST at most; recover through same-origin status GETs only."""
        base["new_model_decisions"] = 0
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Invalid conflict body")
        error = data.get("error", data)
        if not isinstance(error, dict):
            raise ValueError("Invalid conflict error")
        code = error.get("code")
        if code not in (
            "request_already_completed",
            "request_in_progress",
            "idempotency_key_reused",
        ):
            return ProviderObservation(
                status=ObservationStatus.IDEMPOTENCY_CONFLICT,
                latency_ms=(perf_counter() - started) * 1000,
                **base,
            )
        base["idempotency_error"] = code
        if code == "idempotency_key_reused":
            return ProviderObservation(
                status=ObservationStatus.IDEMPOTENCY_CONFLICT,
                latency_ms=(perf_counter() - started) * 1000,
                **base,
            )
        request_id = safe_request_id(error.get("request_id", data.get("request_id")))
        base["request_id"] = request_id
        expected_url = self.settings.jev_base_url + "/requests/" + request_id + "/"
        supplied_url = error.get("status_url", data.get("status_url"))
        if (
            not isinstance(supplied_url, str)
            or urljoin(self.settings.jev_base_url + "/", supplied_url) != expected_url
        ):
            raise ValueError("Unsafe status URL")
        for attempt in range(3):
            remaining = self.settings.jev_timeout_seconds - (perf_counter() - started)
            if remaining <= 0:
                raise TimeoutError()
            base["status_get_attempts"] = base.get("status_get_attempts", 0) + 1

            async def get(client: httpx.AsyncClient) -> httpx.Response:
                return await client.get(
                    expected_url,
                    headers={
                        "Authorization": "Bearer "
                        + self.settings.jev_api_key.get_secret_value().strip()
                    },
                    timeout=remaining,
                    follow_redirects=False,
                )

            async def send() -> httpx.Response:
                if self.client is not None:
                    return await get(self.client)
                async with httpx.AsyncClient(trust_env=False) as client:
                    return await get(client)

            status_response = await asyncio.wait_for(send(), timeout=remaining)
            if status_response.status_code != 200:
                status = {
                    401: ObservationStatus.AUTH_ERROR,
                    402: ObservationStatus.BILLING_ERROR,
                    429: ObservationStatus.RATE_LIMITED,
                }.get(status_response.status_code, ObservationStatus.UNAVAILABLE)
                return ProviderObservation(
                    status=status, latency_ms=(perf_counter() - started) * 1000, **base
                )
            if len(status_response.content) > 1000000:
                raise ValueError("Oversized status response")
            payload = status_response.json()
            if not isinstance(payload, dict):
                raise ValueError("Invalid status response")
            if payload.get("status") in ("queued", "pending", "running", "in_progress"):
                if attempt < 2:
                    await asyncio.sleep(
                        min(
                            1,
                            max(0, self.settings.jev_timeout_seconds - (perf_counter() - started)),
                        )
                    )
                    continue
                return ProviderObservation(
                    status=ObservationStatus.IDEMPOTENCY_CONFLICT,
                    latency_ms=(perf_counter() - started) * 1000,
                    **base,
                )
            # Accept a native decision or a narrow completed-status result envelope.
            decision: Any
            if "answers" in payload:
                decision = payload
            elif payload.get("status") == "completed":
                decision = payload.get("result", payload.get("response"))
            else:
                raise ValueError("Unknown status envelope")
            if isinstance(decision, dict) and "id" in decision and decision["id"] != request_id:
                raise ValueError("Recovered request identity differs")
            validate_response(decision, self.settings.jev_model, base)
            base["recovered_idempotent"] = True
            return ProviderObservation(
                status=ObservationStatus.SUCCESS,
                latency_ms=(perf_counter() - started) * 1000,
                **base,
            )
        raise ValueError("Status polling exhausted")

    async def route(self, request: RoutingInput, *, idempotency_key: str) -> ProviderObservation:
        state, truncated = serialize_state(request)
        base: dict[str, Any] = dict(
            provider="jev-ai.org",
            model=self.settings.jev_model,
            criteria_version=CRITERIA_VERSION,
            history_truncated=truncated,
        )
        key = self.settings.jev_api_key.get_secret_value().strip()
        if not key:
            return ProviderObservation(status=ObservationStatus.UNAVAILABLE, **base)
        started = perf_counter()
        base["calls"] = 1
        base["post_attempts"] = 1
        base["new_model_decisions"] = None
        try:

            async def call(client: httpx.AsyncClient) -> httpx.Response:
                return await client.post(
                    self.settings.jev_base_url + "/systemone/",
                    json={
                        "model": self.settings.jev_model,
                        "state": state,
                        "questions": questions(),
                    },
                    headers={"Authorization": "Bearer " + key, "Idempotency-Key": idempotency_key},
                    timeout=self.settings.jev_timeout_seconds,
                    follow_redirects=False,
                )

            async def send() -> httpx.Response:
                if self.client is not None:
                    return await call(self.client)
                async with httpx.AsyncClient(trust_env=False) as client:
                    return await call(client)

            response = await asyncio.wait_for(send(), timeout=self.settings.jev_timeout_seconds)
            base["http_status"] = response.status_code
            if response.status_code == 409:
                return await self.recover_conflict(response, base, started)
            if response.status_code != 200:
                base["new_model_decisions"] = 0
                status = {
                    401: ObservationStatus.AUTH_ERROR,
                    402: ObservationStatus.BILLING_ERROR,
                    429: ObservationStatus.RATE_LIMITED,
                    409: ObservationStatus.IDEMPOTENCY_CONFLICT,
                    504: ObservationStatus.TIMEOUT,
                }.get(
                    response.status_code,
                    ObservationStatus.UNAVAILABLE
                    if response.status_code >= 500
                    else ObservationStatus.INVALID_RESPONSE,
                )
                return ProviderObservation(
                    status=status, latency_ms=(perf_counter() - started) * 1000, **base
                )
            if len(response.content) > 1000000:
                raise ValueError("Oversized response")
            base["new_model_decisions"] = 1
            data = response.json()
            # Preserve validated raw fields even if assembly fails (legacy recovery).
            sanitized = validate_response(data, self.settings.jev_model, base)
            base.update(sanitized)
            return ProviderObservation(
                status=ObservationStatus.SUCCESS,
                latency_ms=(perf_counter() - started) * 1000,
                **base,
            )
        except (TimeoutError, httpx.TimeoutException):
            status = ObservationStatus.TIMEOUT
        except httpx.TransportError:
            status = ObservationStatus.UNAVAILABLE
        except (ValueError, TypeError, KeyError):
            status = ObservationStatus.INVALID_RESPONSE
        # Never retain external error bodies, exception messages, headers, or credentials.
        return ProviderObservation(
            status=status, latency_ms=(perf_counter() - started) * 1000, **base
        )
