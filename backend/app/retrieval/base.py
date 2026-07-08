"""Common protocol definitions for retrieval components."""

from __future__ import annotations

from typing import Protocol

from app.retrieval.types import RetrievedChunk


class Retriever(Protocol):
    """Protocol for retrieval implementations used by RAG orchestration."""

    async def retrieve(self, question: str) -> list[RetrievedChunk]: ...
