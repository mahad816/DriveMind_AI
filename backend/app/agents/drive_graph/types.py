"""Intent and retrieval-plan types for the DriveMind LangGraph agent."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

RetrieverName = Literal["vector", "keyword", "metadata"]

ALL_RETRIEVERS: tuple[RetrieverName, ...] = ("vector", "keyword", "metadata")


class QueryIntent(StrEnum):
    """High-level query intent used to route retrieval strategy."""

    FIND_LATEST = "find_latest"
    KEYWORD_SEARCH = "keyword_search"
    SEMANTIC_QUESTION = "semantic_question"
    SUMMARIZE_TOPIC = "summarize_topic"
    LIST_OR_FILTER = "list_or_filter"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RetrievalPlan:
    """Planned retrieval strategy selected after intent classification."""

    intent: QueryIntent
    retrievers: tuple[RetrieverName, ...]
    top_k: int | None = None
    sort_by_modified_desc: bool = False

    def __post_init__(self) -> None:
        if not self.retrievers:
            raise ValueError("RetrievalPlan must include at least one retriever")
        for retriever in self.retrievers:
            if retriever not in ALL_RETRIEVERS:
                raise ValueError(f"Unsupported retriever: {retriever}")

    @property
    def uses_vector(self) -> bool:
        return "vector" in self.retrievers

    @property
    def uses_keyword(self) -> bool:
        return "keyword" in self.retrievers

    @property
    def uses_metadata(self) -> bool:
        return "metadata" in self.retrievers
