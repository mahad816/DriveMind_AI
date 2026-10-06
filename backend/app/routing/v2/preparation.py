"""Bounded structural candidate preparation; no routing or metadata lookup."""

import hashlib
import json
import re
from typing import Literal, cast

from pydantic import Field, model_validator, ValidationError

from app.routing.v2 import domain as d
from app.routing.v2.state import RoutingConversationState
from app.routing.v2.resolved import ResolvedFileTargetRequest

PREPARATION_VERSION = "v2-preparation-2.1"
MAX_SPANS = 8
MAX_CANDIDATES = 32
MAX_BINDINGS = 64
MAX_CONTEXT_CHARS = 4000
# Structural occurrences, never filename existence or capability signals.
QUOTED = re.compile(r"""(?<!\w)(?:"([^"\n]+)"|'([^'\n]+)'|“([^”\n]+)”|‘([^’\n]+)’)""")
FILENAME = re.compile(r"(?<![\w./\\])[^\s\"'“”‘’,;:!?()<>/\\]+\.[A-Za-z0-9]{1,12}(?![\w])")
SELECTORS = re.compile(r"\b(most recent|latest|newest|oldest|earliest)\b", re.IGNORECASE)
CONTEXT_FILE = re.compile(
    r"\b(previous document|previous file|this file|this document|that file|that document|it|that)\b",
    re.IGNORECASE,
)
RUNTIME_RESULT = re.compile(
    r"\b(?:the (?:first|second) (?:one|result)|the file you just listed|the result you just found)\b",
    re.IGNORECASE,
)
BOUNDARY = re.compile(r"\band\b|\bthen\b|\balso\b|[;\n]|\.(?=\s|$)", re.IGNORECASE)


class PreparationFailure(d.DomainModel):
    span_count: int = Field(default=0, ge=0)
    candidate_count: int = Field(default=0, ge=0)
    binding_count: int = Field(default=0, ge=0)
    option_count: int = Field(default=0, ge=0)
    serialized_size: int = Field(default=0, ge=0)
    status: Literal["PREPARATION_ERROR"] = "PREPARATION_ERROR"
    reason: Literal[
        "INVALID_INPUT",
        "CANDIDATE_LIMIT",
        "BINDING_LIMIT",
        "SPAN_LIMIT_EXCEEDED",
        "OPTION_LIMIT_EXCEEDED",
        "REQUEST_SIZE_LIMIT",
    ]


class PreparedBinding(d.DomainModel):
    label: str = Field(pattern=r"^B[0-9]{3}$")
    candidate_id: d.CandidateId
    request_span: d.InputSpan


class PreparedSpan(d.DomainModel):
    span_id: str = Field(pattern=r"^S[0-9]{3}$")
    span: d.InputSpan


class SafeContext(d.DomainModel):
    handle: Literal[
        "ACTIVE_FILE_CONTEXT",
        "MULTIPLE_ACTIVE_FILES",
        "ACTIVE_TOPIC",
        "LAST_USER_MESSAGE",
        "LAST_ASSISTANT_ANSWER",
        "LAST_SUBSTANTIVE_REQUEST",
    ]
    description: str = Field(max_length=2000)


class PreparedEnvelope(d.DomainModel):
    version: Literal["v2-preparation-2.1"] = "v2-preparation-2.1"
    input: d.PreparedInput
    spans: tuple[PreparedSpan, ...] = Field(min_length=1, max_length=MAX_SPANS)
    context_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    bindings: tuple[PreparedBinding, ...] = Field(min_length=1, max_length=MAX_BINDINGS)
    context: tuple[SafeContext, ...] = Field(default=(), max_length=12)
    context_truncated: bool = False

    @model_validator(mode="after")
    def consistent(self) -> "PreparedEnvelope":
        if len({s.span_id for s in self.spans}) != len(self.spans) or len(
            {(s.span.start, s.span.end) for s in self.spans}
        ) != len(self.spans):
            raise ValueError("duplicate source spans")
        if self.spans[0].span != d.InputSpan(start=0, end=len(self.input.question)):
            raise ValueError("entire original question span is required")
        for span in self.spans:
            self.input.validate_span(span.span)
        ids = {c.candidate_id for c in self.input.candidates}
        if len({b.label for b in self.bindings}) != len(self.bindings):
            raise ValueError("duplicate binding labels")
        for binding in self.bindings:
            if binding.candidate_id not in ids:
                raise ValueError("binding candidate missing")
            self.input.validate_span(binding.request_span)
        if sum(len(c.description) for c in self.context) > MAX_CONTEXT_CHARS:
            raise ValueError("provider context exceeds bounds")
        return self

    @property
    def identity_hash(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()

    def provider_state(self) -> dict[str, object]:
        registry = {c.candidate_id: c for c in self.input.candidates}
        options = []
        for binding in self.bindings:
            candidate = registry[binding.candidate_id]
            source = candidate.source
            display = (
                self.input.question[source.start : source.end]
                if isinstance(source, d.SourceLocation)
                and isinstance(
                    candidate, (d.LiteralFileCandidate, d.SelectorCandidate, d.ContextFileCandidate)
                )
                else ""
            )
            options.append(
                {
                    "label": binding.label,
                    "kind": candidate.kind,
                    "request_span": binding.request_span.model_dump(),
                    "literal_or_selector_text": display,
                    "reference": candidate.model_dump(mode="json"),
                }
            )
        return {
            "CURRENT_QUESTION": self.input.question,
            "SOURCE_SPANS": [s.model_dump(mode="json") for s in self.spans],
            "UNTRUSTED_RECENT_CONTEXT": [c.model_dump() for c in self.context],
            "BINDING_CANDIDATES": options,
            "CONTEXT_TRUNCATED": self.context_truncated,
        }


def source_units(
    question: str, protected: tuple[d.InputSpan, ...], references: tuple[d.InputSpan, ...] = ()
) -> tuple[d.InputSpan, ...]:
    """Expose full text and punctuation/conjunction spans; do not declare tasks."""
    cuts = [
        m
        for m in BOUNDARY.finditer(question)
        if not any(p.start <= m.start() < p.end for p in protected)
    ]
    ranges = [(0, len(question))]
    cursor = 0
    for cut in cuts:
        ranges.append((cursor, cut.start()))
        cursor = cut.end()
    ranges.append((cursor, len(question)))
    spans = [d.InputSpan(start=0, end=len(question))]
    ranges.extend((p.start, p.end) for p in references)
    for start, end in ranges:
        while start < end and question[start].isspace():
            start += 1
        while end > start and question[end - 1].isspace():
            end -= 1
        if start < end:
            span = d.InputSpan(start=start, end=end)
            if span not in spans:
                spans.append(span)
    return tuple(spans)


def safe_context(state: d.ConversationState) -> tuple[tuple[SafeContext, ...], bool]:
    entries: list[tuple[str, str]] = []
    if state.active_file_ids:
        handle = (
            "ACTIVE_FILE_CONTEXT" if len(state.active_file_ids) == 1 else "MULTIPLE_ACTIVE_FILES"
        )
        entries.append(
            (
                handle,
                f"{len(state.active_file_ids)} contextual file reference(s). Resolver must revalidate existence/eligibility; no names or IDs supplied.",
            )
        )
    topics = (
        state.active_topics
        if isinstance(state, RoutingConversationState)
        else (() if state.active_topic is None else (state.active_topic,))
    )
    if topics:
        entries.append(
            (
                "ACTIVE_TOPIC",
                f"{len(topics)} prior grounded topic context(s), resolved downstream; no private topic text supplied.",
            )
        )
    for role in ("user", "assistant"):
        count = sum(m.role == role for m in state.recent_messages)
        if count:
            entries.append(
                (
                    "LAST_USER_MESSAGE" if role == "user" else "LAST_ASSISTANT_ANSWER",
                    f"{count} bounded prior {role} messages available; content withheld.",
                )
            )
    previous = state.last_substantive_request
    if previous:
        value = previous.interpretation
        labels = (
            [f"{q.capability}:{q.operation}" for q in value.requests]
            if isinstance(value, d.RequestedOperations)
            else [value.kind]
        )
        entries.append(("LAST_SUBSTANTIVE_REQUEST", json.dumps(labels)))
    result = []
    truncated = False
    budget = MAX_CONTEXT_CHARS
    for handle, description in entries:
        size = min(len(description), 1000, budget)
        truncated |= size < len(description)
        if size:
            result.append(
                SafeContext.model_validate({"handle": handle, "description": description[:size]})
            )
            budget -= size
    return tuple(result), truncated


def prepare(
    question: str, state: d.ConversationState | None = None
) -> PreparedEnvelope | PreparationFailure:
    state = state or d.ConversationState()
    try:
        d.PreparedInput(question=question)
        state = type(state).model_validate_json(state.model_dump_json())
    except (ValidationError, TypeError, ValueError):
        return PreparationFailure(reason="INVALID_INPUT")
    candidates: list[d.BindingCandidate] = []
    protected: list[d.InputSpan] = []
    candidate_count = 0

    def add(kind: type[d.DomainModel], **fields: object) -> None:
        nonlocal candidate_count
        candidate_count += 1
        if len(candidates) >= MAX_CANDIDATES:
            return  # Failure is emitted; partial registries never escape.
        candidates.append(
            cast(
                d.BindingCandidate,
                kind.model_validate({"candidate_id": f"c{len(candidates) + 1}", **fields}),
            )
        )

    literal_spans: set[tuple[int, int]] = set()
    for match in QUOTED.finditer(question):
        group = next(i for i in range(1, 5) if match.group(i) is not None)
        literal_spans.add(match.span(group))
        protected.append(d.InputSpan(start=match.start(), end=match.end()))
    for match in FILENAME.finditer(question):
        if not any(p.start <= match.start() and match.end() <= p.end for p in protected):
            literal_spans.add(match.span())
    strong_literals = set(literal_spans)
    known_names: set[str] = set()
    for snapshot in (state.last_substantive_request, state.last_successful_request_bundle):
        if snapshot:
            for candidate in snapshot.input.candidates:
                if isinstance(candidate, d.LiteralFileCandidate):
                    known_names.add(
                        snapshot.input.question[candidate.source.start : candidate.source.end]
                    )
    if isinstance(state, RoutingConversationState) and state.last_resolved_bundle:
        known_names.update(
            request.action.file.name
            for request in state.last_resolved_bundle.requests
            if isinstance(request, ResolvedFileTargetRequest)
        )
    for name in sorted(known_names):
        for match in re.finditer(re.escape(name), question):
            if (match.start() == 0 or not question[match.start() - 1].isalnum()) and (
                match.end() == len(question) or not question[match.end()].isalnum()
            ):
                if not any(
                    start <= match.start() and match.end() <= end for start, end in literal_spans
                ):
                    literal_spans.add(match.span())
    extraction_protected = list(protected) + [
        d.InputSpan(start=start, end=end)
        for start, end in strong_literals
        if question[start:end].strip()
    ]
    for start, end in sorted(literal_spans):
        if not question[start:end].strip():
            continue
        add(d.LiteralFileCandidate, source=d.SourceLocation(start=start, end=end))
        protected.append(d.InputSpan(start=start, end=end))
    for match in SELECTORS.finditer(question):
        if any(p.start <= match.start() < p.end for p in extraction_protected):
            continue
        value = (
            d.ReferenceSelector.OLDEST
            if match.group().lower() in ("oldest", "earliest")
            else d.ReferenceSelector.LATEST
        )
        add(
            d.SelectorCandidate,
            source=d.SourceLocation(start=match.start(), end=match.end()),
            selector=value,
        )
    runtime_spans: list[d.SourceLocation] = []
    for match in RUNTIME_RESULT.finditer(question):
        if any(p.start <= match.start() < p.end for p in extraction_protected):
            continue
        source = d.SourceLocation(start=match.start(), end=match.end())
        runtime_spans.append(source)
        add(d.RuntimeResultCandidate, source=source)
    for match in CONTEXT_FILE.finditer(question):
        if any(p.start <= match.start() < p.end for p in (*extraction_protected, *runtime_spans)):
            continue
        text = match.group().lower()
        kind = (
            d.FileContextKind.IT
            if text == "it"
            else d.FileContextKind.PREVIOUS_DOCUMENT
            if text.startswith("previous")
            else d.FileContextKind.THIS_FILE
            if text.startswith("this")
            else d.FileContextKind.THAT
        )
        source = d.SourceLocation(start=match.start(), end=match.end())
        add(d.ContextFileCandidate, source=source, reference_kind=kind)
        add(d.ContextTopicCandidate, source=source)
    add(d.CollectionCandidate)
    # Available handles are possibilities, not assertions that a reference resolves.
    add(
        d.ContextFileCandidate,
        source=d.ContextHandle(handle="ACTIVE_FILES"),
        reference_kind=d.FileContextKind.PREVIOUS_DOCUMENT,
    )
    add(d.ContextTopicCandidate, source=d.ContextHandle(handle="ACTIVE_TOPIC"))
    for role in ("user", "assistant"):
        count = max(1, sum(m.role == role for m in state.recent_messages))
        for ordinal in range(1, count + 1):
            add(
                d.PriorMessageCandidate,
                source=d.ContextHandle(handle="RECENT_MESSAGES"),
                reference=d.MessageReference.model_validate(
                    {"role": role, "relative_position": ordinal}
                ),
            )
    add(d.UnspecifiedTargetCandidate, source=d.SourceLocation(start=0, end=len(question)))
    if candidate_count > MAX_CANDIDATES:
        return PreparationFailure(reason="CANDIDATE_LIMIT", candidate_count=candidate_count)
    units = source_units(
        question,
        tuple(protected),
        tuple(
            c.source
            for c in candidates
            if isinstance(c.source, d.SourceLocation)
            and not isinstance(c, d.UnspecifiedTargetCandidate)
        ),
    )
    if len(units) > MAX_SPANS:
        return PreparationFailure(
            reason="SPAN_LIMIT_EXCEEDED", span_count=len(units), candidate_count=candidate_count
        )
    for unit in units:
        add(d.OriginalQueryCandidate, source=d.SourceLocation(start=unit.start, end=unit.end))
    if candidate_count > MAX_CANDIDATES:
        return PreparationFailure(
            reason="CANDIDATE_LIMIT", candidate_count=candidate_count, span_count=len(units)
        )
    bindings: list[PreparedBinding] = []
    full = units[0]
    for candidate in candidates:
        candidate_source = candidate.source
        spans: tuple[d.InputSpan, ...]
        if isinstance(candidate, d.UnspecifiedTargetCandidate):
            continue
        if isinstance(candidate, d.OriginalQueryCandidate):
            spans = (d.InputSpan(start=candidate.source.start, end=candidate.source.end),)
        elif isinstance(candidate_source, d.SourceLocation):
            spans = tuple(
                s
                for s in units
                if s.start <= candidate_source.start and candidate_source.end <= s.end
            )
        else:
            spans = units
        for span in spans or (full,):
            bindings.append(
                PreparedBinding(
                    label=f"B{len(bindings) + 1:03}",
                    candidate_id=candidate.candidate_id,
                    request_span=span,
                )
            )
    if len(bindings) > MAX_BINDINGS:
        return PreparationFailure(
            reason="BINDING_LIMIT",
            candidate_count=candidate_count,
            span_count=len(units),
            binding_count=len(bindings),
        )
    context, truncated = safe_context(state)
    return PreparedEnvelope(
        input=d.PreparedInput(question=question, candidates=tuple(candidates)),
        spans=tuple(PreparedSpan(span_id=f"S{i:03}", span=unit) for i, unit in enumerate(units, 1)),
        context_identity=hashlib.sha256(state.model_dump_json().encode()).hexdigest(),
        bindings=tuple(bindings),
        context=context,
        context_truncated=truncated,
    )
