"""Turn-local insertion-ordered handles; identities never occur in handle text."""

from typing import Literal
from uuid import UUID
from pydantic import Field
from app.routing.intent_frame.references import ContractModel
from app.routing.intent_frame.evidence import EvidenceSection
from .errors import ToolFailure, ToolErrorCode


class FileHandle(ContractModel):
    kind: Literal["FILE"] = "FILE"
    value: str = Field(pattern=r"^file_[1-9][0-9]{0,5}$", max_length=11)


class EvidenceHandle(ContractModel):
    kind: Literal["EVIDENCE"] = "EVIDENCE"
    value: str = Field(pattern=r"^evidence_[1-9][0-9]{0,5}$", max_length=15)


class SourceHandle(ContractModel):
    kind: Literal["SOURCE"] = "SOURCE"
    value: str = Field(pattern=r"^source_[1-9][0-9]{0,5}$", max_length=13)


class RuntimeHandleRegistry:
    """Owned by one turn. Never persist/reuse across turns or use as authorization."""

    def __init__(self) -> None:
        self._files: dict[UUID, FileHandle] = {}
        self._returned_filenames: set[str] = set()
        self._file_ids: dict[FileHandle, UUID] = {}
        self._sources: dict[UUID, SourceHandle] = {}
        self._source_ids: dict[SourceHandle, UUID] = {}
        self._sections: dict[EvidenceSection, EvidenceHandle] = {}
        self._section_values: dict[EvidenceHandle, EvidenceSection] = {}

    def register_file(self, file_id: UUID, *, filename: str | None = None) -> FileHandle:
        if not isinstance(file_id, UUID):
            raise ToolFailure(ToolErrorCode.INVALID_ARGUMENT)
        if file_id not in self._files:
            handle = FileHandle(value=f"file_{len(self._files) + 1}")
            self._files[file_id] = handle
            self._file_ids[handle] = file_id
        if filename is not None:
            self._returned_filenames.add(filename.casefold())
        return self._files[file_id]

    def filename_returned_in_run(self, reference: str) -> bool:
        """Provenance only, not identity/authorization; populated by safe projections."""
        return reference.casefold() in self._returned_filenames

    def resolve_file(self, handle: FileHandle) -> UUID:
        if not isinstance(handle, FileHandle) or handle not in self._file_ids:
            raise ToolFailure(ToolErrorCode.UNKNOWN_HANDLE)
        return self._file_ids[handle]

    def register_source(self, chunk_id: UUID) -> SourceHandle:
        if not isinstance(chunk_id, UUID):
            raise ToolFailure(ToolErrorCode.INVALID_ARGUMENT)
        if chunk_id not in self._sources:
            handle = SourceHandle(value=f"source_{len(self._sources) + 1}")
            self._sources[chunk_id] = handle
            self._source_ids[handle] = chunk_id
        return self._sources[chunk_id]

    def resolve_source(self, handle: SourceHandle) -> UUID:
        if not isinstance(handle, SourceHandle) or handle not in self._source_ids:
            raise ToolFailure(ToolErrorCode.UNKNOWN_HANDLE)
        return self._source_ids[handle]

    def register_section(self, section: EvidenceSection) -> EvidenceHandle:
        if section not in self._sections:
            handle = EvidenceHandle(value=f"evidence_{len(self._sections) + 1}")
            self._sections[section] = handle
            self._section_values[handle] = section
        return self._sections[section]

    def resolve_section(self, handle: EvidenceHandle) -> EvidenceSection:
        if not isinstance(handle, EvidenceHandle) or handle not in self._section_values:
            raise ToolFailure(ToolErrorCode.UNKNOWN_HANDLE)
        return self._section_values[handle]
