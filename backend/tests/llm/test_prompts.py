"""Tests for grounded RAG prompt assembly."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.llm.base import ChatError
from app.llm.prompts import (
    build_grounded_user_message,
    format_citation_snippet,
    normalize_answer_citations,
    select_context_chunks,
    select_prompt_chunks,
)
from app.retrieval.types import RetrievedChunk

CHUNK_ID = uuid.uuid4()
DOCUMENT_ID = uuid.uuid4()
DRIVE_FILE_ID = uuid.uuid4()


def _chunk(*, text: str, chunk_index: int = 0, score: float = 0.9) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=DOCUMENT_ID,
        drive_file_id=DRIVE_FILE_ID,
        filename="notes.txt",
        mime_type="text/plain",
        modified_at=datetime.now(UTC),
        chunk_index=chunk_index,
        text=text,
        score=score,
    )


def test_build_grounded_user_message_includes_question_and_context() -> None:
    chunk = _chunk(text="Tensile strength measures resistance to pulling.")

    message = build_grounded_user_message(
        "What is tensile strength?",
        [chunk],
        max_context_chars=500,
    )

    assert "Question:\nWhat is tensile strength?" in message
    assert "Context:\n" in message
    assert "[1] notes.txt" in message
    assert "Tensile strength measures resistance to pulling." in message


def test_select_context_chunks_respects_budget() -> None:
    chunks = [
        _chunk(text="a" * 200, chunk_index=0),
        _chunk(text="b" * 200, chunk_index=1),
        _chunk(text="c" * 200, chunk_index=2),
    ]

    selected = select_context_chunks(chunks, max_context_chars=250)

    assert len(selected) == 1
    assert selected[0].chunk_index == 0


def test_select_context_chunks_truncates_single_oversized_chunk() -> None:
    chunk = _chunk(text="x" * 500)

    selected = select_context_chunks([chunk], max_context_chars=120)

    assert len(selected) == 1
    assert len(selected[0].text) < 500
    assert selected[0].text.endswith("...")


def test_format_citation_snippet_normalizes_whitespace_and_truncates() -> None:
    snippet = format_citation_snippet("line one\n\nline two " + ("word " * 100), max_length=40)

    assert "\n" not in snippet
    assert snippet.endswith("...")
    assert len(snippet) <= 40


@pytest.mark.parametrize(
    ("answer", "citations", "expected_answer", "expected_citations"),
    [
        ("See [1].", ["c1", "c2", "c3"], "See [1].", ["c1"]),
        ("See [3].", ["c1", "c2", "c3"], "See [1].", ["c3"]),
        (
            "Compare [1] and [3].",
            ["c1", "c2", "c3"],
            "Compare [1] and [2].",
            ["c1", "c3"],
        ),
        (
            "Compare [3] and [1].",
            ["c1", "c2", "c3"],
            "Compare [1] and [2].",
            ["c3", "c1"],
        ),
        ("[3] then [3].", ["c1", "c2", "c3"], "[1] then [1].", ["c3"]),
        ("Invalid [0] and [4].", ["c1", "c2", "c3"], "Invalid and.", []),
        (
            "Use [2] and ignore [9].",
            ["c1", "c2", "c3"],
            "Use [1] and ignore.",
            ["c2"],
        ),
        ("Only invalid [9].", ["c1"], "Only invalid.", []),
        ("[9] Invalid at start.", ["c1"], "Invalid at start.", []),
        ("No citation markers.", ["c1"], "No citation markers.", []),
        (
            "Keep [abc] and [1,2].",
            ["c1", "c2"],
            "Keep [abc] and [1,2].",
            [],
        ),
        ("See [12].", [f"c{i}" for i in range(1, 13)], "See [1].", ["c12"]),
    ],
)
def test_normalize_answer_citations(
    answer: str,
    citations: list[str],
    expected_answer: str,
    expected_citations: list[str],
) -> None:
    normalized_answer, normalized_citations = normalize_answer_citations(answer, citations)

    assert normalized_answer == expected_answer
    assert normalized_citations == expected_citations


def test_normalize_answer_citations_preserves_markdown_paragraphs() -> None:
    answer = "First claim [9].  \n\n- Second claim [1]."

    normalized_answer, citations = normalize_answer_citations(answer, ["c1"])

    assert normalized_answer == "First claim.  \n\n- Second claim [1]."
    assert citations == ["c1"]


def test_build_grounded_user_message_rejects_empty_question() -> None:
    with pytest.raises(ChatError, match="empty question"):
        build_grounded_user_message("  ", [_chunk(text="content")], max_context_chars=200)


def test_build_grounded_user_message_rejects_missing_chunks() -> None:
    with pytest.raises(ChatError, match="without retrieved chunks"):
        build_grounded_user_message("hello?", [], max_context_chars=200)


def test_select_prompt_chunks_returns_empty_for_blank_question() -> None:
    chunk = _chunk(text="content")

    selected = select_prompt_chunks("  ", [chunk], max_context_chars=500)

    assert selected == []


def test_select_prompt_chunks_matches_build_grounded_user_message_selection() -> None:
    chunks = [
        _chunk(text="a" * 200, chunk_index=0),
        _chunk(text="b" * 200, chunk_index=1),
    ]

    selected = select_prompt_chunks(
        "What is here?",
        chunks,
        max_context_chars=300,
    )
    message = build_grounded_user_message(
        "What is here?",
        chunks,
        max_context_chars=300,
    )

    assert len(selected) >= 1
    assert selected[0].text[:20] in message
