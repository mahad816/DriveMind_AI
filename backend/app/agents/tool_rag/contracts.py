"""Strict arguments, rich internal results, and explicit safe projections."""

from typing import Annotated, Literal, TypeAlias
from uuid import UUID
from pydantic import AwareDatetime, Field, model_validator
from app.routing.intent_frame.references import ContractModel
from app.routing.intent_frame.evidence import EvidenceSection, SourceLocator
from app.routing.intent_frame.scope import DEFAULT_LIST_ORDER
from .handles import FileHandle, EvidenceHandle, SourceHandle, RuntimeHandleRegistry

# Reuse Phase 1's deterministic ordered-result contract; no sorting executor here.
LIST_ORDER_CONTRACT = DEFAULT_LIST_ORDER


class AllEligibleFiles(ContractModel):
    kind: Literal["ALL_ELIGIBLE_INDEXED_FILES"] = "ALL_ELIGIBLE_INDEXED_FILES"


class ExactFiles(ContractModel):
    kind: Literal["EXACT_FILES"] = "EXACT_FILES"
    file_handles: tuple[FileHandle, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique_handles(self) -> "ExactFiles":
        if len(set(self.file_handles)) != len(self.file_handles):
            raise ValueError("duplicate file handles")
        return self


ToolRetrievalScope: TypeAlias = Annotated[
    AllEligibleFiles | ExactFiles, Field(discriminator="kind")
]


class FilesQueryArguments(ContractModel):
    operation: Literal["LIST", "COUNT", "LATEST", "OLDEST"]
    scope: AllEligibleFiles


class ResolveFileArguments(ContractModel):
    reference: str = Field(
        min_length=1,
        max_length=1024,
        pattern=r"\S",
        description="Human file reference, not trusted identity.",
    )


class SearchKnowledgeArguments(ContractModel):
    query: str = Field(min_length=1, max_length=8000, pattern=r"\S")
    scope: ToolRetrievalScope
    candidate_limit: int = Field(default=20, ge=1, le=50)


class FileEvidenceArguments(ContractModel):
    file_handle: FileHandle
    query: str = Field(min_length=1, max_length=8000, pattern=r"\S")


class InternalFileSummary(ContractModel):
    file_id: UUID
    filename: str = Field(min_length=1, max_length=1024, pattern=r"\S")
    mime_type: str | None = Field(default=None, min_length=1, max_length=200)
    # Executor may supply only authoritative, timezone-aware source time; no fallback time.
    modified_at: AwareDatetime | None = None

    def to_llm_payload(self, registry: RuntimeHandleRegistry) -> "FileSummary":
        return FileSummary(
            handle=registry.register_file(self.file_id),
            filename=self.filename,
            mime_type=self.mime_type,
            modified_at=self.modified_at,
        )


class FileSummary(ContractModel):
    handle: FileHandle
    filename: str = Field(min_length=1, max_length=1024, pattern=r"\S")
    mime_type: str | None = Field(default=None, min_length=1, max_length=200)
    modified_at: AwareDatetime | None = None


class FileListResult(ContractModel):
    kind: Literal["LIST"] = "LIST"
    items: tuple[InternalFileSummary, ...] = Field(max_length=100)
    ordering: Literal["DEFAULT"] = "DEFAULT"

    @model_validator(mode="after")
    def distinct_files(self) -> "FileListResult":
        if len({f.file_id for f in self.items}) != len(self.items):
            raise ValueError("duplicate file identity")
        return self


class SafeFileList(ContractModel):
    kind: Literal["LIST"] = "LIST"
    items: tuple[FileSummary, ...] = Field(max_length=100)
    ordering: Literal["DEFAULT"] = "DEFAULT"


class FileCountResult(ContractModel):
    kind: Literal["COUNT"] = "COUNT"
    count: int = Field(ge=0)


class FileSelectionResult(ContractModel):
    kind: Literal["LATEST", "OLDEST"]
    item: InternalFileSummary | None = None


class SafeFileSelection(ContractModel):
    kind: Literal["LATEST", "OLDEST"]
    item: FileSummary | None = None


FileQueryValue: TypeAlias = Annotated[
    FileListResult | FileCountResult | FileSelectionResult, Field(discriminator="kind")
]
SafeFileQueryValue: TypeAlias = Annotated[
    SafeFileList | FileCountResult | SafeFileSelection, Field(discriminator="kind")
]


class FilesQueryPayload(ContractModel):
    result: SafeFileQueryValue


class FilesQueryResult(ContractModel):
    result: FileQueryValue

    def to_llm_payload(self, registry: RuntimeHandleRegistry) -> FilesQueryPayload:
        if isinstance(self.result, FileListResult):
            value: SafeFileQueryValue = SafeFileList(
                items=tuple(f.to_llm_payload(registry) for f in self.result.items)
            )
        elif isinstance(self.result, FileSelectionResult):
            value = SafeFileSelection(
                kind=self.result.kind,
                item=self.result.item.to_llm_payload(registry) if self.result.item else None,
            )
        else:
            value = self.result
        return FilesQueryPayload(result=value)


class ResolvedFileResult(ContractModel):
    kind: Literal["RESOLVED"] = "RESOLVED"
    file: InternalFileSummary


class AmbiguousFileResult(ContractModel):
    kind: Literal["AMBIGUOUS"] = "AMBIGUOUS"
    candidates: tuple[InternalFileSummary, ...] = Field(min_length=2, max_length=10)

    @model_validator(mode="after")
    def distinct_files(self) -> "AmbiguousFileResult":
        if len({f.file_id for f in self.candidates}) != len(self.candidates):
            raise ValueError("ambiguous candidates must be distinct")
        return self


class NotFoundFileResult(ContractModel):
    kind: Literal["NOT_FOUND"] = "NOT_FOUND"


class SafeResolvedFile(ContractModel):
    kind: Literal["RESOLVED"] = "RESOLVED"
    file: FileSummary


class SafeAmbiguousFiles(ContractModel):
    kind: Literal["AMBIGUOUS"] = "AMBIGUOUS"
    candidates: tuple[FileSummary, ...] = Field(min_length=2, max_length=10)


ResolveValue: TypeAlias = Annotated[
    ResolvedFileResult | AmbiguousFileResult | NotFoundFileResult, Field(discriminator="kind")
]
SafeResolveValue: TypeAlias = Annotated[
    SafeResolvedFile | SafeAmbiguousFiles | NotFoundFileResult, Field(discriminator="kind")
]


class ResolveFilePayload(ContractModel):
    result: SafeResolveValue


class ResolveFileResult(ContractModel):
    result: ResolveValue

    def to_llm_payload(self, registry: RuntimeHandleRegistry) -> ResolveFilePayload:
        if isinstance(self.result, ResolvedFileResult):
            value: SafeResolveValue = SafeResolvedFile(
                file=self.result.file.to_llm_payload(registry)
            )
        elif isinstance(self.result, AmbiguousFileResult):
            value = SafeAmbiguousFiles(
                candidates=tuple(f.to_llm_payload(registry) for f in self.result.candidates)
            )
        else:
            value = self.result
        return ResolveFilePayload(result=value)


class CitationMember(ContractModel):
    source_handle: SourceHandle
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    locator: SourceLocator | None = None

    @model_validator(mode="after")
    def forward(self) -> "CitationMember":
        if self.end <= self.start:
            raise ValueError("citation range must be forward")
        return self


class EvidencePayload(ContractModel):
    evidence_handle: EvidenceHandle
    file_handle: FileHandle
    filename: str = Field(min_length=1, max_length=1024, pattern=r"\S")
    context: str = Field(min_length=1, max_length=32000, pattern=r"\S")
    citations: tuple[CitationMember, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def valid_ranges(self) -> "EvidencePayload":
        if len({c.source_handle.value for c in self.citations}) != len(self.citations):
            raise ValueError("duplicate citation sources")
        previous_end = 0
        for c in self.citations:
            if c.start < previous_end or c.end > len(self.context):
                raise ValueError("citations must map ordered context ranges")
            previous_end = c.end
        return self


def project_section(section: EvidenceSection, registry: RuntimeHandleRegistry) -> EvidencePayload:
    anchor = next(m for m in section.members if m.chunk_id == section.anchor_chunk_id)
    locators = {m.chunk_id: m.locator for m in section.members}
    return EvidencePayload(
        evidence_handle=registry.register_section(section),
        file_handle=registry.register_file(anchor.file_id),
        filename=anchor.filename,
        context=section.combined_text,
        citations=tuple(
            CitationMember(
                source_handle=registry.register_source(chunk_id),
                start=start,
                end=end,
                locator=locators[chunk_id],
            )
            for chunk_id, start, end in section.member_ranges
        ),
    )


class SearchKnowledgePayload(ContractModel):
    sections: tuple[EvidencePayload, ...] = Field(max_length=20)


class SearchKnowledgeResult(ContractModel):
    sections: tuple[EvidenceSection, ...] = Field(max_length=20)

    def to_llm_payload(self, registry: RuntimeHandleRegistry) -> SearchKnowledgePayload:
        return SearchKnowledgePayload(
            sections=tuple(project_section(s, registry) for s in self.sections)
        )


class FileEvidencePayload(ContractModel):
    file_handle: FileHandle
    sections: tuple[EvidencePayload, ...] = Field(max_length=20)

    @model_validator(mode="after")
    def one_file(self) -> "FileEvidencePayload":
        if any(s.file_handle != self.file_handle for s in self.sections):
            raise ValueError("evidence belongs to a different file")
        return self


class FileEvidenceResult(ContractModel):
    file_id: UUID
    sections: tuple[EvidenceSection, ...] = Field(max_length=20)

    @model_validator(mode="after")
    def one_file(self) -> "FileEvidenceResult":
        if any(m.file_id != self.file_id for s in self.sections for m in s.members):
            raise ValueError("file evidence must remain scoped to exactly one file")
        return self

    def to_llm_payload(self, registry: RuntimeHandleRegistry) -> FileEvidencePayload:
        return FileEvidencePayload(
            file_handle=registry.register_file(self.file_id),
            sections=tuple(project_section(s, registry) for s in self.sections),
        )
