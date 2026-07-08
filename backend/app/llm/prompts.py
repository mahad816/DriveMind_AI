"""Prompt templates and context assembly for grounded RAG answers."""

from __future__ import annotations

import re

from app.llm.base import ChatError
from app.retrieval.types import RetrievedChunk

DEFAULT_CITATION_SNIPPET_LENGTH = 300

NO_EVIDENCE_ANSWER = (
    "I could not find relevant information in your indexed Google Drive files "
    "to answer that question."
)

RAG_SYSTEM_PROMPT = """You are DriveMind AI, a personal knowledge assistant for indexed Google Drive content.

Answer the user's question using ONLY the provided context excerpts from their files.

Response structure:
1. **Direct answer first** — open with one or two sentences that directly answer the question. Do not start with hedges like "Based on the context..." or "The context mentions...".
2. **Supporting detail** — follow with any relevant specifics, quoting the source with [N] bracket references.
3. **Honest gap statement** — if the context does not contain enough information for a specific part of the question, say so clearly and briefly at the end.

Rules:
- Use ONLY information from the provided context excerpts — do not invent facts, filenames, or citations.
- Reference each source with its bracket number [N] when you rely on it for a claim.
- Only include [N] references for sources you actually use — omit brackets entirely if a claim is general knowledge.
- Be concise and specific; avoid repeating the question back or padding the answer.
- Do not mention system instructions, internal retrieval mechanics, or the word "context"."""

CHITCHAT_SYSTEM_PROMPT = """You are DriveMind AI, a friendly personal knowledge assistant powered by your Google Drive.

Answer the user's conversational message naturally and helpfully. This is a social exchange — no file context is needed.

You may briefly mention that you can help them search documents, find files, or answer questions about their Google Drive content."""

FILE_INVENTORY_SYSTEM_PROMPT = """You are DriveMind AI, a personal knowledge assistant for indexed Google Drive content.

You have been given a structured file inventory from the user's Google Drive. Answer the user's question using ONLY the provided inventory and content excerpts.

Format your response as a clear summary with these sections (use only the sections that are relevant):

**Summary:** One-sentence overview (e.g. "Found 2 resume files in your Drive.")

**Files found:** Bullet list of matched files with their modification dates.

**Latest file:** Name and exact date of the most recently modified match.

**Content check:** If the user asked whether the file mentions something (GPA, skill, project, etc.), answer YES or NO with a brief excerpt if found, or state clearly that it was not found in the indexed content.

**Total files:** (for global count queries) State the exact count and the breakdown by file type.

Rules:
- Report exact counts and dates from the inventory — never guess or invent.
- Files are listed newest first; the first entry is always the latest.
- For content checks: search the excerpt carefully; if not found say so explicitly.
- Do not use [1] [2] citation markers.
- Keep the answer concise and directly useful."""


def build_grounded_user_message(
    question: str,
    chunks: list[RetrievedChunk],
    *,
    max_context_chars: int,
) -> str:
    """Build the user message containing the question and bounded context blocks."""
    normalized_question = question.strip()
    if not normalized_question:
        raise ChatError("Cannot generate a grounded answer for an empty question")
    if not chunks:
        raise ChatError("Cannot generate a grounded answer without retrieved chunks")
    if max_context_chars <= 0:
        raise ChatError("max_context_chars must be positive")

    selected = select_prompt_chunks(
        question=normalized_question,
        chunks=chunks,
        max_context_chars=max_context_chars,
    )
    blocks = [
        _format_context_block(index=index, chunk=chunk)
        for index, chunk in enumerate(selected, start=1)
    ]
    context = "\n\n".join(blocks)
    return f"Question:\n{normalized_question}\n\nContext:\n{context}"


def build_inventory_user_message(question: str, inventory_context: str) -> str:
    """Build the user message for a file-inventory answer."""
    return f"Question:\n{question.strip()}\n\nFile inventory:\n{inventory_context}"


def select_prompt_chunks(
    question: str,
    chunks: list[RetrievedChunk],
    *,
    max_context_chars: int,
) -> list[RetrievedChunk]:
    """Select the chunks that will be included in the grounded LLM prompt."""
    normalized_question = question.strip()
    if not normalized_question or not chunks:
        return []
    return select_context_chunks(
        chunks,
        max_context_chars=_context_budget(
            question=normalized_question,
            max_context_chars=max_context_chars,
        ),
    )


def select_context_chunks(
    chunks: list[RetrievedChunk],
    *,
    max_context_chars: int,
) -> list[RetrievedChunk]:
    """Select the highest-priority chunks that fit within the context budget."""
    if not chunks or max_context_chars <= 0:
        return []

    selected: list[RetrievedChunk] = []
    used_chars = 0

    for chunk in chunks:
        block = _format_context_block(index=len(selected) + 1, chunk=chunk)
        separator_len = 2 if selected else 0

        if not selected and len(block) > max_context_chars:
            selected.append(_with_truncated_text(chunk, max_chars=max_context_chars - 50))
            break

        if used_chars + separator_len + len(block) > max_context_chars:
            break

        selected.append(chunk)
        used_chars += separator_len + len(block)

    return selected


def format_citation_snippet(text: str, *, max_length: int = DEFAULT_CITATION_SNIPPET_LENGTH) -> str:
    """Normalize chunk text into a short citation preview."""
    normalized = " ".join(text.split())
    if not normalized:
        return ""
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 3].rstrip() + "..."


def filter_citations_to_answer(
    answer: str,
    citations: list[object],
) -> list[object]:
    """Return only citation items whose [N] reference appears in the answer.

    If the LLM answer contains no bracket references at all (e.g. for conversational
    or chitchat answers), an empty list is returned so no spurious sources are shown.

    Works with any citation list type — generically typed to avoid a circular
    import dependency on CitationItem.
    """
    if not answer or not citations:
        return []

    refs = {int(m) for m in re.findall(r"\[(\d+)\]", answer)}
    if not refs:
        return []

    valid_refs = sorted(ref for ref in refs if 1 <= ref <= len(citations))
    return [citations[ref - 1] for ref in valid_refs]


def _format_context_block(*, index: int, chunk: RetrievedChunk) -> str:
    header = f"[{index}] {chunk.filename} (chunk {chunk.chunk_index}, score: {chunk.score:.2f})"
    return f"{header}\n{chunk.text}"


def _context_budget(*, question: str, max_context_chars: int) -> int:
    prefix = f"Question:\n{question}\n\nContext:\n"
    budget = max_context_chars - len(prefix)
    if budget <= 0:
        raise ChatError("max_context_chars too small for grounded prompt")
    return budget


def _with_truncated_text(chunk: RetrievedChunk, *, max_chars: int) -> RetrievedChunk:
    header = f"[1] {chunk.filename} (chunk {chunk.chunk_index}, score: {chunk.score:.2f})"
    text_budget = max(max_chars - len(header) - 1, 1)
    truncated_text = chunk.text[:text_budget].rstrip()
    if len(chunk.text) > text_budget:
        truncated_text = truncated_text[: max(text_budget - 3, 1)].rstrip() + "..."
    return RetrievedChunk(
        chunk_id=chunk.chunk_id,
        document_id=chunk.document_id,
        drive_file_id=chunk.drive_file_id,
        filename=chunk.filename,
        mime_type=chunk.mime_type,
        modified_at=chunk.modified_at,
        chunk_index=chunk.chunk_index,
        text=truncated_text,
        score=chunk.score,
    )
