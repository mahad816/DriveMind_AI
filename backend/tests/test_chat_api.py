"""Tests for grounded chat API route."""

from __future__ import annotations

from collections.abc import Generator
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.api.chat import get_rag_service
from app.embeddings.base import EmbeddingConfigurationError
from app.llm.base import ChatError
from app.main import app
from app.schemas.query import CitationItem
from app.services.rag_service import RagResult

USER_ID = uuid.uuid4()
QUERY_ID = uuid.uuid4()
CHUNK_ID = uuid.uuid4()
DRIVE_FILE_ID = uuid.uuid4()


@pytest.fixture(autouse=True)
def clear_dependency_overrides() -> Generator[None, None, None]:
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_chat_success_returns_grounded_answer(async_client: AsyncClient) -> None:
    fake_service = MagicMock()
    fake_service.ask = AsyncMock(
        return_value=RagResult(
            query_id=QUERY_ID,
            user_id=USER_ID,
            question="What is tensile strength?",
            answer="Tensile strength is discussed in [1].",
            citations=[
                CitationItem(
                    chunk_id=CHUNK_ID,
                    drive_file_id=DRIVE_FILE_ID,
                    filename="notes.txt",
                    snippet="Tensile strength is a material property.",
                    score=0.91,
                )
            ],
            retrieval_count=1,
        )
    )
    app.dependency_overrides[get_rag_service] = lambda: fake_service

    response = await async_client.post(
        "/api/v1/chat",
        json={"question": "What is tensile strength?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["query_id"] == str(QUERY_ID)
    assert body["user_id"] == str(USER_ID)
    assert body["answer"] == "Tensile strength is discussed in [1]."
    assert body["retrieval_count"] == 1
    assert body["message"] == "Answer generated from indexed Drive content"
    assert len(body["citations"]) == 1
    assert body["citations"][0]["chunk_id"] == str(CHUNK_ID)
    fake_service.ask.assert_awaited_once_with("What is tensile strength?")


@pytest.mark.asyncio
async def test_chat_rejects_empty_question(async_client: AsyncClient) -> None:
    response = await async_client.post(
        "/api/v1/chat",
        json={"question": "   "},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_chat_no_connection_returns_503(async_client: AsyncClient) -> None:
    fake_service = MagicMock()
    fake_service.ask = AsyncMock(
        side_effect=ValueError("No Google Drive connection found. Complete OAuth first."),
    )
    app.dependency_overrides[get_rag_service] = lambda: fake_service

    response = await async_client.post(
        "/api/v1/chat",
        json={"question": "What files do I have?"},
    )

    assert response.status_code == 503
    assert "No Google Drive connection" in response.json()["detail"]


@pytest.mark.asyncio
async def test_chat_missing_openai_key_returns_503(async_client: AsyncClient) -> None:
    fake_service = MagicMock()
    fake_service.ask = AsyncMock(
        side_effect=EmbeddingConfigurationError("OPENAI_API_KEY is not configured"),
    )
    app.dependency_overrides[get_rag_service] = lambda: fake_service

    response = await async_client.post(
        "/api/v1/chat",
        json={"question": "Summarize my notes"},
    )

    assert response.status_code == 503
    assert "OPENAI_API_KEY" in response.json()["detail"]


@pytest.mark.asyncio
async def test_chat_openai_failure_returns_503(async_client: AsyncClient) -> None:
    fake_service = MagicMock()
    fake_service.ask = AsyncMock(
        side_effect=ChatError("OpenAI chat request failed: rate limited"),
    )
    app.dependency_overrides[get_rag_service] = lambda: fake_service

    response = await async_client.post(
        "/api/v1/chat",
        json={"question": "Summarize my notes"},
    )

    assert response.status_code == 503
    assert "OpenAI chat request failed" in response.json()["detail"]


@pytest.mark.asyncio
async def test_chat_no_evidence_returns_empty_citations(async_client: AsyncClient) -> None:
    from app.llm.prompts import NO_EVIDENCE_ANSWER

    fake_service = MagicMock()
    fake_service.ask = AsyncMock(
        return_value=RagResult(
            query_id=QUERY_ID,
            user_id=USER_ID,
            question="What is quantum foam?",
            answer=NO_EVIDENCE_ANSWER,
            citations=[],
            retrieval_count=0,
        )
    )
    app.dependency_overrides[get_rag_service] = lambda: fake_service

    response = await async_client.post(
        "/api/v1/chat",
        json={"question": "What is quantum foam?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == NO_EVIDENCE_ANSWER
    assert body["citations"] == []
    assert body["retrieval_count"] == 0


@pytest.mark.asyncio
async def test_chat_vector_store_error_returns_503(async_client: AsyncClient) -> None:
    from app.embeddings.vector_store import VectorStoreError

    fake_service = MagicMock()
    fake_service.ask = AsyncMock(
        side_effect=VectorStoreError("Qdrant connection failed during vector search"),
    )
    app.dependency_overrides[get_rag_service] = lambda: fake_service

    response = await async_client.post(
        "/api/v1/chat",
        json={"question": "What is tensile strength?"},
    )

    assert response.status_code == 503
    assert "Qdrant connection failed" in response.json()["detail"]


@pytest.mark.asyncio
async def test_chat_embedding_error_returns_503(async_client: AsyncClient) -> None:
    from app.embeddings.base import EmbeddingError

    fake_service = MagicMock()
    fake_service.ask = AsyncMock(
        side_effect=EmbeddingError("OpenAI embedding request failed: timeout"),
    )
    app.dependency_overrides[get_rag_service] = lambda: fake_service

    response = await async_client.post(
        "/api/v1/chat",
        json={"question": "What is tensile strength?"},
    )

    assert response.status_code == 503
    assert "embedding request failed" in response.json()["detail"]


@pytest.mark.asyncio
async def test_chat_configuration_error_returns_503(async_client: AsyncClient) -> None:
    from app.llm.base import ChatConfigurationError

    fake_service = MagicMock()
    fake_service.ask = AsyncMock(
        side_effect=ChatConfigurationError("OPENAI_API_KEY is not configured"),
    )
    app.dependency_overrides[get_rag_service] = lambda: fake_service

    response = await async_client.post(
        "/api/v1/chat",
        json={"question": "What is tensile strength?"},
    )

    assert response.status_code == 503
    assert "OPENAI_API_KEY" in response.json()["detail"]


@pytest.mark.asyncio
async def test_chat_missing_question_field_returns_422(async_client: AsyncClient) -> None:
    response = await async_client.post("/api/v1/chat", json={})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_chat_strips_question_whitespace(async_client: AsyncClient) -> None:
    fake_service = MagicMock()
    fake_service.ask = AsyncMock(
        return_value=RagResult(
            query_id=QUERY_ID,
            user_id=USER_ID,
            question="What is tensile strength?",
            answer="Answer",
            citations=[],
            retrieval_count=0,
        )
    )
    app.dependency_overrides[get_rag_service] = lambda: fake_service

    response = await async_client.post(
        "/api/v1/chat",
        json={"question": "  What is tensile strength?  "},
    )

    assert response.status_code == 200
    fake_service.ask.assert_awaited_once_with("What is tensile strength?")
