"""Shared types and errors for chat providers."""

from __future__ import annotations

from typing import Protocol

from app.retrieval.types import RetrievedChunk


class ChatError(Exception):
    """Base error raised when chat completion fails."""


class ChatConfigurationError(ChatError):
    """Raised when chat provider settings are missing or invalid."""


class ChatService(Protocol):
    """Protocol implemented by chat completion providers."""

    @property
    def model_name(self) -> str:
        """Return the configured chat model identifier."""
        ...

    async def generate_grounded_answer(
        self,
        question: str,
        chunks: list[RetrievedChunk],
        *,
        max_context_chars: int,
    ) -> str:
        """Generate an answer grounded in the supplied retrieved chunks."""
        ...
