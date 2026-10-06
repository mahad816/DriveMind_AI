"""Held-out v2 gold data and offline resolver validation. No provider execution."""

import hashlib
import re
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.routing.v2 import domain as d
from app.routing.v2 import resolved as r
from app.routing.v2.contracts import verify_lock
from app.routing.v2.preparation import prepare, PreparedEnvelope
from app.routing.v2.resolver import resolve

ROOT = Path(__file__).parent / "datasets"
LOCK_SHA = "8b85ec5fb3b0bd541d6eba59bb09af00eb96fcbc6c91ef000550dda75efef9c4"
OPS = {
    "FILE_INVENTORY": {"LIST", "COUNT", "LATEST", "OLDEST"},
    "FILE_TARGET": {"SUMMARIZE", "ANSWER_QUESTION"},
    "COLLECTION_SUMMARY": {"SUMMARIZE_EACH"},
    "GROUNDED_RAG": {"ANSWER"},
    "CONVERSATION_HISTORY": {"RECALL"},
    "CHITCHAT": {"RESPOND"},
}


class GoldReference(d.DomainModel):
    kind: Literal[
        "collection",
        "literal",
        "selector",
        "context_file",
        "context_topic",
        "history",
        "original_query",
        "social",
        "unspecified",
    ]
    context_kind: d.FileContextKind | None = None
    name: str | None = Field(default=None, min_length=1, max_length=1024)
    selector: d.ReferenceSelector | None = None
    role: Literal["user", "assistant"] | None = None
    relative_position: int | None = Field(default=None, ge=1, le=6)

    @model_validator(mode="after")
    def valid(self) -> "GoldReference":
        if (self.context_kind is not None) != (self.kind == "context_file"):
            raise ValueError("context reference kind mismatch")
        if (self.name is not None) != (self.kind == "literal") or (self.selector is not None) != (
            self.kind == "selector"
        ):
            raise ValueError("reference argument mismatch")
        if (self.role is not None and self.relative_position is not None) != (
            self.kind == "history"
        ) or (
            self.kind != "history" and (self.role is not None or self.relative_position is not None)
        ):
            raise ValueError("history argument mismatch")
        return self


class GoldReadiness(d.DomainModel):
    status: Literal["READY", "NEEDS_CLARIFICATION", "UNSUPPORTED"]
    detail: str | None = None
    file_id: UUID | None = None
    message_text: str | None = None

    @model_validator(mode="after")
    def valid(self) -> "GoldReadiness":
        if self.status != "READY" and (self.file_id is not None or self.message_text is not None):
            raise ValueError("unready gold cannot resolve an object")
        if self.status == "READY" and self.detail is not None:
            raise ValueError("ready gold cannot carry a failure")
        return self


class GoldRequest(d.DomainModel):
    capability: Literal[
        "FILE_INVENTORY",
        "FILE_TARGET",
        "COLLECTION_SUMMARY",
        "GROUNDED_RAG",
        "CONVERSATION_HISTORY",
        "CHITCHAT",
    ]
    operation: str
    reference: GoldReference
    ordering: Literal["NAME_ASC", "NAME_DESC", "MODIFIED_AT_ASC", "MODIFIED_AT_DESC"] | None = None
    source_ranges: tuple[d.InputSpan, ...] = Field(min_length=1, max_length=3)
    query_ranges: tuple[d.InputSpan, ...] = Field(default=(), max_length=3)
    readiness: GoldReadiness

    @model_validator(mode="after")
    def valid(self) -> "GoldRequest":
        allowed = {
            "FILE_INVENTORY": {"collection"},
            "COLLECTION_SUMMARY": {"collection"},
            "FILE_TARGET": {"literal", "selector", "context_file", "unspecified"},
            "GROUNDED_RAG": {"original_query", "context_topic"},
            "CONVERSATION_HISTORY": {"history"},
            "CHITCHAT": {"social"},
        }
        if (
            self.operation not in OPS[self.capability]
            or self.reference.kind not in allowed[self.capability]
        ):
            raise ValueError("capability/operation/reference mismatch")
        if self.ordering is not None and (self.capability, self.operation) != (
            "FILE_INVENTORY",
            "LIST",
        ):
            raise ValueError("ordering only applies to LIST")
        needs_query = (self.capability, self.operation) == (
            "FILE_TARGET",
            "ANSWER_QUESTION",
        ) or self.reference.kind == "original_query"
        if needs_query != bool(self.query_ranges):
            raise ValueError("query range contract mismatch")
        return self


class RoutingV2Case(d.DomainModel):
    id: str = Field(pattern=r"^v2-[0-9]{3}$")
    question: str = Field(min_length=1, max_length=8000)
    metadata_fixture: str
    state_fixture: str
    cohort: Literal["ONE", "COMPOUND", "SAFETY"]
    expected_cardinality: Literal["ONE", "TWO", "THREE", "OVER_LIMIT", "UNINTERPRETABLE"]
    expected_special: Literal["UNSUPPORTED_OPERATION", "UNINTERPRETABLE", "OVER_LIMIT"] | None = (
        None
    )
    expected_requests: tuple[GoldRequest, ...] = Field(default=(), max_length=3)
    expected_readiness: Literal["READY", "NEEDS_CLARIFICATION", "UNSUPPORTED", "NOT_APPLICABLE"]
    unsupported_reason: d.UnsupportedReason | None = None
    difficulty: Literal[
        "LITERAL", "PARAPHRASE", "BOUNDARY", "CONTEXTUAL", "COMPOUND", "AMBIGUOUS_UNSUPPORTED"
    ]
    tags: tuple[str, ...] = Field(min_length=1)
    notes: str

    @model_validator(mode="after")
    def valid(self) -> "RoutingV2Case":
        if self.expected_special:
            if self.expected_requests or self.expected_readiness not in (
                "UNSUPPORTED",
                "NOT_APPLICABLE",
            ):
                raise ValueError("special outcome is non-executable")
            if (
                self.expected_cardinality in ("OVER_LIMIT", "UNINTERPRETABLE")
                and self.expected_special != self.expected_cardinality
            ):
                raise ValueError("structure special mismatch")
        elif len(self.expected_requests) != {"ONE": 1, "TWO": 2, "THREE": 3}.get(
            self.expected_cardinality
        ):
            raise ValueError("gold cardinality mismatch")
        if len(set(self.tags)) != len(self.tags):
            raise ValueError("duplicate tags")
        for q in self.expected_requests:
            for span in (*q.source_ranges, *q.query_ranges):
                if (
                    span.end > len(self.question)
                    or not self.question[span.start : span.end].strip()
                ):
                    raise ValueError("gold span out of input")
        if self.expected_requests:
            statuses = {q.readiness.status for q in self.expected_requests}
            expected = (
                "UNSUPPORTED"
                if "UNSUPPORTED" in statuses
                else "NEEDS_CLARIFICATION"
                if "NEEDS_CLARIFICATION" in statuses
                else "READY"
            )
            if expected != self.expected_readiness:
                raise ValueError("readiness aggregation mismatch")
        return self


class RoutingV2Dataset(d.DomainModel):
    dataset_id: Literal["routing_v2"]
    schema_version: Literal["routing-v2-gold-1.0"]
    synthetic_only: Literal[True]
    contract_lock_sha256: Literal[
        "8b85ec5fb3b0bd541d6eba59bb09af00eb96fcbc6c91ef000550dda75efef9c4"
    ]
    cases: tuple[RoutingV2Case, ...] = Field(min_length=180, max_length=180)

    @model_validator(mode="after")
    def valid(self) -> "RoutingV2Dataset":
        if tuple(c.id for c in self.cases) != tuple(f"v2-{i:03}" for i in range(1, 181)):
            raise ValueError("IDs must be unique and ordered")
        if len({normalized(c.question) for c in self.cases}) != len(self.cases):
            raise ValueError("duplicate questions")
        return self


class FixtureFile(d.DomainModel):
    file: r.IndexedFile
    visible: bool = True
    indexed: bool = True


class RoutingV2Fixtures(d.DomainModel):
    schema_version: Literal["routing-v2-fixtures-1.0"]
    synthetic_only: Literal[True]
    user_id: UUID
    snapshots: dict[str, tuple[FixtureFile, ...]]
    states: dict[str, d.ConversationState]
    state_notes: dict[str, str]

    @model_validator(mode="after")
    def valid(self) -> "RoutingV2Fixtures":
        if set(self.states) != set(self.state_notes):
            raise ValueError("missing state provenance notes")
        for files in self.snapshots.values():
            if len({f.file.file_id for f in files}) != len(files) or any(
                f.file.user_id != self.user_id for f in files
            ):
                raise ValueError("invalid owned snapshot")
        return self


def normalized(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.casefold()))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load() -> tuple[RoutingV2Dataset, RoutingV2Fixtures]:
    return (
        RoutingV2Dataset.model_validate_json((ROOT / "routing_v2.json").read_text()),
        RoutingV2Fixtures.model_validate_json((ROOT / "routing_v2_fixtures.json").read_text()),
    )


def materialize(case: RoutingV2Case, envelope: PreparedEnvelope) -> d.BoundInterpretation:
    if case.expected_special:
        reason = case.unsupported_reason or d.UnsupportedReason.OPERATION
        return d.BoundInterpretation(
            input=envelope.input,
            interpretation=d.UnsupportedRequest(reason=reason, input_span=envelope.spans[0].span),
        )
    requests: list[d.SemanticRequest] = []
    for gold in case.expected_requests:
        span = gold.source_ranges[0]
        ref = gold.reference

        def candidate(kind: type[d.DomainModel]) -> d.BindingCandidate:
            choices = [c for c in envelope.input.candidates if isinstance(c, kind)]
            if ref.kind == "literal":
                choices = [
                    c
                    for c in choices
                    if isinstance(c.source, d.SourceLocation)
                    and case.question[c.source.start : c.source.end] == ref.name
                ]
            if ref.kind == "selector":
                choices = [
                    c
                    for c in choices
                    if isinstance(c, d.SelectorCandidate) and c.selector == ref.selector
                ]
            if ref.kind == "history":
                choices = [
                    c
                    for c in choices
                    if isinstance(c, d.PriorMessageCandidate)
                    and c.reference.role == ref.role
                    and c.reference.relative_position == ref.relative_position
                ]
            if ref.kind == "context_file":
                choices = [
                    c
                    for c in choices
                    if isinstance(c, d.ContextFileCandidate)
                    and c.reference_kind == ref.context_kind
                ]
            if not choices:
                raise ValueError(f"{case.id}: missing {ref.kind} gold candidate")
            return choices[0]

        request: d.SemanticRequest
        if gold.capability == "FILE_INVENTORY":
            request = d.FileInventoryRequest.model_validate(
                {"input_span": span, "operation": gold.operation, "ordering": gold.ordering}
            )
        elif gold.capability == "COLLECTION_SUMMARY":
            request = d.CollectionSummaryRequest(input_span=span)
        elif gold.capability == "CHITCHAT":
            request = d.ChitchatRequest(input_span=span)
        elif gold.capability == "CONVERSATION_HISTORY":
            c = candidate(d.PriorMessageCandidate)
            assert isinstance(c, d.PriorMessageCandidate)
            request = d.ConversationHistoryRequest(
                input_span=span, candidate_id=c.candidate_id, reference=c.reference
            )
        elif gold.capability == "GROUNDED_RAG":
            query = (
                d.OriginalQuery(span=gold.query_ranges[0])
                if ref.kind == "original_query"
                else d.ContextTopicReference(
                    candidate_id=candidate(d.ContextTopicCandidate).candidate_id
                )
            )
            request = d.GroundedRagRequest(input_span=span, query=query)
        else:
            target: d.FileReference
            if ref.kind == "literal":
                target = d.LiteralMention(
                    candidate_id=candidate(d.LiteralFileCandidate).candidate_id
                )
            elif ref.kind == "selector":
                assert ref.selector is not None
                target = d.MetadataSelector(
                    candidate_id=candidate(d.SelectorCandidate).candidate_id, selector=ref.selector
                )
            elif ref.kind == "context_file":
                c = candidate(d.ContextFileCandidate)
                assert isinstance(c, d.ContextFileCandidate)
                target = d.ContextFileReference(
                    candidate_id=c.candidate_id, reference_kind=c.reference_kind
                )
            else:
                target = d.UnspecifiedFile(
                    candidate_id=candidate(d.UnspecifiedTargetCandidate).candidate_id
                )
            action = (
                d.SummarizeFileRequest(target=target)
                if gold.operation == "SUMMARIZE"
                else d.FileQuestionRequest(target=target, question_span=gold.query_ranges[0])
            )
            request = d.FileTargetRequest(input_span=span, action=action)
        requests.append(request)
    return d.BoundInterpretation(
        input=envelope.input, interpretation=d.RequestedOperations(requests=tuple(requests))
    )


async def validate_gold() -> dict[str, object]:
    dataset, fixtures = load()
    if (
        not verify_lock()
        or sha(Path(__file__).parents[1] / "app/routing/v2/CONTRACT_LOCK.json") != LOCK_SHA
    ):
        raise ValueError("frozen router contract mismatch")
    for case in dataset.cases:
        if (
            case.metadata_fixture not in fixtures.snapshots
            or case.state_fixture not in fixtures.states
        ):
            raise ValueError("unknown fixture")
        state = fixtures.states[case.state_fixture]
        envelope = prepare(case.question, state)
        if not isinstance(envelope, PreparedEnvelope):
            raise ValueError(f"{case.id}: preparation {envelope.reason}")
        value = materialize(case, envelope)
        files = fixtures.snapshots[case.metadata_fixture]

        class Metadata:
            async def list_visible_indexed_files(self, user_id: UUID) -> tuple[r.IndexedFile, ...]:
                return tuple(
                    f.file for f in files if f.visible and f.indexed and f.file.user_id == user_id
                )

        report = await resolve(
            value,
            trusted_input=envelope.input,
            state=state,
            user_id=fixtures.user_id,
            metadata=Metadata(),
        )
        if not isinstance(report, r.ResolutionReport) or report.status != case.expected_readiness:
            raise ValueError(f"{case.id}: readiness does not match authored gold")
        if case.expected_special:
            continue
        for gold, outcome in zip(case.expected_requests, report.outcomes, strict=True):
            if outcome.status != gold.readiness.status:
                raise ValueError(f"{case.id}: request readiness mismatch")
            payload = outcome.model_dump(mode="json")
            if (
                gold.readiness.detail
                and payload.get("detail", payload.get("reason")) != gold.readiness.detail
            ):
                raise ValueError(f"{case.id}: readiness reason mismatch")
            if gold.readiness.file_id:
                resolved = payload.get("resolved", {})
                file = resolved.get("action", {}).get("file", resolved.get("selected_file", {}))
                if file.get("file_id") != str(gold.readiness.file_id):
                    raise ValueError(f"{case.id}: resolved file mismatch")
            if (
                gold.readiness.message_text
                and payload["resolved"]["message"]["text"] != gold.readiness.message_text
            ):
                raise ValueError(f"{case.id}: history target mismatch")
    return {"cases_validated": len(dataset.cases), "provider_calls": 0}
