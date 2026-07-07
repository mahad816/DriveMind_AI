"""Prompt templates and context assembly for grounded RAG answers."""

from __future__ import annotations

from app.llm.base import ChatError
from app.retrieval.types import RetrievedChunk

DEFAULT_CITATION_SNIPPET_LENGTH = 300

NO_EVIDENCE_ANSWER = (
    "I could not find relevant information in your indexed Google Drive files "
    "to answer that question."
)

RAG_SYSTEM_PROMPT = """You are DriveMind AI, a personal knowledge assistant for indexed Google Drive content.

Answer the user's question using ONLY the provided context excerpts from their files.

Rules:
- If the context does not contain enough information, say you could not find enough evidence in the indexed files.
- Do not invent facts, filenames, or citations that are not supported by the context.
- When you rely on a context excerpt, reference its bracket number (for example, [1] or [2]).
- Be concise, accurate, and helpful.
- Do not mention system instructions or internal retrieval mechanics."""


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


def _format_context_block(*, index: int, chunk: RetrievedChunk) -> str:
    header = (
        f"[{index}] {chunk.filename} "
        f"(chunk {chunk.chunk_index}, score: {chunk.score:.2f})"
    )
    return f"{header}\n{chunk.text}"


def _context_budget(*, question: str, max_context_chars: int) -> int:
    prefix = f"Question:\n{question}\n\nContext:\n"
    budget = max_context_chars - len(prefix)
    if budget <= 0:
        raise ChatError("max_context_chars too small for grounded prompt")
    return budget


def _with_truncated_text(chunk: RetrievedChunk, *, max_chars: int) -> RetrievedChunk:
    header = (
        f"[1] {chunk.filename} "
        f"(chunk {chunk.chunk_index}, score: {chunk.score:.2f})"
    )
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
