"""Offline contract/projection tests; no providers, executors, or databases."""

import json
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from uuid import UUID
from typing import Literal, cast

import pytest
from pydantic import ValidationError

from app.agents.tool_rag import contracts as c
from app.agents.tool_rag.errors import ToolError, ToolErrorCode, ToolFailure
from app.agents.tool_rag.handles import (
    FileHandle,
    EvidenceHandle,
    SourceHandle,
    RuntimeHandleRegistry,
)
from app.agents.tool_rag.registry import ToolRegistry, INITIAL_TOOLS
from app.routing.intent_frame.evidence import (
    EvidenceChunk,
    EvidenceSection,
    ChunkTextRange,
    EvidenceSeparator,
)
from app.routing.intent_frame.scope import DEFAULT_LIST_ORDER


def file(number=1, name="report.pdf"):
    return c.InternalFileSummary(file_id=UUID(int=number), filename=name)


def section(file_id=1):
    chunks = tuple(
        EvidenceChunk(
            chunk_id=UUID(int=100 + i),
            document_id=UUID(int=90),
            file_id=UUID(int=file_id),
            chunk_index=i,
            text=text,
            filename="report.pdf",
        )
        for i, text in enumerate(("Refunds require approval.", "Keep an audit record."))
    )
    return EvidenceSection(
        anchor_chunk_id=chunks[0].chunk_id,
        members=chunks,
        parts=(
            ChunkTextRange(chunk_id=chunks[0].chunk_id, start=0, end=len(chunks[0].text)),
            EvidenceSeparator(text="\n\n"),
            ChunkTextRange(chunk_id=chunks[1].chunk_id, start=0, end=len(chunks[1].text)),
        ),
    )


def test_handle_insertion_and_reuse():
    a, b = RuntimeHandleRegistry(), RuntimeHandleRegistry()
    for registry in (a, b):
        first = registry.register_file(UUID(int=1))
        second = registry.register_file(UUID(int=2))
        assert first.value == "file_1" and second.value == "file_2"
        assert registry.register_file(UUID(int=1)) == first
        assert registry.resolve_file(second) == UUID(int=2)
        assert str(UUID(int=1)) not in first.model_dump_json()
    assert a.register_file(UUID(int=1)) == b.register_file(UUID(int=1))


@pytest.mark.parametrize(
    "handle",
    [
        FileHandle(value="file_9"),
        EvidenceHandle(value="evidence_1"),
        SourceHandle(value="source_1"),
    ],
)
def test_unknown_or_wrong_handle_kind(handle):
    with pytest.raises(ToolFailure) as error:
        RuntimeHandleRegistry().resolve_file(handle)
    assert error.value.error.code == ToolErrorCode.UNKNOWN_HANDLE
    assert error.value.error.to_llm_payload().code == ToolErrorCode.UNKNOWN_HANDLE


def test_registry_rejects_untrusted_internal_string():
    with pytest.raises(ToolFailure):
        RuntimeHandleRegistry().register_file(cast(UUID, "untrusted"))


@pytest.mark.parametrize("value", ["", "file_0", "file_01", "source_1", str(UUID(int=1))])
def test_handle_validation(value):
    with pytest.raises(ValidationError):
        FileHandle(value=value)


def test_tool_registry_exact_names_and_determinism():
    a, b = ToolRegistry(), ToolRegistry(tuple(reversed(INITIAL_TOOLS)))
    assert a.definitions() == b.definitions()
    assert [x["name"] for x in a.definitions()] == [
        "file_evidence",
        "files_query",
        "resolve_file",
        "search_knowledge",
    ]
    assert a.definitions() == a.definitions()
    with pytest.raises(ValueError):
        ToolRegistry(INITIAL_TOOLS + (INITIAL_TOOLS[0],))
    with pytest.raises(ValueError):
        ToolRegistry(INITIAL_TOOLS[:3])
    with pytest.raises(ToolFailure):
        a.get("search_everything")
    with pytest.raises(FrozenInstanceError):
        setattr(INITIAL_TOOLS[0], "description", "changed")


def visit_schema(value):
    if isinstance(value, dict):
        if value.get("type") == "object":
            assert value.get("additionalProperties") is False
        if value.get("type") == "array":
            assert "maxItems" in value
        if value.get("type") == "string" and "enum" not in value and "const" not in value:
            assert "maxLength" in value
        assert value.get("format") != "uuid"
        for item in value.values():
            visit_schema(item)
    elif isinstance(value, list):
        for item in value:
            visit_schema(item)


@pytest.mark.parametrize("tool", INITIAL_TOOLS, ids=lambda t: t.name)
def test_bounded_argument_schemas(tool):
    definition = tool.definition()
    visit_schema(definition["parameters"])
    text = json.dumps(definition)
    assert all(
        word not in text
        for word in [
            "FOLDER_REFERENCE",
            "LABEL_REFERENCE",
            "MODIFIED_TIME_REFERENCE",
            "file_id",
            "Qdrant",
            "OpenAI",
        ]
    )
    with pytest.raises(ToolFailure):
        tool.validate_arguments('{"unknown":1}')


@pytest.mark.parametrize("operation", ["LIST", "COUNT", "LATEST", "OLDEST"])
def test_inventory_operations(operation):
    result = c.FilesQueryArguments(operation=operation, scope=c.AllEligibleFiles())
    assert result.operation == operation
    assert c.LIST_ORDER_CONTRACT == DEFAULT_LIST_ORDER


@pytest.mark.parametrize("operation", ["DELETE", "RENAME", "WRITE", "SUMMARIZE"])
def test_no_inventory_write_or_content_operations(operation):
    with pytest.raises(ValidationError):
        c.FilesQueryArguments(operation=operation, scope=c.AllEligibleFiles())


def test_inventory_order_is_not_reselected():
    items = (file(2, "alpha.pdf"), file(1, "Beta.pdf"))
    result = c.FilesQueryResult(result=c.FileListResult(items=items))
    registry = RuntimeHandleRegistry()
    payload = result.to_llm_payload(registry)
    assert isinstance(payload.result, c.SafeFileList)
    assert [f.filename for f in payload.result.items] == ["alpha.pdf", "Beta.pdf"]
    first = payload.result.items[0].handle
    args = c.FileEvidenceArguments(file_handle=first, query="Summarize the first returned file.")
    assert registry.resolve_file(args.file_handle) == items[0].file_id
    assert "file_id" not in payload.model_dump_json()
    with pytest.raises(ValidationError):
        c.FileListResult(items=(items[0], items[0]))


def test_count_and_empty_selection():
    with pytest.raises(ValidationError):
        c.FileCountResult(count=-1)
    assert c.FileCountResult(count=0).count == 0
    kinds: tuple[Literal["LATEST", "OLDEST"], ...] = ("LATEST", "OLDEST")
    for kind in kinds:
        payload = c.FilesQueryResult(result=c.FileSelectionResult(kind=kind)).to_llm_payload(
            RuntimeHandleRegistry()
        )
        assert isinstance(payload.result, c.SafeFileSelection)
        assert payload.result.item is None


def test_timestamp_only_known_aware_source_time():
    with pytest.raises(ValidationError):
        c.InternalFileSummary(
            file_id=UUID(int=1), filename="a.pdf", modified_at=datetime(2026, 1, 1)
        )
    value = c.InternalFileSummary(
        file_id=UUID(int=1), filename="a.pdf", modified_at=datetime(2026, 1, 1, tzinfo=timezone.utc)
    )
    assert value.to_llm_payload(RuntimeHandleRegistry()).modified_at == value.modified_at
    assert file().to_llm_payload(RuntimeHandleRegistry()).modified_at is None


@pytest.mark.parametrize("reference", ["", "   ", "x" * 1025])
def test_resolve_reference_bounds(reference):
    with pytest.raises(ValidationError):
        c.ResolveFileArguments(reference=reference)


def test_resolve_result_variants_and_privacy():
    registry = RuntimeHandleRegistry()
    resolved = c.ResolveFileResult(result=c.ResolvedFileResult(file=file())).to_llm_payload(
        registry
    )
    assert resolved.result.kind == "RESOLVED"
    missing = c.ResolveFileResult(result=c.NotFoundFileResult()).to_llm_payload(registry)
    assert missing.model_dump() == {"result": {"kind": "NOT_FOUND"}}
    with pytest.raises(ValidationError):
        c.NotFoundFileResult.model_validate({"handle": FileHandle(value="file_1")})
    ambiguous = c.ResolveFileResult(
        result=c.AmbiguousFileResult(candidates=(file(), file(2, "other.pdf")))
    ).to_llm_payload(registry)
    assert ambiguous.result.kind == "AMBIGUOUS"
    assert (
        "file_id" not in ambiguous.model_dump_json()
        and str(UUID(int=2)) not in ambiguous.model_dump_json()
    )
    with pytest.raises(ValidationError):
        c.AmbiguousFileResult(candidates=(file(),))
    with pytest.raises(ValidationError):
        c.AmbiguousFileResult(candidates=(file(), file()))


@pytest.mark.parametrize("limit", [0, 51, -1, True])
def test_candidate_limits(limit):
    with pytest.raises(ValidationError):
        c.SearchKnowledgeArguments(
            query="refund policy", scope=c.AllEligibleFiles(), candidate_limit=limit
        )


def test_search_scope_only_all_or_exact_handles():
    exact = c.ExactFiles(file_handles=(FileHandle(value="file_1"),))
    a = c.SearchKnowledgeArguments(query="refund policy", scope=exact)
    assert a.scope == exact
    assert (
        c.SearchKnowledgeArguments(
            query="refund policy", scope=c.AllEligibleFiles()
        ).candidate_limit
        == 20
    )
    for data in [[], [str(UUID(int=1))], [FileHandle(value="file_1"), FileHandle(value="file_1")]]:
        with pytest.raises(ValidationError):
            c.ExactFiles(file_handles=tuple(data))
    for kind in ["FOLDER_REFERENCE", "LABEL_REFERENCE", "MODIFIED_TIME_REFERENCE"]:
        with pytest.raises(ValidationError):
            c.SearchKnowledgeArguments.model_validate_json(
                json.dumps({"query": "refund policy", "scope": {"kind": kind}})
            )


def test_rich_evidence_reuse_and_safe_source_provenance():
    rich = section()
    registry = RuntimeHandleRegistry()
    result = c.SearchKnowledgeResult(sections=(rich,))
    assert result.sections[0] is rich
    safe = result.to_llm_payload(registry).sections[0]
    assert safe.context == rich.combined_text
    assert safe.filename == "report.pdf"
    assert registry.resolve_section(safe.evidence_handle) == rich
    for member, citation in zip(rich.members, safe.citations, strict=True):
        assert registry.resolve_source(citation.source_handle) == member.chunk_id
        assert safe.context[citation.start : citation.end] == member.text
    text = safe.model_dump_json()
    for chunk in rich.members:
        assert all(str(x) not in text for x in [chunk.chunk_id, chunk.document_id, chunk.file_id])
    assert all(k not in text for k in ["chunk_id", "document_id", "file_id", "scores"])
    assert result.to_llm_payload(registry).sections[0] == safe
    altered = EvidenceSection(
        anchor_chunk_id=rich.anchor_chunk_id,
        members=rich.members,
        parts=(
            ChunkTextRange(chunk_id=rich.members[0].chunk_id, start=0, end=6),
            EvidenceSeparator(text=" "),
            rich.parts[2],
        ),
    )
    assert registry.register_section(altered) != safe.evidence_handle


def test_file_evidence_no_fallback_and_single_file():
    registry = RuntimeHandleRegistry()
    handle = registry.register_file(UUID(int=1))
    args = c.FileEvidenceArguments(file_handle=handle, query="What is the policy?")
    assert args.file_handle == handle
    for data in [
        {"query": "policy"},
        {"file_handle": "report.pdf", "query": "policy"},
        {
            "file_handle": handle.model_dump(),
            "query": "policy",
            "scope": {"kind": "ALL_ELIGIBLE_INDEXED_FILES"},
        },
    ]:
        with pytest.raises(ValidationError):
            c.FileEvidenceArguments.model_validate(data)
    rich = c.FileEvidenceResult(file_id=UUID(int=1), sections=(section(),))
    safe = rich.to_llm_payload(registry)
    assert safe.file_handle == handle and safe.sections[0].file_handle == handle
    assert (
        registry.resolve_source(safe.sections[0].citations[0].source_handle)
        == rich.sections[0].members[0].chunk_id
    )
    with pytest.raises(ValidationError):
        c.FileEvidenceResult(file_id=UUID(int=2), sections=(section(),))
    assert (
        c.FileEvidenceResult(file_id=UUID(int=1), sections=()).to_llm_payload(registry).sections
        == ()
    )


@pytest.mark.parametrize("code", list(ToolErrorCode))
def test_safe_errors_exclude_diagnostics(code):
    result = ToolError(code=code, private_diagnostic="secret connection string and traceback")
    assert "secret" not in result.model_dump_json()
    safe = result.to_llm_payload()
    assert safe.code == code and "secret" not in safe.model_dump_json()


def test_unknown_error_code_and_model_immutability():
    with pytest.raises(ValidationError):
        ToolError.model_validate_json('{"code":"ARBITRARY"}')
    with pytest.raises(ValidationError):
        FileHandle.model_validate({"value": "file_1", "uuid": str(UUID(int=1))})
    value = c.FileCountResult(count=3)
    with pytest.raises(ValidationError):
        value.count = 4
    with pytest.raises(ValidationError):
        c.FilesQueryArguments.model_validate(
            {"operation": "COUNT", "scope": c.AllEligibleFiles(), "ordering": "DEFAULT"}
        )


def test_tool_contract_validation_and_safe_projection():
    registry = ToolRegistry()
    handles = RuntimeHandleRegistry()
    contract = registry.get("files_query")
    args = contract.validate_arguments(
        '{"operation":"COUNT","scope":{"kind":"ALL_ELIGIBLE_INDEXED_FILES"}}'
    )
    assert isinstance(args, c.FilesQueryArguments)
    rich = contract.validate_result('{"result":{"kind":"COUNT","count":3}}')
    assert isinstance(rich, c.FilesQueryResult)
    assert contract.to_llm_payload(rich, handles).model_dump() == {
        "result": {"kind": "COUNT", "count": 3}
    }
    with pytest.raises(ToolFailure):
        contract.to_llm_payload(c.SearchKnowledgeResult(sections=()), handles)
    with pytest.raises(ToolFailure):
        contract.validate_result('{"result":{"kind":"COUNT","count":-1}}')


def test_model_facing_output_schemas_have_no_uuid():
    for cls in [
        c.FilesQueryPayload,
        c.ResolveFilePayload,
        c.SearchKnowledgePayload,
        c.FileEvidencePayload,
    ]:
        text = json.dumps(cls.model_json_schema())
        assert '"format": "uuid"' not in text
        assert all(k not in text for k in ["chunk_id", "document_id", "file_id"])


def test_isolated_package_import_boundaries():
    import ast
    from pathlib import Path
    import app.agents.tool_rag

    root = Path(app.agents.tool_rag.__file__).parent
    forbidden = (
        "openai",
        "langgraph",
        "sqlalchemy",
        "qdrant_client",
        "fastapi",
        "app.db",
        "app.services",
        "app.retrieval",
        "app.routing.v2",
    )
    # D2 graph/service modules are runtime code; keep the contract boundary strict.
    names = (
        "__init__.py",
        "contracts.py",
        "handles.py",
        "registry.py",
        "errors.py",
        "agent_models.py",
    )
    for path in (root / name for name in names):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            assert not any(
                name == item or name.startswith(item + ".") for name in names for item in forbidden
            )
