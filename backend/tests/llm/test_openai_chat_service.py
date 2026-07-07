"""Tests for OpenAI chat service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from openai import APIError

from app.core.config import Settings
from app.llm.base import ChatConfigurationError, ChatError
from app.llm.factory import get_chat_service
from app.llm.openai_service import OpenAIChatService
from app.llm.prompts import RAG_SYSTEM_PROMPT
from app.retrieval.types import RetrievedChunk


def _chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        drive_file_id=uuid.uuid4(),
        filename="notes.txt",
        mime_type="text/plain",
        modified_at=datetime.now(UTC),
        chunk_index=0,
        text="Tensile strength is a material property.",
        score=0.91,
    )


def _chat_response(content: str) -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=content))]
    return response


@pytest.fixture
def settings() -> Settings:
    return Settings(
        openai_api_key="sk-test-key",
        chat_model="gpt-4o-mini",
        rag_max_context_chars=12000,
    )


@pytest.fixture
def mock_client() -> AsyncMock:
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(
        return_value=_chat_response("Tensile strength is discussed in [1]."),
    )
    return client


@pytest.fixture
def service(settings: Settings, mock_client: AsyncMock) -> OpenAIChatService:
    return OpenAIChatService(settings=settings, client=mock_client)


def test_get_chat_service_returns_openai_provider(settings: Settings) -> None:
    provider = get_chat_service(settings)
    assert isinstance(provider, OpenAIChatService)
    assert provider.model_name == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_generate_grounded_answer_sends_system_and_user_messages(
    service: OpenAIChatService,
    mock_client: AsyncMock,
) -> None:
    answer = await service.generate_grounded_answer(
        "What is tensile strength?",
        [_chunk()],
        max_context_chars=12000,
    )

    assert answer == "Tensile strength is discussed in [1]."
    mock_client.chat.completions.create.assert_awaited_once()
    call_kwargs = mock_client.chat.completions.create.await_args.kwargs
    assert call_kwargs["model"] == "gpt-4o-mini"
    messages = call_kwargs["messages"]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == RAG_SYSTEM_PROMPT
    assert messages[1]["role"] == "user"
    assert "What is tensile strength?" in messages[1]["content"]
    assert "[1] notes.txt" in messages[1]["content"]


@pytest.mark.asyncio
async def test_generate_grounded_answer_raises_configuration_error_without_api_key() -> None:
    service = OpenAIChatService(
        settings=Settings(openai_api_key="", chat_model="gpt-4o-mini"),
    )

    with pytest.raises(ChatConfigurationError, match="OPENAI_API_KEY is not configured"):
        await service.generate_grounded_answer(
            "question",
            [_chunk()],
            max_context_chars=12000,
        )


@pytest.mark.asyncio
async def test_generate_grounded_answer_wraps_openai_api_errors(
    settings: Settings,
    mock_client: AsyncMock,
) -> None:
    mock_client.chat.completions.create = AsyncMock(
        side_effect=APIError("rate limited", request=MagicMock(), body=None),
    )
    service = OpenAIChatService(settings=settings, client=mock_client)

    with pytest.raises(ChatError, match="OpenAI chat request failed"):
        await service.generate_grounded_answer(
            "question",
            [_chunk()],
            max_context_chars=12000,
        )


@pytest.mark.asyncio
async def test_generate_grounded_answer_rejects_empty_model_response(
    settings: Settings,
    mock_client: AsyncMock,
) -> None:
    mock_client.chat.completions.create = AsyncMock(return_value=_chat_response("   "))
    service = OpenAIChatService(settings=settings, client=mock_client)

    with pytest.raises(ChatError, match="empty answer"):
        await service.generate_grounded_answer(
            "question",
            [_chunk()],
            max_context_chars=12000,
        )
