"""Provider-independent observations for shadow evaluation, never execution."""

from enum import StrEnum
from typing import Protocol

from pydantic import Field

from app.routing.contract import (
    Capability,
    ClarificationReason,
    Operation,
    RoutingMode,
    StrictModel,
)


class ObservationStatus(StrEnum):
    SUCCESS = "SUCCESS"
    TIMEOUT = "TIMEOUT"
    UNAVAILABLE = "UNAVAILABLE"
    AUTH_ERROR = "AUTH_ERROR"
    BILLING_ERROR = "BILLING_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"


class RoutingInput(StrictModel):
    question: str = Field(min_length=1, max_length=8000)
    history: tuple[dict[str, str], ...] = ()
    history_window_complete: bool = False


class SemanticRequest(StrictModel):
    capability: Capability
    operation: Operation | None = None


class SemanticPrediction(StrictModel):
    mode: RoutingMode
    requests: tuple[SemanticRequest, ...] = ()
    clarification_reason: ClarificationReason | None = None


class DecisionAnswer(StrictModel):
    selected: str | None = None
    probabilities: dict[str, float] = Field(default_factory=dict)
    confidence: float | None = None
    noul: float | None = None


class AssemblyDiagnostics(StrictModel):
    relevant_answer_ids: tuple[str, ...] = ()
    unused_answer_ids: tuple[str, ...] = ()
    disagreement_flags: tuple[str, ...] = ()


class ProviderObservation(StrictModel):
    status: ObservationStatus
    provider: str
    model: str
    model_version: str | None = None
    criteria_version: str
    prediction: SemanticPrediction | None = None
    answers: dict[str, DecisionAnswer] = Field(default_factory=dict)
    assembly_diagnostics: AssemblyDiagnostics | None = None
    usage: dict[str, int | str] = Field(default_factory=dict)
    latency_ms: float = 0
    upstream_latency_ms: float | None = None
    http_status: int | None = None
    calls: int = 0
    history_truncated: bool = False
    request_id: str | None = None
    idempotency_error: str | None = None
    post_attempts: int = 0
    status_get_attempts: int = 0
    new_model_decisions: int | None = 0
    recovered_idempotent: bool = False
    provenance: dict[str, str] = Field(default_factory=dict)


class SemanticRouter(Protocol):
    async def route(
        self, request: RoutingInput, *, idempotency_key: str
    ) -> ProviderObservation: ...
