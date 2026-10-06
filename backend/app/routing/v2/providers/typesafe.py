"""Native direct TypeSafe staged adapter. Live calls require explicit opt-in."""

import asyncio
import json
from time import perf_counter
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import ValidationError

from app.routing.providers.typesafe import TypeSafeSettings
from app.routing.v2 import domain as d
from app.routing.v2.observations import (
    AdapterResult,
    StageObservation,
)
from app.routing.v2.preparation import prepare, PreparedEnvelope, PreparationFailure
from app.routing.v2.questions import (
    stage1_questions,
    stage2_questions,
    CRITERIA_VERSION,
    QUESTION_SCHEMA_VERSION,
)
from app.routing.v2.translation import translate
from app.routing.v2.wire import parse_stage
from app.routing.v2.options import generate_options
from app.routing.v2.observations import Stage1Checkpoint, DebugCounts
from app.routing.v2.checkpoints import make_checkpoint, reuse_stage1, write_checkpoint
from app.routing.v2.contracts import source_hashes, verify_lock


MAX_STAGE2_QUESTIONS_BYTES = 40000
MAX_REQUEST_BYTES = 48000
MAX_STATE_AND_QUESTION_BYTES = 24000


def request_size(envelope: PreparedEnvelope, questions: dict[str, dict[str, Any]]) -> int:
    return len(
        json.dumps(
            {"model": "jev-latest", "state": envelope.provider_state(), "questions": questions},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    )


def request_fits(envelope: PreparedEnvelope, questions: dict[str, dict[str, Any]]) -> bool:
    state = envelope.provider_state()

    def size(value: object) -> int:
        return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())

    return size(
        {"model": "jev-latest", "state": state, "questions": questions}
    ) <= MAX_REQUEST_BYTES and all(
        size({"state": state, "question": question}) <= MAX_STATE_AND_QUESTION_BYTES
        for question in questions.values()
    )


class TypeSafeV2Router:
    """Only evaluation/shadow callers may opt in; no automatic retries."""

    def __init__(self, settings: TypeSafeSettings, client: httpx.AsyncClient | None = None) -> None:
        if settings.typesafe_base_url != "https://api.typesafe.ai":
            raise ValueError("V2 experiment requires direct TypeSafe origin")
        self.settings = settings
        self.client = client

    async def stage(
        self,
        envelope: PreparedEnvelope,
        questions: dict[str, dict[str, Any]],
        stage: Literal[1, 2],
        *,
        execute: bool,
    ) -> StageObservation:
        key = self.settings.typesafe_api_key.get_secret_value().strip()
        if not execute or not key:
            return StageObservation(stage=stage, status="PROVIDER_ERROR", error_code="UNAVAILABLE")
        started = perf_counter()
        try:

            async def post(client: httpx.AsyncClient) -> httpx.Response:
                return await client.post(
                    self.settings.typesafe_base_url + "/v1/systemone",
                    json={
                        "model": self.settings.typesafe_model,
                        "state": envelope.provider_state(),
                        "questions": questions,
                    },
                    headers={"Authorization": "Bearer " + key},
                    timeout=self.settings.typesafe_timeout_seconds,
                    follow_redirects=False,
                )

            async def send() -> httpx.Response:
                if self.client is not None:
                    return await post(self.client)
                async with httpx.AsyncClient(trust_env=False) as client:
                    return await post(client)

            response = await asyncio.wait_for(
                send(), timeout=self.settings.typesafe_timeout_seconds
            )
            base = {"stage": stage, "http_status": response.status_code, "post_attempts": 1}
            if response.status_code != 200:
                code = (
                    "AUTH_ERROR"
                    if response.status_code == 401
                    else "RATE_LIMITED"
                    if response.status_code == 429
                    else "HTTP_ERROR"
                )
                return StageObservation.model_validate(
                    {
                        **base,
                        "status": "PROVIDER_ERROR",
                        "error_code": code,
                        "latency_ms": (perf_counter() - started) * 1000,
                    }
                )
            if len(response.content) > 1000000:
                return StageObservation.model_validate(
                    {
                        **base,
                        "status": "INVALID_RESPONSE",
                        "error_code": "RESPONSE_TOO_LARGE",
                        "latency_ms": (perf_counter() - started) * 1000,
                    }
                )
            try:
                data = response.json()
            except ValueError:
                return StageObservation.model_validate(
                    {
                        **base,
                        "status": "INVALID_RESPONSE",
                        "error_code": "JSON_INVALID",
                        "latency_ms": (perf_counter() - started) * 1000,
                    }
                )
            observation = parse_stage(data, questions, stage, http_status=200)
            return StageObservation.model_validate(
                {**observation.model_dump(), "latency_ms": (perf_counter() - started) * 1000}
            )
        except (TimeoutError, httpx.TimeoutException):
            code = "TIMEOUT"
        except httpx.TransportError:
            code = "TRANSPORT_ERROR"
        return StageObservation.model_validate(
            {
                "stage": stage,
                "status": "PROVIDER_ERROR",
                "error_code": code,
                "post_attempts": 1,
                "latency_ms": (perf_counter() - started) * 1000,
            }
        )

    async def route(
        self,
        question: str,
        state: d.ConversationState | None = None,
        *,
        execute: bool = False,
        resume: Stage1Checkpoint | None = None,
        checkpoint_path: Path | None = None,
    ) -> AdapterResult:
        envelope = prepare(question, state)
        if isinstance(envelope, PreparationFailure):
            return AdapterResult(status="PREPARATION_ERROR", error_code=envelope.reason)
        return await self.interpret(
            envelope, execute=execute, resume=resume, checkpoint_path=checkpoint_path
        )

    async def interpret(
        self,
        envelope: PreparedEnvelope,
        *,
        execute: bool = False,
        resume: Stage1Checkpoint | None = None,
        checkpoint_path: Path | None = None,
    ) -> AdapterResult:
        try:
            envelope = PreparedEnvelope.model_validate_json(envelope.model_dump_json())
        except ValidationError:
            return AdapterResult(status="PREPARATION_ERROR", error_code="INVALID_ENVELOPE")
        if not verify_lock():
            return AdapterResult(status="PREPARATION_ERROR", error_code="CONTRACT_LOCK_MISMATCH")
        frozen = source_hashes()
        registry = generate_options(envelope)
        if isinstance(registry, PreparationFailure):
            return AdapterResult(
                status="PREPARATION_ERROR",
                error_code=registry.reason,
                debug_counts=DebugCounts(
                    spans=registry.span_count,
                    candidates=registry.candidate_count,
                    bindings=registry.binding_count,
                    options=registry.option_count,
                    stage2_question_bytes=0,
                ),
            )
        first_questions = stage1_questions()
        counts = {
            "spans": len(envelope.spans),
            "candidates": len(envelope.input.candidates),
            "bindings": len(envelope.bindings),
            "options": len(registry.options),
        }
        if not request_fits(envelope, first_questions):
            return AdapterResult(
                status="PREPARATION_ERROR",
                error_code="REQUEST_SIZE_LIMIT",
                preparation_hash=envelope.identity_hash,
                debug_counts=DebugCounts(
                    **counts,
                    stage2_question_bytes=0,
                    request_bytes=request_size(envelope, first_questions),
                ),
            )
        if resume is not None:
            try:
                first = reuse_stage1(envelope, registry, resume)
            except (ValueError, TypeError, KeyError):
                return AdapterResult(
                    status="DOMAIN_TRANSLATION_ERROR", error_code="STAGE1_CHECKPOINT_MISMATCH"
                )
        else:
            first = await self.stage(envelope, first_questions, 1, execute=execute)
        common: dict[str, Any] = {
            "stages": (first,),
            "preparation_hash": envelope.identity_hash,
            "reused_stage1": resume is not None,
            "debug_counts": DebugCounts(
                **counts,
                stage2_question_bytes=0,
                request_bytes=request_size(envelope, first_questions),
            ),
        }
        if source_hashes() != frozen:
            return AdapterResult(
                **common,
                status="DOMAIN_TRANSLATION_ERROR",
                error_code="CONTRACT_CHANGED_DURING_REQUEST",
            )
        if first.status != "SUCCESS":
            status = (
                "STAGE1_PROVIDER_ERROR"
                if first.status == "PROVIDER_ERROR"
                else "STAGE1_INVALID_RESPONSE"
            )
            return AdapterResult.model_validate(
                {**common, "status": status, "error_code": first.error_code}
            )
        checkpoint = make_checkpoint(envelope, registry, first)
        common["stage1_checkpoint"] = checkpoint
        common["fingerprints"] = checkpoint.fingerprints
        if checkpoint_path is not None:
            try:
                write_checkpoint(checkpoint_path, checkpoint)
            except (OSError, ValueError):
                return AdapterResult(
                    **common, status="DOMAIN_TRANSLATION_ERROR", error_code="CHECKPOINT_WRITE_ERROR"
                )
        selected = first.answers[0].selected
        if selected == "UNINTERPRETABLE":
            return AdapterResult(**common, status="STAGE1_UNINTERPRETABLE")
        if selected == "OVER_LIMIT":
            unsupported = d.UnsupportedRequest(
                reason=d.UnsupportedReason.REQUEST_LIMIT,
                input_span=d.InputSpan(start=0, end=len(envelope.input.question)),
            )
            return AdapterResult(
                **common,
                status="STAGE1_OVER_LIMIT",
                interpretation=d.BoundInterpretation(
                    input=envelope.input, interpretation=unsupported
                ),
            )
        count = {"ONE": 1, "TWO": 2, "THREE": 3}[selected]
        second_questions = stage2_questions(registry, count)
        size = len(json.dumps(second_questions, ensure_ascii=False, separators=(",", ":")).encode())
        common["debug_counts"] = DebugCounts(
            **counts,
            stage2_question_bytes=size,
            request_bytes=request_size(envelope, second_questions),
        )
        if size > MAX_STAGE2_QUESTIONS_BYTES or not request_fits(envelope, second_questions):
            return AdapterResult(
                **common, status="PREPARATION_ERROR", error_code="REQUEST_SIZE_LIMIT"
            )
        second = await self.stage(envelope, second_questions, 2, execute=execute)
        common["stages"] = (first, second)
        if source_hashes() != frozen:
            return AdapterResult(
                **common,
                status="DOMAIN_TRANSLATION_ERROR",
                error_code="CONTRACT_CHANGED_DURING_REQUEST",
            )
        if second.status != "SUCCESS":
            status = (
                "STAGE2_PROVIDER_ERROR"
                if second.status == "PROVIDER_ERROR"
                else "STAGE2_INVALID_RESPONSE"
            )
            return AdapterResult.model_validate(
                {**common, "status": status, "error_code": second.error_code}
            )
        result = translate(envelope, registry, count, second.answers)
        return AdapterResult.model_validate({**result.model_dump(), **common})

    @property
    def criteria_version(self) -> str:
        return CRITERIA_VERSION

    @property
    def question_schema_version(self) -> str:
        return QUESTION_SCHEMA_VERSION
