"""Application-owned state, never a model argument."""

from dataclasses import dataclass, field
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.retrieval.hybrid import HybridRetriever
from ..handles import RuntimeHandleRegistry


@dataclass
class EvidenceRecoveryBudget:
    """Request-local cap; no provider retries or model-controlled allowance."""

    limit: int = 2
    attempted_files: set[UUID] = field(default_factory=set)

    def __post_init__(self) -> None:
        if not 0 <= self.limit <= 2:
            raise ValueError("evidence recovery limit must be within 0..2")

    def claim(self, file_id: UUID) -> bool:
        if file_id in self.attempted_files or len(self.attempted_files) >= self.limit:
            return False
        self.attempted_files.add(file_id)
        return True


@dataclass(frozen=True)
class ExecutionContext:
    user_id: UUID
    db: AsyncSession
    handles: RuntimeHandleRegistry
    retriever: HybridRetriever | None = None
    original_question: str = ""
    has_prior_history: bool = False
    max_context_chars: int = 12000
    recovery_budget: EvidenceRecoveryBudget = field(default_factory=EvidenceRecoveryBudget)

    def __post_init__(self) -> None:
        if not 1 <= self.max_context_chars <= 32000:
            raise ValueError("context budget must be within 1..32000")
