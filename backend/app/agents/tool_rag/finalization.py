"""Render only retained sources; never rewrite authoritative evidence content."""

import re
from uuid import UUID
from dataclasses import dataclass
from app.schemas.query import CitationItem
from app.llm.prompts import format_citation_snippet, normalize_answer_citations
from .agent_state import AgentState, ToolExecutionRecord
from .handles import RuntimeHandleRegistry
from .contracts import (
    AmbiguousFileResult,
    FileCountResult,
    FileEvidenceResult,
    FileListResult,
    FileSelectionResult,
    FilesQueryResult,
    NotFoundFileResult,
    ResolveFileResult,
    ResolvedFileResult,
    SearchKnowledgeResult,
)

NO_CONTENT = "I don't have retrieved document evidence to answer that. Which file should I look up?"
EMPTY_CONTENT = (
    "The index did not provide enough evidence to answer. This does not mean the document is empty."
)
CLARIFY_FILE = "Which filename do you mean?"
# Exact input allowlist, not a classifier for arbitrary output or document intent.
_SOCIAL = {
    "hi": "Hello!",
    "hello": "Hello!",
    "hey": "Hello!",
    "good morning": "Hello!",
    "good afternoon": "Hello!",
    "good evening": "Hello!",
    "thanks": "You're welcome!",
    "thank you": "You're welcome!",
    "bye": "Goodbye!",
    "goodbye": "Goodbye!",
}


def display_filename(name: str) -> str:
    # Metadata is data, never model instructions or Markdown links/citations.
    return re.sub(r"([\\`*_{}\[\]()<>#!|])", r"\\\1", name).replace("\n", " ").replace("\r", " ")


def without_content(state: AgentState) -> str:
    """Render only server-owned language and authoritative metadata, never model prose.

    This deliberately sacrifices free-form formatting and chat recall without evidence.
    It does not pretend to classify whether arbitrary prose is a document claim.
    """
    for record in reversed(state["tool_history"]):
        if record.result.error is not None:
            return record.result.error.to_llm_payload().message + " " + CLARIFY_FILE
        result = record.result.internal_result
        if isinstance(result, (FileEvidenceResult, SearchKnowledgeResult)):
            return EMPTY_CONTENT
        if isinstance(result, ResolveFileResult):
            value = result.result
            if isinstance(value, AmbiguousFileResult):
                return "Please disambiguate the filename. Matching indexed files:\n" + "\n".join(
                    "- " + display_filename(f.filename) for f in value.candidates
                )
            if isinstance(value, NotFoundFileResult):
                return "No eligible indexed file matches that name. Check the filename and preparation status."
            if isinstance(value, ResolvedFileResult):
                return (
                    "Found indexed file: "
                    + display_filename(value.file.filename)
                    + ". "
                    + NO_CONTENT
                )
        if isinstance(result, FilesQueryResult):
            value = result.result
            if isinstance(value, FileCountResult):
                return f"Indexed files: {value.count}."
            if isinstance(value, FileListResult):
                total = value.total_count if value.total_count is not None else len(value.items)
                return f"Indexed files: {total}. Showing {len(value.items)}.\n" + "\n".join(
                    "- " + display_filename(f.filename) for f in value.items
                )
            if isinstance(value, FileSelectionResult):
                if value.item is None:
                    return "No eligible indexed files were found."
                return (
                    value.kind.title() + " indexed file: " + display_filename(value.item.filename)
                )
    question = state["original_question"].strip().casefold().rstrip(".!?")
    return _SOCIAL.get(question, NO_CONTENT)


MIXED_METADATA = "Only verified file metadata is shown. A combined metadata/content answer could not be verified."


def provenance_response(state: AgentState) -> str | None:
    """Gate free-form prose using actual ordered tool outcomes, never inferred intent.

    Every resolved target needs a subsequent successful content read containing that
    exact file. Earlier reads cannot satisfy a later resolution. Empty reads, failed
    tools and missing/ambiguous references conservatively block prose for this run,
    even if other calls succeeded. Start a new request to resolve such limitations.

    Any inventory result requires deterministic metadata rendering: free-form prose
    cannot be split reliably into metadata claims and content claims. This includes
    inventory used as a producer for a later read. Multi-file content-only workflows
    remain supported through resolve_file and successful scoped reads.
    """
    pending: dict[UUID, ToolExecutionRecord] = {}
    blocked: list[ToolExecutionRecord] = []
    inventories: list[ToolExecutionRecord] = []
    for record in state["tool_history"]:
        if record.result.error is not None:
            blocked.append(record)
            continue
        result = record.result.internal_result
        if isinstance(result, ResolveFileResult):
            if isinstance(result.result, ResolvedFileResult):
                pending[result.result.file.file_id] = record
            else:
                blocked.append(record)
        elif isinstance(result, (FileEvidenceResult, SearchKnowledgeResult)):
            if not result.sections:
                blocked.append(record)
            else:
                read_ids = {
                    member.file_id for section in result.sections for member in section.members
                }
                for file_id in read_ids:
                    pending.pop(file_id, None)
        elif isinstance(result, FilesQueryResult):
            inventories.append(record)

    def render(record: ToolExecutionRecord) -> str:
        return without_content({**state, "tool_history": (record,)})

    if blocked:
        return render(blocked[-1])
    if pending:
        return render(next(reversed(pending.values())))
    if inventories:
        # Retain authoritative results, not model claims, even after content retrieval.
        response = "\n\n".join(dict.fromkeys(render(record) for record in inventories))
        if state["evidence"]:
            response += "\n\n" + MIXED_METADATA
        return response
    if not state["evidence"]:
        return without_content(state)
    return None


_HANDLE = re.compile(r"(?<!\w)(?:file|source|evidence)_[1-9]\d*(?!\w)")
_UUID = re.compile(r"\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b", re.I)
_MARKER = re.compile(r"\[((?:source|evidence)_[^\]\n]*)\]")


@dataclass(frozen=True)
class FinalizedAnswer:
    answer: str
    citations: tuple[CitationItem, ...]


def finalize_answer(
    text: str, state: AgentState, handles: RuntimeHandleRegistry
) -> FinalizedAnswer:
    # Source text is sliced from actual contributing ranges, not generated summaries.
    chunks = {}
    excerpts: dict[UUID, str] = {}
    for section in state["evidence"]:
        members = {m.chunk_id: m for m in section.members}
        for chunk_id, start, end in section.member_ranges:
            chunks[chunk_id] = members[chunk_id]
            excerpts.setdefault(chunk_id, section.combined_text[start:end])
    sources = [h for h in state["citation_handles"] if handles.resolve_source(h) in chunks]
    citations = [
        CitationItem(
            chunk_id=handles.resolve_source(h),
            drive_file_id=chunks[handles.resolve_source(h)].file_id,
            filename=chunks[handles.resolve_source(h)].filename,
            snippet=format_citation_snippet(excerpts[handles.resolve_source(h)]),
        )
        for h in sources
    ]
    mapping = {h.value: f"[{i}]" for i, h in enumerate(sources, 1)}
    for section in state["evidence"]:
        evidence = handles.register_section(section)
        mapping[evidence.value] = "".join(
            mapping[h.value]
            for h in sources
            if handles.resolve_source(h) in {m.chunk_id for m in section.members}
        )
    # An invented marker is not repaired by deleting it or appending real sources.
    if any(match.group(1) not in mapping for match in _MARKER.finditer(text)):
        raise ValueError("unknown citation handle")
    if any(
        not 1 <= int(match.group(1)) <= len(citations) for match in re.finditer(r"\[(\d+)\]", text)
    ):
        raise ValueError("unknown numeric citation")
    controlled = provenance_response(state)
    if controlled is not None:
        return FinalizedAnswer(answer=controlled, citations=())
    # Only explicit protocol citation markers are transformed.
    # Bare handles / UUIDs fail closed instead of blind replacement in quoted content.
    answer = _MARKER.sub(lambda match: mapping.get(match.group(1), ""), text).strip()
    if _HANDLE.search(answer) or _UUID.search(answer):
        raise ValueError("unsafe final output")
    answer, retained = normalize_answer_citations(answer, citations)
    if citations and not retained:
        # Honest attribution of consulted sources, not invented sentence-level support.
        names = "; ".join(f"{c.filename} [{i}]" for i, c in enumerate(citations, 1))
        answer += "\n\nSources consulted: " + names
        answer, retained = normalize_answer_citations(answer, citations)
    if _HANDLE.search(answer) or _UUID.search(answer):
        raise ValueError("unsafe source display")
    return FinalizedAnswer(answer=answer, citations=tuple(retained))
