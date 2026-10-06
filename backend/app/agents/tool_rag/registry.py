"""Deterministic contract registry, schema generation and validation; no dispatch."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, cast
from pydantic import JsonValue, ValidationError
from app.routing.intent_frame.references import ContractModel
from . import contracts as c
from .handles import RuntimeHandleRegistry
from .errors import ToolFailure, ToolErrorCode

ToolName = Literal["files_query", "resolve_file", "search_knowledge", "file_evidence"]
Arguments = (
    c.FilesQueryArguments
    | c.ResolveFileArguments
    | c.SearchKnowledgeArguments
    | c.FileEvidenceArguments
)
RichResult = (
    c.FilesQueryResult | c.ResolveFileResult | c.SearchKnowledgeResult | c.FileEvidenceResult
)
SafeResult = (
    c.FilesQueryPayload | c.ResolveFilePayload | c.SearchKnowledgePayload | c.FileEvidencePayload
)


@dataclass(frozen=True)
class ToolContract:
    name: ToolName
    description: str
    arguments_model: type[ContractModel]
    result_model: type[ContractModel]

    def __post_init__(self) -> None:
        if self.name not in {"files_query", "resolve_file", "search_knowledge", "file_evidence"}:
            raise ValueError("unknown canonical tool name")
        if not self.description.strip():
            raise ValueError("tool description required")

    def definition(self) -> dict[str, JsonValue]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": cast(dict[str, JsonValue], self.arguments_model.model_json_schema()),
        }

    def validate_arguments(self, arguments_json: str) -> ContractModel:
        try:
            return self.arguments_model.model_validate_json(arguments_json)
        except ValidationError:
            raise ToolFailure(ToolErrorCode.INVALID_ARGUMENT) from None

    def validate_result(self, result_json: str) -> ContractModel:
        try:
            return self.result_model.model_validate_json(result_json)
        except ValidationError:
            raise ToolFailure(ToolErrorCode.INTERNAL_ERROR) from None

    def to_llm_payload(self, result: RichResult, registry: RuntimeHandleRegistry) -> SafeResult:
        if not isinstance(result, self.result_model):
            raise ToolFailure(ToolErrorCode.INTERNAL_ERROR)
        return result.to_llm_payload(registry)


INITIAL_TOOLS = (
    ToolContract(
        "files_query",
        "Inspect indexed file inventory: list, count, or select the newest/oldest file. Not for document-content questions.",
        c.FilesQueryArguments,
        c.FilesQueryResult,
    ),
    ToolContract(
        "resolve_file",
        "Resolve a specific human file reference to a unique indexed file handle.",
        c.ResolveFileArguments,
        c.ResolveFileResult,
    ),
    ToolContract(
        "search_knowledge",
        "Search indexed document content for evidence needed to answer a knowledge question.",
        c.SearchKnowledgeArguments,
        c.SearchKnowledgeResult,
    ),
    ToolContract(
        "file_evidence",
        "Read evidence from exactly one file already resolved to a file handle.",
        c.FileEvidenceArguments,
        c.FileEvidenceResult,
    ),
)


class ToolRegistry:
    def __init__(self, contracts: tuple[ToolContract, ...] = INITIAL_TOOLS):
        by_name = {tool.name: tool for tool in contracts}
        if len(by_name) != len(contracts):
            raise ValueError("duplicate canonical tool names")
        if set(by_name) != {tool.name for tool in INITIAL_TOOLS}:
            raise ValueError("registry must contain exactly the four initial tools")
        self._tools = MappingProxyType(dict(sorted(by_name.items())))

    def get(self, name: str) -> ToolContract:
        if name not in self._tools:
            raise ToolFailure(ToolErrorCode.INVALID_ARGUMENT)
        return self._tools[cast(ToolName, name)]

    def definitions(self) -> tuple[dict[str, JsonValue], ...]:
        return tuple(tool.definition() for tool in self._tools.values())
