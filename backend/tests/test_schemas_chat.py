"""Tests for Phase 6 chat API schemas."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.chat import ChatRequest, ChatResponse
from app.schemas.query import CitationItem


def test_chat_request_strips_and_validates_question() -> None:
    payload = ChatRequest(question="  What is tensile strength?  ")

    assert payload.question == "What is tensile strength?"


def test_chat_request_rejects_blank_question() -> None:
    with pytest.raises(ValidationError, match="Question must not be empty"):
        ChatRequest(question="   ")


def test_chat_response_accepts_citations_and_counts() -> None:
    response = ChatResponse(
        query_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        answer="Tensile strength is discussed in [1].",
        citations=[
            CitationItem(
                chunk_id=uuid.uuid4(),
                drive_file_id=uuid.uuid4(),
                filename="notes.txt",
                snippet="Tensile strength is a material property.",
                score=0.91,
            )
        ],
        retrieval_count=3,
        message="Answer generated from indexed Drive content",
    )

    assert response.retrieval_count == 3
    assert len(response.citations) == 1
