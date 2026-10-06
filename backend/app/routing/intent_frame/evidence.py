"""Authoritative text slices with complete member provenance; no generated context."""

from typing import Annotated, Literal, TypeAlias
from uuid import UUID
from pydantic import Field, model_validator
from .references import ContractModel


class SourceLocator(ContractModel):
    page: int | None = Field(default=None, ge=1)
    section: str | None = Field(default=None, min_length=1, max_length=200)


class RetrievalScore(ContractModel):
    source: Literal["vector", "keyword", "metadata", "fusion", "rerank"]
    value: float = Field(allow_inf_nan=False)


class EvidenceChunk(ContractModel):
    chunk_id: UUID
    document_id: UUID
    file_id: UUID
    chunk_index: int = Field(ge=0)
    text: str = Field(min_length=1, pattern=r"\S")
    filename: str = Field(min_length=1, max_length=1024, pattern=r"\S")
    locator: SourceLocator | None = None
    scores: tuple[RetrievalScore, ...] = Field(default=(), max_length=5)

    @model_validator(mode="after")
    def unique_scores(self) -> "EvidenceChunk":
        if len({s.source for s in self.scores}) != len(self.scores):
            raise ValueError("score sources must be unique")
        return self


class ChunkTextRange(ContractModel):
    kind: Literal["CHUNK_TEXT"] = "CHUNK_TEXT"
    chunk_id: UUID
    start: int = Field(ge=0)
    end: int = Field(gt=0)


class EvidenceSeparator(ContractModel):
    kind: Literal["SEPARATOR"] = "SEPARATOR"
    text: Literal["\n", "\n\n", " "]


EvidencePart: TypeAlias = Annotated[ChunkTextRange | EvidenceSeparator, Field(discriminator="kind")]


class EvidenceSection(ContractModel):
    anchor_chunk_id: UUID
    members: tuple[EvidenceChunk, ...] = Field(min_length=1, max_length=20)
    parts: tuple[EvidencePart, ...] = Field(min_length=1, max_length=60)
    # Context and section offsets are derived, never a second writable truth.

    @model_validator(mode="after")
    def authoritative_parts(self) -> "EvidenceSection":
        by_id = {m.chunk_id: m for m in self.members}
        if len(by_id) != len(self.members) or self.anchor_chunk_id not in by_id:
            raise ValueError("unique members must include the anchor")
        if len({(m.file_id, m.document_id) for m in self.members}) != 1:
            raise ValueError("a section belongs to one document and file")
        if tuple(m.chunk_index for m in self.members) != tuple(
            sorted({m.chunk_index for m in self.members})
        ):
            raise ValueError("members must have unique ordered chunk indices")
        used = []
        for i, p in enumerate(self.parts):
            if isinstance(p, EvidenceSeparator):
                if (
                    i == 0
                    or i == len(self.parts) - 1
                    or isinstance(self.parts[i - 1], EvidenceSeparator)
                ):
                    raise ValueError("separator must occur between source ranges")
            else:
                if p.chunk_id not in by_id or not (
                    0 <= p.start < p.end <= len(by_id[p.chunk_id].text)
                ):
                    raise ValueError("source range must be within a member's original text")
                used.append(p.chunk_id)
        if tuple(used) != tuple(by_id):
            raise ValueError("each ordered member must contribute exactly one source range")
        return self

    @property
    def combined_text(self) -> str:
        by_id = {m.chunk_id: m for m in self.members}
        return "".join(
            p.text if isinstance(p, EvidenceSeparator) else by_id[p.chunk_id].text[p.start : p.end]
            for p in self.parts
        )

    @property
    def member_ranges(self) -> tuple[tuple[UUID, int, int], ...]:
        by_id = {m.chunk_id: m for m in self.members}
        offset = 0
        ranges = []
        for p in self.parts:
            if isinstance(p, EvidenceSeparator):
                offset += len(p.text)
            else:
                length = len(by_id[p.chunk_id].text[p.start : p.end])
                ranges.append((p.chunk_id, offset, offset + length))
                offset += length
        return tuple(ranges)
