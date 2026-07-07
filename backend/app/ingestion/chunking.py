"""Deterministic text chunking for extracted document content."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.ingestion.extractors.plain_text import normalize_extracted_text

DEFAULT_TARGET_CHUNK_SIZE = 3500
DEFAULT_CHUNK_OVERLAP = 500

_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class ChunkingConfig:
    """Tunable chunking parameters for extracted plain text."""

    target_size: int = DEFAULT_TARGET_CHUNK_SIZE
    overlap: int = DEFAULT_CHUNK_OVERLAP

    def __post_init__(self) -> None:
        if self.target_size <= 0:
            raise ValueError("target_size must be positive")
        if self.overlap < 0:
            raise ValueError("overlap must be non-negative")
        if self.overlap >= self.target_size:
            raise ValueError("overlap must be less than target_size")


@dataclass(frozen=True)
class TextChunk:
    """A single chunk produced from extracted document text."""

    chunk_index: int
    text: str
    metadata: dict[str, object] = field(default_factory=dict)


def chunk_text(text: str, *, config: ChunkingConfig | None = None) -> list[TextChunk]:
    """Split normalized extracted text into overlapping chunks with metadata."""
    resolved = config or ChunkingConfig()
    normalized = normalize_extracted_text(text)
    if not normalized:
        return []

    if len(normalized) <= resolved.target_size:
        return [
            TextChunk(
                chunk_index=0,
                text=normalized,
                metadata=_build_metadata(char_start=0, char_end=len(normalized)),
            )
        ]

    chunks: list[TextChunk] = []
    start = 0
    chunk_index = 0

    while start < len(normalized):
        remaining = len(normalized) - start
        if remaining <= resolved.target_size:
            chunk_body = normalized[start:]
            chunks.append(
                TextChunk(
                    chunk_index=chunk_index,
                    text=chunk_body,
                    metadata=_build_metadata(char_start=start, char_end=len(normalized)),
                )
            )
            break

        split_end = _find_split_end(
            normalized,
            start=start,
            target_size=resolved.target_size,
        )
        chunk_body = normalized[start:split_end]
        if not chunk_body:
            break

        chunks.append(
            TextChunk(
                chunk_index=chunk_index,
                text=chunk_body,
                metadata=_build_metadata(char_start=start, char_end=split_end),
            )
        )
        chunk_index += 1

        if split_end >= len(normalized):
            break

        next_start = split_end - resolved.overlap
        if next_start <= start:
            next_start = split_end
        start = next_start

    return chunks


def _build_metadata(*, char_start: int, char_end: int) -> dict[str, object]:
    return {
        "char_start": char_start,
        "char_end": char_end,
        "char_length": char_end - char_start,
    }


def _find_split_end(text: str, *, start: int, target_size: int) -> int:
    """Pick a split point at or before ``start + target_size``."""
    hard_end = min(start + target_size, len(text))
    if hard_end == len(text):
        return hard_end

    window = text[start:hard_end]
    min_offset = max(1, target_size // 4)

    paragraph_break = window.rfind("\n\n", min_offset)
    if paragraph_break != -1:
        return start + paragraph_break

    line_break = window.rfind("\n", min_offset)
    if line_break != -1:
        return start + line_break

    sentence_break = _find_sentence_break(window, min_offset=min_offset)
    if sentence_break is not None:
        return start + sentence_break

    space_break = window.rfind(" ", min_offset)
    if space_break != -1:
        return start + space_break

    return hard_end


def _find_sentence_break(window: str, *, min_offset: int) -> int | None:
    """Return the end offset of the last sentence break inside ``window``."""
    best: int | None = None
    for match in _SENTENCE_BREAK.finditer(window):
        end = match.end()
        if end >= min_offset:
            best = end
    return best
