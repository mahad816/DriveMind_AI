"""Tests for filename target extraction and prioritization."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.retrieval.filename_targets import (
    chunk_matches_filename_target,
    extract_filename_targets,
    filename_matches_target,
    prioritize_filename_targets,
)
from app.retrieval.types import RetrievedChunk


def _chunk(filename: str, text: str = "body") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        drive_file_id=uuid.uuid4(),
        filename=filename,
        mime_type="text/plain",
        modified_at=datetime.now(UTC),
        chunk_index=0,
        text=text,
        score=0.5,
    )


def test_extract_filename_targets_from_quoted_name() -> None:
    assert extract_filename_targets('Tell me about "Far611"') == ["Far611"]


def test_extract_short_quoted_target() -> None:
    assert extract_filename_targets('Tell me about "HI"') == ["HI"]


def test_extract_filename_targets_from_tell_me_about() -> None:
    assert extract_filename_targets("Tell me about harrypotterrrrrr") == ["harrypotterrrrrr"]


def test_filename_matches_target_case_insensitive() -> None:
    assert filename_matches_target("Far611", "far611") is True
    assert filename_matches_target("Resume_2024.pdf", "Resume_2024") is True


def test_prioritize_filename_targets_moves_named_file_first() -> None:
    far611 = _chunk("Far611", "Cherry blossoms")
    assignment = _chunk("Assignment_01.pdf", "ES111")

    result = prioritize_filename_targets(
        [assignment, far611],
        'Tell me about "Far611"',
    )

    assert result[0].filename == "Far611"
    assert result[1].filename == "Assignment_01.pdf"


def test_chunk_matches_filename_target() -> None:
    chunk = _chunk("Far611")
    assert chunk_matches_filename_target(chunk, ["Far611"]) is True
    assert chunk_matches_filename_target(chunk, ["Other"]) is False
