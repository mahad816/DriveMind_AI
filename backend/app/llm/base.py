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

    async def generate_direct_answer(self, question: str) -> str:
        """Generate a direct conversational reply without any file context.

        Used for chitchat / social messages where retrieval is not needed.
        """
        ...

    async def generate_inventory_answer(
        self,
        question: str,
        inventory_context: str,
    ) -> str:
        """Answer a file-inventory question using a structured Drive file context.

        ``inventory_context`` is a pre-formatted string produced by
        ``build_inventory_context()`` that lists matching files, counts, and
        optional content excerpts from the most recently modified file.
        """
        ...
