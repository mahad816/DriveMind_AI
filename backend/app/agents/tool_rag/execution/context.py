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


@dataclass
class DualQueryAllowance:
    """One use of C2 per run. The context (and with it this object) is created once per agent run, so a retry, a
    repeated tool call or a later cycle can never reset it; the first eligible search claims it for good."""

    used: bool = False

    def claim(self) -> bool:
        if self.used:
            return False
        self.used = True
        return True


@dataclass(frozen=True)
class ExecutionContext:
    user_id: UUID
    db: AsyncSession
    handles: RuntimeHandleRegistry
    retriever: HybridRetriever | None = None
    original_question: str = ""
    has_prior_history: bool = False
    # C2 (settings.retrieval_dual_query_enabled): set by the agent service, never by a model argument.
    dual_query_enabled: bool = False
    dual_query_allowance: DualQueryAllowance = field(default_factory=DualQueryAllowance)
    max_context_chars: int = 12000
    recovery_budget: EvidenceRecoveryBudget = field(default_factory=EvidenceRecoveryBudget)

    def __post_init__(self) -> None:
        if not 1 <= self.max_context_chars <= 32000:
            raise ValueError("context budget must be within 1..32000")
