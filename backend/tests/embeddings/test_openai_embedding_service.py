"""Tests for OpenAI embedding service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from openai import APIError

from app.core.config import Settings
from app.embeddings.base import EmbeddingConfigurationError, EmbeddingError
from app.embeddings.factory import get_embedding_service
from app.embeddings.openai_service import (
    OpenAIEmbeddingService,
    resolve_embedding_dimension,
)


def _embedding_response(*vectors: list[float]) -> MagicMock:
    response = MagicMock()
    response.data = [
        MagicMock(index=index, embedding=vector) for index, vector in enumerate(vectors)
    ]
    return response


@pytest.fixture
def settings() -> Settings:
    return Settings(
        openai_api_key="sk-test-key",
        embedding_model="text-embedding-3-small",
    )


@pytest.fixture
def mock_client() -> AsyncMock:
    client = AsyncMock()
    client.embeddings.create = AsyncMock(
        return_value=_embedding_response([0.1, 0.2, 0.3], [0.4, 0.5, 0.6]),
    )
    return client


@pytest.fixture
def service(settings: Settings, mock_client: AsyncMock) -> OpenAIEmbeddingService:
    return OpenAIEmbeddingService(settings=settings, client=mock_client)


def test_resolve_embedding_dimension_for_supported_models() -> None:
    assert resolve_embedding_dimension("text-embedding-3-small") == 1536
    assert resolve_embedding_dimension("text-embedding-3-large") == 3072
    assert resolve_embedding_dimension("text-embedding-ada-002") == 1536


def test_resolve_embedding_dimension_rejects_unknown_model() -> None:
    with pytest.raises(EmbeddingConfigurationError, match="Unsupported embedding model"):
        resolve_embedding_dimension("unknown-model")


def test_get_embedding_service_returns_openai_provider(settings: Settings) -> None:
    provider = get_embedding_service(settings)
    assert isinstance(provider, OpenAIEmbeddingService)
    assert provider.model_name == "text-embedding-3-small"
    assert provider.embedding_dimension == 1536


@pytest.mark.asyncio
async def test_embed_texts_returns_vectors_in_input_order(
    service: OpenAIEmbeddingService,
    mock_client: AsyncMock,
) -> None:
    result = await service.embed_texts(["hello", "world"])

    assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    mock_client.embeddings.create.assert_awaited_once_with(
        input=["hello", "world"],
        model="text-embedding-3-small",
    )


@pytest.mark.asyncio
async def test_embed_texts_returns_empty_list_for_no_input(
    service: OpenAIEmbeddingService,
    mock_client: AsyncMock,
) -> None:
    result = await service.embed_texts([])

    assert result == []
    mock_client.embeddings.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_embed_texts_batches_large_inputs(settings: Settings) -> None:
    mock_client = AsyncMock()
    mock_client.embeddings.create = AsyncMock(
        side_effect=[
            _embedding_response([1.0], [2.0]),
            _embedding_response([3.0]),
        ],
    )
    service = OpenAIEmbeddingService(settings=settings, client=mock_client, batch_size=2)

    result = await service.embed_texts(["a", "b", "c"])

    assert result == [[1.0], [2.0], [3.0]]
    assert mock_client.embeddings.create.await_count == 2


@pytest.mark.asyncio
async def test_embed_texts_rejects_empty_string(
    service: OpenAIEmbeddingService,
) -> None:
    with pytest.raises(EmbeddingError, match="Cannot embed empty text at index 1"):
        await service.embed_texts(["valid", "   "])


@pytest.mark.asyncio
async def test_embed_texts_raises_configuration_error_without_api_key() -> None:
    service = OpenAIEmbeddingService(
        settings=Settings(openai_api_key="", embedding_model="text-embedding-3-small"),
    )

    with pytest.raises(EmbeddingConfigurationError, match="OPENAI_API_KEY is not configured"):
        await service.embed_texts(["hello"])


@pytest.mark.asyncio
async def test_embed_texts_wraps_openai_api_errors(
    settings: Settings,
    mock_client: AsyncMock,
) -> None:
    mock_client.embeddings.create = AsyncMock(
        side_effect=APIError("rate limited", request=MagicMock(), body=None),
    )
    service = OpenAIEmbeddingService(settings=settings, client=mock_client)

    with pytest.raises(EmbeddingError, match="OpenAI embedding request failed"):
        await service.embed_texts(["hello"])
