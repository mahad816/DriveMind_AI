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
