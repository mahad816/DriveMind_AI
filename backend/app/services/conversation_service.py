"""Request-owned SQL transactions for metadata APIs, without provider calls."""

import base64
import binascii
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, AwareDatetime, ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import ApplicationSessionKind
from app.db.models.application_session import ApplicationSession
from app.db.models.conversation_turn import TurnOperation, TurnStatus
from app.schemas.conversation import (
    ConversationCreate,
    ConversationRead,
    ConversationList,
    ConversationDetail,
    ConversationTurnRead,
    ConversationRename,
    SavedCitation,
)
from app.security.principal import ApplicationPrincipal
from app.services.conversation_repository import ConversationRepository


class ConversationSessionExpired(Exception):
    pass


class InvalidConversationCursor(Exception):
    pass


class _Cursor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1]
    owner: UUID
    activity: AwareDatetime
    id: UUID


def encode_cursor(owner: UUID, activity: datetime, cid: UUID) -> str:
    raw = _Cursor(version=1, owner=owner, activity=activity, id=cid).model_dump_json().encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(value: str, owner: UUID) -> tuple[datetime, UUID]:
    try:
        if not 1 <= len(value) <= 512:
            raise ValueError()
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        cursor = _Cursor.model_validate_json(raw)
        if cursor.owner != owner:
            raise ValueError()
        return cursor.activity, cursor.id
    except (ValueError, binascii.Error, ValidationError):
        raise InvalidConversationCursor() from None


class ConversationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repository = ConversationRepository(db)

    async def _live_session(self, principal: ApplicationPrincipal, *, lock: bool) -> None:
        query = select(ApplicationSession.expires_at, ApplicationSession.revoked_at).where(
            ApplicationSession.id == principal.session_id,
            ApplicationSession.user_id == principal.corpus_user_id,
            ApplicationSession.kind == ApplicationSessionKind.GOOGLE_ACCOUNT,
        )
        if lock:
            query = query.with_for_update(read=True, of=ApplicationSession)
        with self.db.no_autoflush:
            row = (await self.db.execute(query)).one_or_none()
            now = await self.db.scalar(select(func.clock_timestamp()))
        if not isinstance(now, datetime):
            raise RuntimeError("PostgreSQL time is unavailable")
        if row is None or row.revoked_at is not None or row.expires_at <= now:
            raise ConversationSessionExpired()

    @asynccontextmanager
    async def transaction(
        self, principal: ApplicationPrincipal, *, write: bool
    ) -> AsyncIterator[None]:
        # Authentication already autobegins this request-owned session. Do not open
        # a second transaction; this layer commits/rolls back that exact unit.
        if not self.db.in_transaction():
            await self.db.begin()
        try:
            await self.db.execute(text("SET LOCAL lock_timeout = '2s'"))
            await self.db.execute(text("SET LOCAL statement_timeout = '10s'"))
            if write:
                await self._live_session(principal, lock=True)
            yield
            if write:
                # Fresh expiry check after potentially blocking repository SQL.
                await self._live_session(principal, lock=False)
                await self.db.commit()
            else:
                await self.db.rollback()  # Read DTOs already materialized; no writes.
        except BaseException:
            await self.db.rollback()
            raise

    async def create(
        self, principal: ApplicationPrincipal, body: ConversationCreate
    ) -> tuple[ConversationRead, bool]:
        async with self.transaction(principal, write=True):
            made = await self.repository.create(
                principal.corpus_user_id, body.create_request_id, body.title
            )
            response = ConversationRead.model_validate(made.conversation)
            replayed = made.replayed
        return response, replayed

    async def list_owned(
        self, principal: ApplicationPrincipal, *, limit: int, cursor: str | None
    ) -> ConversationList:
        owner = principal.corpus_user_id
        before = decode_cursor(cursor, owner) if cursor is not None else None
        async with self.transaction(principal, write=False):
            rows = await self.repository.list_owned(owner, limit=limit, before=before)
            result = ConversationList(
                conversations=[ConversationRead.model_validate(c) for c in rows],
                next_cursor=encode_cursor(owner, rows[-1].last_activity_at, rows[-1].id)
                if len(rows) == limit
                else None,
            )
        return result

    async def detail(
        self, principal: ApplicationPrincipal, cid: UUID, *, limit: int, before_sequence: int | None
    ) -> ConversationDetail:
        async with self.transaction(principal, write=False):
            conversation = await self.repository.get(principal.corpus_user_id, cid, for_share=True)
            metadata = ConversationRead.model_validate(conversation)
            rows = await self.repository.turns_with_results(
                principal.corpus_user_id, cid, limit=limit, before_sequence=before_sequence
            )
            turns = []
            for turn, history in rows:
                complete = turn.status == TurnStatus.COMPLETED
                if complete != (history is not None):
                    raise ValueError("Stored conversation result is inconsistent")
                turns.append(
                    ConversationTurnRead(
                        id=turn.id,
                        client_request_id=turn.client_request_id,
                        sequence=turn.sequence,
                        question=turn.original_question,
                        operation=TurnOperation(turn.operation),
                        source_turn_id=turn.source_turn_id,
                        status=TurnStatus(turn.status),
                        created_at=turn.created_at,
                        updated_at=turn.updated_at,
                        finished_at=turn.finished_at,
                        error_code="TURN_FAILED"
                        if turn.status == TurnStatus.FAILED
                        else "TURN_INTERRUPTED"
                        if turn.status == TurnStatus.INTERRUPTED
                        else None,
                        query_id=history.id if history else None,
                        answer=history.answer if history else None,
                        citations=[SavedCitation.model_validate(c) for c in history.citations_json]
                        if history
                        else [],
                        retrieval_count=turn.retrieval_count,
                    )
                )
            result = ConversationDetail(
                conversation=metadata,
                turns=turns,
                next_before_sequence=turns[0].sequence if len(turns) == limit else None,
            )
            if len(result.model_dump_json().encode()) > 2097152:
                raise ValueError("Conversation page exceeds the response limit")
        return result

    async def rename(
        self, principal: ApplicationPrincipal, cid: UUID, body: ConversationRename
    ) -> ConversationRead:
        async with self.transaction(principal, write=True):
            row = await self.repository.rename(
                principal.corpus_user_id,
                cid,
                expected_version=body.expected_metadata_version,
                title=body.title,
            )
            # SQL onupdate expires this column; load it asynchronously before
            # DTO serialization and commit, never through lazy post-commit IO.
            await self.db.refresh(row, attribute_names=["updated_at"])
            result = ConversationRead.model_validate(row)
        return result

    async def delete(self, principal: ApplicationPrincipal, cid: UUID, version: int) -> None:
        async with self.transaction(principal, write=True):
            await self.repository.delete(principal.corpus_user_id, cid, expected_version=version)
