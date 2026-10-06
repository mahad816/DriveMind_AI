"""Render only retained sources; never rewrite authoritative evidence content."""

import re
from uuid import UUID
from dataclasses import dataclass
from app.schemas.query import CitationItem
from app.llm.prompts import format_citation_snippet, normalize_answer_citations
from .agent_state import AgentState
from .handles import RuntimeHandleRegistry

_HANDLE = re.compile(r"(?<!\w)(?:file|source|evidence)_[1-9]\d*(?!\w)")
_UUID = re.compile(r"\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b", re.I)
_MARKER = re.compile(r"\[(source_[1-9]\d*|evidence_[1-9]\d*)\]")


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
    # Only explicit protocol citation markers are transformed. Unknown markers vanish.
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
