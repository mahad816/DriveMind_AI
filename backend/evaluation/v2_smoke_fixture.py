"""Frozen synthetic smoke inputs; separate from a held-out routing benchmark."""

import hashlib
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.routing.v2 import domain as d
from app.routing.v2.resolved import IndexedFile

FIXTURE = Path(__file__).parent / "datasets/v2_smoke_15_v1.json"


class ExpectedRequest(d.DomainModel):
    capability: Literal[
        "FILE_INVENTORY",
        "FILE_TARGET",
        "COLLECTION_SUMMARY",
        "GROUNDED_RAG",
        "CONVERSATION_HISTORY",
        "CHITCHAT",
    ]
    operation: Literal[
        "LIST",
        "COUNT",
        "LATEST",
        "OLDEST",
        "SUMMARIZE",
        "ANSWER_QUESTION",
        "SUMMARIZE_EACH",
        "ANSWER",
        "RECALL",
        "RESPOND",
    ]
    binding: Literal[
        "collection",
        "literal",
        "selector",
        "context_file",
        "original_query",
        "context_topic",
        "history",
    ]
    ordering: Literal["DEFAULT", "NEWEST_FIRST", "OLDEST_FIRST", "NAME_ASC", "NAME_DESC"] | None = (
        None
    )
    target_name: str | None = None
    selector: Literal["LATEST", "OLDEST"] | None = None
    role: Literal["user", "assistant"] | None = None
    relative_position: int | None = None
    source_spans: tuple[d.InputSpan, ...] = Field(min_length=1, max_length=3)
    query_spans: tuple[d.InputSpan, ...] = ()
    resolved_file_id: UUID | None = None
    resolved_message: str | None = None


class SmokeCase(d.DomainModel):
    id: str = Field(pattern=r"^v2-smoke-[0-9]{3}$")
    question: str = Field(min_length=1, max_length=8000)
    user_id: UUID
    metadata: tuple[IndexedFile, ...]
    eligibility: Literal["VISIBLE_INDEXED_ONLY"] = "VISIBLE_INDEXED_ONLY"
    state: d.ConversationState = Field(default_factory=d.ConversationState)
    expected_cardinality: Literal["ONE", "TWO"]
    expected_special: Literal["UNSUPPORTED_OPERATION"] | None = None
    expected_requests: tuple[ExpectedRequest, ...] = ()
    expected_readiness: Literal["READY", "UNSUPPORTED"]

    @model_validator(mode="after")
    def coherent(self) -> "SmokeCase":
        if any(f.user_id != self.user_id for f in self.metadata) or len(
            {f.file_id for f in self.metadata}
        ) != len(self.metadata):
            raise ValueError("invalid synthetic metadata snapshot")
        if self.expected_special:
            if self.expected_requests or self.expected_readiness != "UNSUPPORTED":
                raise ValueError("invalid unsupported gold")
        elif len(self.expected_requests) != {"ONE": 1, "TWO": 2}[self.expected_cardinality]:
            raise ValueError("gold cardinality mismatch")
        for request in self.expected_requests:
            for span in (*request.source_spans, *request.query_spans):
                if (
                    span.end > len(self.question)
                    or not self.question[span.start : span.end].strip()
                ):
                    raise ValueError("invalid gold source span")
            if request.resolved_file_id and request.resolved_file_id not in {
                f.file_id for f in self.metadata
            }:
                raise ValueError("gold file not in snapshot")
        return self


class SmokeFixtures(d.DomainModel):
    fixture_version: Literal["v2-smoke-15-1.0"]
    synthetic_only: Literal[True]
    description: str
    cases: tuple[SmokeCase, ...] = Field(min_length=15, max_length=15)

    @model_validator(mode="after")
    def exact_cases(self) -> "SmokeFixtures":
        if tuple(c.id for c in self.cases) != tuple(f"v2-smoke-{i:03}" for i in range(1, 16)):
            raise ValueError("smoke must contain exactly ordered cases 001–015")
        return self


def load_fixtures(path: Path = FIXTURE) -> SmokeFixtures:
    return SmokeFixtures.model_validate_json(path.read_text(encoding="utf-8"))


def fixture_hash(path: Path = FIXTURE) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
