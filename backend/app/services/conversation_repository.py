"""Owner-scoped SQL primitives, with no commits, rollbacks or network calls.

Callers must open an explicit transaction and roll it back on any exception.
Returned records are not durable until that caller commits. Repository-managed
conversation/turn objects must not be edited directly. Normal sessions authorize
HTTP elsewhere; session freshness must be revalidated by the future chat service.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4
from typing import cast

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.application_session import ApplicationSession
from app.db.models.conversation import Conversation
from app.db.models.conversation_turn import ConversationTurn, TurnOperation, TurnStatus
from app.db.models.query_history import QueryHistory
from app.db.models.user import User


class ConversationNotFound(Exception):
    """Missing, deleted and foreign resources have the same outcome."""


class ConversationConflict(Exception):
    """A request identity was reused for a different canonical payload."""


class ConversationVersionConflict(ConversationConflict):
    """The supplied metadata/content revision is stale."""


class ConversationBusy(ConversationConflict):
    """The conversation already has a generating turn."""


class ConversationExecutionLost(ConversationConflict):
    """The exact execution is no longer live or eligible for publication."""


@dataclass(frozen=True)
class ConversationCreation:
    conversation: Conversation
    replayed: bool


@dataclass(frozen=True)
class TurnReservation:
    turn: ConversationTurn
    replayed: bool


def canonical_hash(payload: dict[str, object]) -> bytes:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).digest()


def _title(value: str) -> str:
    title = value.strip()
    if not 1 <= len(title) <= 256:
        raise ValueError("Conversation titles must contain 1 to 256 characters")
    return title


class ConversationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def _transaction(self, owner: UUID) -> None:
        if not isinstance(owner, UUID):
            raise ValueError("A verified server-side owner UUID is required")
        if not self.db.in_transaction():
            raise RuntimeError("ConversationRepository requires a caller-owned transaction")
        if any(isinstance(obj, (Conversation, ConversationTurn)) for obj in self.db.dirty):
            raise ValueError("Use repository methods to update conversation state")

    async def _database_now(self) -> datetime:
        with self.db.no_autoflush:
            value = await self.db.scalar(select(func.clock_timestamp()))
        if not isinstance(value, datetime):
            raise RuntimeError("PostgreSQL time is unavailable")
        return value

    async def _normal_owner(self, owner: UUID) -> None:
        with self.db.no_autoflush:
            found = await self.db.scalar(
                select(User.id).where(User.id == owner, ~User.google_id.startswith("demo:"))
            )
        if found is None:
            raise ConversationNotFound()

    async def get(self, owner: UUID, conversation_id: UUID) -> Conversation:
        self._transaction(owner)
        with self.db.no_autoflush:
            row = await self.db.scalar(
                select(Conversation)
                .where(
                    Conversation.id == conversation_id,
                    Conversation.owner_id == owner,
                    Conversation.deleted_at.is_(None),
                )
                .execution_options(populate_existing=True)
            )
        if row is None:
            raise ConversationNotFound()
        return row

    async def _lock(self, owner: UUID, conversation_id: UUID) -> Conversation:
        self._transaction(owner)
        with self.db.no_autoflush:
            row = await self.db.scalar(
                select(Conversation)
                .where(
                    Conversation.id == conversation_id,
                    Conversation.owner_id == owner,
                    Conversation.deleted_at.is_(None),
                )
                .with_for_update(of=Conversation)
                .execution_options(populate_existing=True)
            )
        if row is None:
            raise ConversationNotFound()
        return row

    async def create(
        self, owner: UUID, request_id: UUID, title: str = "New chat"
    ) -> ConversationCreation:
        self._transaction(owner)
        await self._normal_owner(owner)
        normalized = _title(title)
        digest = canonical_hash({"version": 1, "title": normalized})
        with self.db.no_autoflush:
            inserted = await self.db.scalar(
                insert(Conversation)
                .values(
                    id=uuid4(),
                    owner_id=owner,
                    title=normalized,
                    create_request_id=request_id,
                    create_payload_hash=digest,
                )
                .on_conflict_do_nothing(constraint="uq_conversations_create_request")
                .returning(Conversation.id)
            )
            row = await self.db.scalar(
                select(Conversation)
                .where(
                    Conversation.owner_id == owner,
                    Conversation.create_request_id == request_id,
                )
                .execution_options(populate_existing=True)
            )
        assert row is not None
        if row.deleted_at is not None:
            raise ConversationNotFound()
        if row.create_payload_hash != digest:
            raise ConversationConflict()
        return ConversationCreation(row, inserted is None)

    async def list_owned(
        self, owner: UUID, *, limit: int = 30, before: tuple[datetime, UUID] | None = None
    ) -> list[Conversation]:
        self._transaction(owner)
        if not 1 <= limit <= 100:
            raise ValueError("Conversation page size must be between 1 and 100")
        query = select(Conversation).where(
            Conversation.owner_id == owner, Conversation.deleted_at.is_(None)
        )
        if before is not None:
            activity, cid = before
            query = query.where(
                (Conversation.last_activity_at < activity)
                | ((Conversation.last_activity_at == activity) & (Conversation.id < cid))
            )
        with self.db.no_autoflush:
            return list(
                (
                    await self.db.scalars(
                        query.order_by(Conversation.last_activity_at.desc(), Conversation.id.desc())
                        .limit(limit)
                        .execution_options(populate_existing=True)
                    )
                ).all()
            )

    async def rename(
        self, owner: UUID, conversation_id: UUID, *, expected_version: int, title: str
    ) -> Conversation:
        row = await self._lock(owner, conversation_id)
        normalized = _title(title)
        if row.metadata_version != expected_version:
            raise ConversationVersionConflict()
        row.title = normalized
        row.title_is_manual = True
        row.metadata_version += 1
        await self.db.flush()
        return row

    async def delete(self, owner: UUID, conversation_id: UUID, *, expected_version: int) -> None:
        row = await self._lock(owner, conversation_id)
        if row.metadata_version != expected_version:
            raise ConversationVersionConflict()
        now = await self._database_now()
        row.deleted_at = now
        row.metadata_version += 1
        row.content_version += 1
        with self.db.no_autoflush:
            await self.db.execute(
                update(ConversationTurn)
                .where(
                    ConversationTurn.conversation_id == conversation_id,
                    ConversationTurn.owner_id == owner,
                    ConversationTurn.status == TurnStatus.RUNNING,
                )
                .values(
                    status=TurnStatus.INTERRUPTED,
                    finished_at=now,
                    error_code="CONVERSATION_DELETED",
                )
            )
        await self.db.flush()

    async def request(
        self, owner: UUID, conversation_id: UUID, request_id: UUID
    ) -> ConversationTurn | None:
        await self.get(owner, conversation_id)
        with self.db.no_autoflush:
            return cast(
                ConversationTurn | None,
                await self.db.scalar(
                    select(ConversationTurn)
                    .join(Conversation, Conversation.id == ConversationTurn.conversation_id)
                    .where(
                        Conversation.owner_id == owner,
                        Conversation.deleted_at.is_(None),
                        ConversationTurn.owner_id == owner,
                        ConversationTurn.conversation_id == conversation_id,
                        ConversationTurn.client_request_id == request_id,
                    )
                    .execution_options(populate_existing=True)
                ),
            )

    async def result(
        self, owner: UUID, conversation_id: UUID, request_id: UUID
    ) -> QueryHistory | None:
        """Load only the result referenced by this owned, visible request."""
        turn = await self.request(owner, conversation_id, request_id)
        if turn is None or turn.query_history_id is None:
            return None
        with self.db.no_autoflush:
            return cast(
                QueryHistory | None,
                await self.db.scalar(
                    select(QueryHistory)
                    .join(ConversationTurn, ConversationTurn.query_history_id == QueryHistory.id)
                    .join(Conversation, Conversation.id == ConversationTurn.conversation_id)
                    .where(
                        QueryHistory.id == turn.query_history_id,
                        QueryHistory.user_id == owner,
                        ConversationTurn.owner_id == owner,
                        ConversationTurn.id == turn.id,
                        Conversation.id == conversation_id,
                        Conversation.owner_id == owner,
                        Conversation.deleted_at.is_(None),
                    )
                ),
            )

    async def reserve(
        self,
        owner: UUID,
        conversation_id: UUID,
        *,
        request_id: UUID,
        question: str,
        session_id: UUID,
        expected_content_version: int,
        operation: TurnOperation = TurnOperation.ASK,
        source_turn_id: UUID | None = None,
        execution_seconds: int = 180,
    ) -> TurnReservation:
        row = await self._lock(owner, conversation_id)
        normalized = question.strip()
        if (
            not normalized
            or not isinstance(operation, TurnOperation)
            or not 1 <= execution_seconds <= 600
        ):
            raise ValueError("Invalid turn inputs")
        if (operation == TurnOperation.ASK) != (source_turn_id is None):
            raise ValueError("Only retry/regeneration has a source turn")
        digest = canonical_hash(
            {
                "version": 1,
                "conversation_id": str(conversation_id),
                "question": normalized,
                "operation": operation.value,
                "source_turn_id": str(source_turn_id) if source_turn_id else None,
                "base_content_version": expected_content_version,
            }
        )
        with self.db.no_autoflush:
            existing = await self.db.scalar(
                select(ConversationTurn)
                .where(
                    ConversationTurn.owner_id == owner,
                    ConversationTurn.client_request_id == request_id,
                )
                .execution_options(populate_existing=True)
            )
            if existing is not None:
                if existing.payload_hash != digest:
                    raise ConversationConflict()
                return TurnReservation(existing, True)
            active = await self.db.scalar(
                select(ConversationTurn.id).where(
                    ConversationTurn.conversation_id == conversation_id,
                    ConversationTurn.owner_id == owner,
                    ConversationTurn.status == TurnStatus.RUNNING,
                )
            )
            if active is not None:
                raise ConversationBusy()
            if row.content_version != expected_content_version:
                raise ConversationVersionConflict()
            session = await self.db.scalar(
                select(ApplicationSession.id).where(
                    ApplicationSession.id == session_id,
                    ApplicationSession.user_id == owner,
                    ApplicationSession.kind == "GOOGLE_ACCOUNT",
                )
            )
            if session is None:
                raise ConversationNotFound()
            history_end = row.next_sequence - 1
            if source_turn_id is not None:
                source = await self.db.scalar(
                    select(ConversationTurn).where(
                        ConversationTurn.id == source_turn_id,
                        ConversationTurn.owner_id == owner,
                        ConversationTurn.conversation_id == conversation_id,
                    )
                )
                if source is None:
                    raise ConversationNotFound()
                history_end = source.sequence - 1
            now = await self._database_now()
            tid = await self.db.scalar(
                insert(ConversationTurn)
                .values(
                    id=uuid4(),
                    owner_id=owner,
                    conversation_id=conversation_id,
                    client_request_id=request_id,
                    payload_hash=digest,
                    sequence=row.next_sequence,
                    original_question=normalized,
                    operation=operation.value,
                    source_turn_id=source_turn_id,
                    history_end_sequence=history_end,
                    initiating_session_id=session_id,
                    status=TurnStatus.RUNNING,
                    execution_id=uuid4(),
                    execution_deadline=now + timedelta(seconds=execution_seconds),
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing(constraint="uq_turns_owner_request")
                .returning(ConversationTurn.id)
            )
            if tid is None:
                other = await self.db.scalar(
                    select(ConversationTurn)
                    .where(
                        ConversationTurn.owner_id == owner,
                        ConversationTurn.client_request_id == request_id,
                    )
                    .execution_options(populate_existing=True)
                )
                assert other is not None
                if other.payload_hash != digest:
                    raise ConversationConflict()
                return TurnReservation(other, True)
        row.next_sequence += 1
        row.content_version += 1
        row.last_activity_at = now
        await self.db.flush()
        turn = await self.db.get(ConversationTurn, tid)
        assert turn is not None
        return TurnReservation(turn, False)

    async def turns(
        self,
        owner: UUID,
        conversation_id: UUID,
        *,
        before_sequence: int | None = None,
        limit: int = 50,
    ) -> list[ConversationTurn]:
        await self.get(owner, conversation_id)
        if not 1 <= limit <= 100:
            raise ValueError("Turn page size must be between 1 and 100")
        query = (
            select(ConversationTurn)
            .join(Conversation, Conversation.id == ConversationTurn.conversation_id)
            .where(
                ConversationTurn.owner_id == owner,
                ConversationTurn.conversation_id == conversation_id,
                Conversation.owner_id == owner,
                Conversation.deleted_at.is_(None),
            )
        )
        if before_sequence is not None:
            query = query.where(ConversationTurn.sequence < before_sequence)
        with self.db.no_autoflush:
            rows = list(
                (
                    await self.db.scalars(
                        query.order_by(ConversationTurn.sequence.desc())
                        .limit(limit)
                        .execution_options(populate_existing=True)
                    )
                ).all()
            )
        return list(reversed(rows))

    async def _execution(
        self, owner: UUID, conversation_id: UUID, turn_id: UUID, execution_id: UUID
    ) -> tuple[Conversation, ConversationTurn, datetime]:
        conversation = await self._lock(owner, conversation_id)
        with self.db.no_autoflush:
            turn = await self.db.scalar(
                select(ConversationTurn)
                .where(
                    ConversationTurn.id == turn_id,
                    ConversationTurn.owner_id == owner,
                    ConversationTurn.conversation_id == conversation_id,
                )
                .with_for_update(of=ConversationTurn)
                .execution_options(populate_existing=True)
            )
            now = await self._database_now()
        if turn is None:
            raise ConversationNotFound()
        if (
            turn.status != TurnStatus.RUNNING
            or turn.execution_id != execution_id
            or turn.execution_deadline <= now
        ):
            raise ConversationExecutionLost()
        return conversation, turn, now

    async def complete(
        self,
        owner: UUID,
        conversation_id: UUID,
        turn_id: UUID,
        *,
        execution_id: UUID,
        result_id: UUID,
        retrieval_count: int,
    ) -> ConversationTurn:
        conversation, turn, now = await self._execution(
            owner, conversation_id, turn_id, execution_id
        )
        if retrieval_count < 0:
            raise ValueError("Retrieval count cannot be negative")
        # Pending result rows may flush only AFTER execution authorization.
        await self.db.flush()
        result = await self.db.scalar(
            select(QueryHistory.id).where(
                QueryHistory.id == result_id, QueryHistory.user_id == owner
            )
        )
        if result is None:
            raise ConversationNotFound()
        turn.status = TurnStatus.COMPLETED
        turn.query_history_id = result_id
        turn.retrieval_count = retrieval_count
        turn.finished_at = now
        conversation.content_version += 1
        conversation.last_activity_at = now
        await self.db.flush()
        return turn

    async def fail(
        self,
        owner: UUID,
        conversation_id: UUID,
        turn_id: UUID,
        *,
        execution_id: UUID,
        error_code: str,
        interrupted: bool = False,
    ) -> ConversationTurn:
        conversation, turn, now = await self._execution(
            owner, conversation_id, turn_id, execution_id
        )
        if re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", error_code) is None:
            raise ValueError("Only nonsecret error categories may be stored")
        turn.status = TurnStatus.INTERRUPTED if interrupted else TurnStatus.FAILED
        turn.error_code = error_code
        turn.finished_at = now
        conversation.content_version += 1
        conversation.last_activity_at = now
        await self.db.flush()
        return turn
