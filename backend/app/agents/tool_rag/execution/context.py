"""Application-owned state, never a model argument."""

from dataclasses import dataclass
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.retrieval.hybrid import HybridRetriever
from ..handles import RuntimeHandleRegistry


@dataclass(frozen=True)
class ExecutionContext:
    user_id: UUID
    db: AsyncSession
    handles: RuntimeHandleRegistry
    retriever: HybridRetriever | None = None
    original_question: str = ""
    has_prior_history: bool = False
    max_context_chars: int = 12000

    def __post_init__(self) -> None:
        if not 1 <= self.max_context_chars <= 32000:
            raise ValueError("context budget must be within 1..32000")
