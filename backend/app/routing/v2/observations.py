"""Provider observations intentionally separate from semantic request schemas."""

from typing import Literal
from pydantic import Field, StrictInt, model_validator

from app.routing.v2 import domain as d


class ChoiceObservation(d.DomainModel):
    answer_id: str
    selected: str
    probabilities: tuple[tuple[str, float], ...]
    confidence: float

    def distribution(self) -> dict[str, float]:
        return dict(self.probabilities)


class TokenUsage(d.DomainModel):
    input_tokens: StrictInt | None = Field(default=None, ge=0)
    output_tokens: StrictInt | None = Field(default=None, ge=0)


class StageObservation(d.DomainModel):
    stage: Literal[1, 2]
    requested_model: Literal["jev-latest"] = "jev-latest"
    returned_model: Literal["jev-latest", "jev-1.13.0"] | None = None
    status: Literal["SUCCESS", "PROVIDER_ERROR", "INVALID_RESPONSE"]
    error_code: (
        Literal[
            "AUTH_ERROR",
            "RATE_LIMITED",
            "HTTP_ERROR",
            "TIMEOUT",
            "TRANSPORT_ERROR",
            "UNAVAILABLE",
            "JSON_INVALID",
            "INVALID_BODY",
            "MODEL_INVALID",
            "ANSWER_IDS_INVALID",
            "ANSWER_INVALID",
            "USAGE_INVALID",
            "RESPONSE_TOO_LARGE",
        ]
        | None
    ) = None
    http_status: int | None = None
    latency_ms: float = Field(default=0, ge=0)
    usage: TokenUsage = Field(default_factory=TokenUsage)
    answers: tuple[ChoiceObservation, ...] = ()
    post_attempts: StrictInt = Field(default=0, ge=0, le=1)


class Fingerprint(d.DomainModel):
    name: str
    value: str = Field(pattern=r"^[0-9a-f]{64}$")


class Stage1Checkpoint(d.DomainModel):
    version: Literal["v2-stage1-checkpoint-1.0"] = "v2-stage1-checkpoint-1.0"
    identity_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    fingerprints: tuple[Fingerprint, ...]
    response_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    observation: StageObservation


class DebugCounts(d.DomainModel):
    spans: StrictInt = Field(ge=0)
    candidates: StrictInt = Field(ge=0)
    bindings: StrictInt = Field(ge=0)
    options: StrictInt = Field(ge=0)
    stage2_question_bytes: StrictInt = Field(ge=0)
    request_bytes: StrictInt = Field(default=0, ge=0)


class SemanticAmbiguitySignal(d.DomainModel):
    kind: Literal["semantic_ambiguity_signal"] = "semantic_ambiguity_signal"
    request_positions: tuple[StrictInt, ...] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def valid_positions(self) -> "SemanticAmbiguitySignal":
        if any(p not in (1, 2, 3) for p in self.request_positions) or len(
            set(self.request_positions)
        ) != len(self.request_positions):
            raise ValueError("invalid ambiguity positions")
        return self


class AdapterResult(d.DomainModel):
    criteria_version: Literal["jev-v2-atomic-criteria-2.0"] = "jev-v2-atomic-criteria-2.0"
    question_schema_version: Literal["v2-atomic-requests-2.1"] = "v2-atomic-requests-2.1"
    status: Literal[
        "SUCCESS",
        "PREPARATION_ERROR",
        "STAGE1_PROVIDER_ERROR",
        "STAGE1_INVALID_RESPONSE",
        "STAGE1_UNINTERPRETABLE",
        "STAGE1_OVER_LIMIT",
        "STAGE2_PROVIDER_ERROR",
        "STAGE2_INVALID_RESPONSE",
        "BINDING_VALIDATION_ERROR",
        "DOMAIN_TRANSLATION_ERROR",
        "SEMANTIC_AMBIGUITY",
    ]
    interpretation: d.BoundInterpretation | None = None
    stages: tuple[StageObservation, ...] = Field(default=(), max_length=2)
    preparation_hash: str | None = None
    error_code: str | None = None
    semantic_signal: SemanticAmbiguitySignal | None = None
    source_overlaps: tuple[tuple[int, int], ...] = ()
    stage1_checkpoint: Stage1Checkpoint | None = None
    reused_stage1: bool = False
    fingerprints: tuple[Fingerprint, ...] = ()
    debug_counts: DebugCounts | None = None
    request_position: StrictInt | None = Field(default=None, ge=1, le=3)

    @model_validator(mode="after")
    def valid_result(self) -> "AdapterResult":
        if (self.status == "SEMANTIC_AMBIGUITY") != (self.semantic_signal is not None):
            raise ValueError("explicit ambiguity must carry a non-executable signal")
        if self.status == "SUCCESS" and self.interpretation is None:
            raise ValueError("successful translation requires a domain interpretation")
        if self.status not in ("SUCCESS", "STAGE1_OVER_LIMIT") and self.interpretation is not None:
            raise ValueError("failure cannot carry a repaired domain interpretation")
        if self.status == "STAGE1_OVER_LIMIT" and (
            self.interpretation is None
            or not isinstance(self.interpretation.interpretation, d.UnsupportedRequest)
            or self.interpretation.interpretation.reason != d.UnsupportedReason.REQUEST_LIMIT
        ):
            raise ValueError("over-limit must remain an unsupported limit outcome")
        if tuple(stage.stage for stage in self.stages) != tuple(range(1, len(self.stages) + 1)):
            raise ValueError("stage observations must be ordered")
        return self

    def telemetry_record(self, *, include_synthetic_domain: bool = False) -> dict[str, object]:
        """Safe artifact default: no raw user/private domain input."""
        record = self.model_dump(
            mode="json", exclude=set() if include_synthetic_domain else {"interpretation"}
        )
        record["new_post_attempts"] = self.new_post_attempts
        record["represented_usage"] = self.total_usage.model_dump()
        if self.stages and self.stages[0].status == "SUCCESS":
            answer = self.stages[0].answers[0]
            values = sorted(answer.distribution().values(), reverse=True)
            record["cardinality"] = {
                "selected": answer.selected,
                "selected_probability": answer.distribution()[answer.selected],
                "top_two_margin": values[0] - values[1],
            }
        return record

    @property
    def new_post_attempts(self) -> int:
        return sum(
            stage.post_attempts
            for stage in self.stages
            if not (stage.stage == 1 and self.reused_stage1)
        )

    @property
    def total_usage(self) -> TokenUsage:
        # Missing counts stay unknown, not silently converted to zero.
        def total(name: str) -> int | None:
            counts = [
                stage.usage.input_tokens if name == "input_tokens" else stage.usage.output_tokens
                for stage in self.stages
            ]
            return (
                sum(c for c in counts if c is not None)
                if counts and all(c is not None for c in counts)
                else None
            )

        return TokenUsage(input_tokens=total("input_tokens"), output_tokens=total("output_tokens"))
