"""Tests for deterministic extracted-text chunking."""

from __future__ import annotations

import pytest

from app.ingestion.chunking import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_TARGET_CHUNK_SIZE,
    ChunkingConfig,
    TextChunk,
    chunk_text,
)
from app.ingestion.extractors.plain_text import normalize_extracted_text


def _repeat_paragraph(paragraph: str, *, count: int, separator: str = "\n\n") -> str:
    return separator.join([paragraph] * count)


def test_chunk_text_returns_empty_list_for_empty_input() -> None:
    assert chunk_text("") == []
    assert chunk_text("   \n\n\t") == []


def test_chunk_text_returns_single_chunk_for_short_text() -> None:
    text = "DriveMind chunking sample."
    chunks = chunk_text(text)

    assert len(chunks) == 1
    assert chunks[0] == TextChunk(
        chunk_index=0,
        text=text,
        metadata={"char_start": 0, "char_end": len(text), "char_length": len(text)},
    )


def test_chunk_text_is_deterministic() -> None:
    paragraph = "Sentence one. Sentence two. " * 80
    text = _repeat_paragraph(paragraph, count=12)

    first = chunk_text(text)
    second = chunk_text(text)

    assert first == second


def test_chunk_text_normalizes_line_endings_before_splitting() -> None:
    text = "alpha\r\n\r\nbeta\r\n"
    chunks = chunk_text(text)

    assert len(chunks) == 1
    assert chunks[0].text == "alpha\n\nbeta"


def test_chunk_text_assigns_sequential_chunk_indices() -> None:
    paragraph = "x" * 1200
    text = _repeat_paragraph(paragraph, count=8)
    config = ChunkingConfig(target_size=2000, overlap=200)

    chunks = chunk_text(text, config=config)

    assert len(chunks) > 1
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))


def test_chunk_text_respects_target_size() -> None:
    paragraph = "word " * 300
    text = _repeat_paragraph(paragraph, count=10)
    config = ChunkingConfig(target_size=1500, overlap=150)

    chunks = chunk_text(text, config=config)

    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.text) <= config.target_size


def test_chunk_text_applies_overlap_between_chunks() -> None:
    paragraph = "abcdefghij " * 200
    text = _repeat_paragraph(paragraph, count=6)
    config = ChunkingConfig(target_size=1200, overlap=250)

    chunks = chunk_text(text, config=config)

    assert len(chunks) >= 2
    for previous, current in zip(chunks, chunks[1:], strict=False):
        assert previous.text[-250:] == current.text[:250]


def test_chunk_text_prefers_paragraph_boundaries() -> None:
    paragraph_a = "A" * 900
    paragraph_b = "B" * 900
    paragraph_c = "C" * 900
    text = f"{paragraph_a}\n\n{paragraph_b}\n\n{paragraph_c}"
    config = ChunkingConfig(target_size=1000, overlap=100)

    chunks = chunk_text(text, config=config)

    assert len(chunks) >= 2
    assert chunks[0].text == paragraph_a
    assert chunks[0].metadata["char_end"] == len(paragraph_a)
    assert "B" not in chunks[0].text
    assert "B" * 100 in chunks[1].text


def test_chunk_text_metadata_tracks_source_offsets() -> None:
    paragraph = "token " * 500
    text = _repeat_paragraph(paragraph, count=4)
    normalized = normalize_extracted_text(text)
    config = ChunkingConfig(target_size=1800, overlap=200)

    chunks = chunk_text(text, config=config)

    for chunk in chunks:
        start = chunk.metadata["char_start"]
        end = chunk.metadata["char_end"]
        length = chunk.metadata["char_length"]

        assert isinstance(start, int)
        assert isinstance(end, int)
        assert isinstance(length, int)
        assert 0 <= start < end <= len(normalized)
        assert length == end - start
        assert normalized[start:end] == chunk.text


def test_chunk_text_covers_entire_document_without_gaps() -> None:
    paragraph = "coverage " * 250
    text = _repeat_paragraph(paragraph, count=5)
    normalized = normalize_extracted_text(text)
    config = ChunkingConfig(target_size=1600, overlap=300)

    chunks = chunk_text(text, config=config)
    covered = [False] * len(normalized)

    for chunk in chunks:
        start = chunk.metadata["char_start"]
        end = chunk.metadata["char_end"]
        assert isinstance(start, int)
        assert isinstance(end, int)
        for index in range(start, end):
            covered[index] = True

    assert all(covered)


def test_chunk_text_uses_default_config_values() -> None:
    assert DEFAULT_TARGET_CHUNK_SIZE == 3500
    assert DEFAULT_CHUNK_OVERLAP == 500

    paragraph = "z" * 1800
    text = _repeat_paragraph(paragraph, count=5)
    chunks = chunk_text(text)

    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.text) <= DEFAULT_TARGET_CHUNK_SIZE


def test_chunking_config_rejects_invalid_overlap() -> None:
    with pytest.raises(ValueError, match="overlap must be less than target_size"):
        ChunkingConfig(target_size=1000, overlap=1000)


def test_chunking_config_rejects_negative_overlap() -> None:
    with pytest.raises(ValueError, match="overlap must be non-negative"):
        ChunkingConfig(target_size=1000, overlap=-1)


def test_chunking_config_rejects_non_positive_target_size() -> None:
    with pytest.raises(ValueError, match="target_size must be positive"):
        ChunkingConfig(target_size=0)
