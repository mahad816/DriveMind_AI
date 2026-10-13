"""Bounded request-owned RAG: durable admission, no detached generation tasks."""

import asyncio
import math
from collections.abc import Callable
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.enums import DriveFileStatus
from app.db.models import Chunk, Document, DriveFile, QueryHistory
from app.db.models.conversation_turn import TurnStatus
from app.schemas.conversation import (
    ConversationSubmit,
    ConversationSubmission,
    ConversationTurnStatus,
    SavedCitation,
)
from app.security.principal import ApplicationPrincipal
from app.services.conversation_repository import (
    ConversationRepository,
    ConversationNotFound,
    ConversationExecutionLost,
)
from app.services.conversation_service import (
    ConversationService,
    ConversationSessionExpired,
    serialize_turn,
)
from app.services.rag_service import RagService, RagResult


class CitationAuthorityLost(Exception):
    pass


class ConversationChatService:
    def __init__(
        self,
        db: AsyncSession,
        settings: Settings,
        *,
        rag_factory: Callable[[AsyncSession, Settings], RagService] | None = None,
        generation_timeout: float = 120.0,
        execution_seconds: int = 180,
    ) -> None:
        if not isinstance(db.bind, AsyncEngine) or settings.demo_mode:
            raise ValueError("Normal chat requires an engine-bound request session")
        if (
            not math.isfinite(generation_timeout)
            or not 0.01 <= generation_timeout <= 120
            or not generation_timeout < execution_seconds <= 600
        ):
            raise ValueError("Conversation generation must have bounded execution settings")
        self.db, self.settings = db, settings
        self.sessions = async_sessionmaker(db.bind, expire_on_commit=False)
        # Parallel retrievers inherit this engine's READ ONLY characteristic.
        # SQLAlchemy restores it on pool return; no session-wide SET leaks.
        self.read_sessions = async_sessionmaker(
            db.bind.execution_options(postgresql_readonly=True), expire_on_commit=False
        )
        self.rag_factory = rag_factory or (
            lambda db, settings: RagService(db, settings, persist_query_history=False)
        )
        self.generation_timeout, self.execution_seconds = generation_timeout, execution_seconds

    async def _status(
        self, db: AsyncSession, owner: UUID, cid: UUID, tid: UUID
    ) -> ConversationTurnStatus:
        repo = ConversationRepository(db)
        await repo.get(owner, cid, for_share=True)
        turn, result = await repo.turn_with_result(owner, cid, tid)
        now = await db.scalar(select(func.clock_timestamp()))
        if not isinstance(now, datetime):
            raise RuntimeError("PostgreSQL time unavailable")
        return ConversationTurnStatus(
            **serialize_turn(turn, result).model_dump(),
            execution_expired=turn.status == TurnStatus.RUNNING and turn.execution_deadline <= now,
        )

    async def status(
        self, principal: ApplicationPrincipal, cid: UUID, tid: UUID
    ) -> ConversationTurnStatus:
        async with ConversationService(self.db).transaction(principal, write=False):
            response = await self._status(self.db, principal.corpus_user_id, cid, tid)
            await ConversationService(self.db)._live_session(principal, lock=False)
        return response

    async def interrupt_expired(
        self, principal: ApplicationPrincipal, cid: UUID, tid: UUID
    ) -> ConversationTurnStatus:
        async with ConversationService(self.db).transaction(principal, write=True):
            repo = ConversationRepository(self.db)
            await repo._lock(principal.corpus_user_id, cid)
            turn, _ = await repo.turn_with_result(principal.corpus_user_id, cid, tid)
            await repo.interrupt_attempt(
                principal.corpus_user_id,
                cid,
                tid,
                execution_id=turn.execution_id,
                error_code="EXECUTION_EXPIRED",
                expired_only=True,
            )
            response = await self._status(self.db, principal.corpus_user_id, cid, tid)
        return response

    async def _context(
        self, db: AsyncSession, owner: UUID, cid: UUID, boundary: int
    ) -> tuple[list[dict[str, str]], bool]:
        pairs, omitted = await ConversationRepository(db).completed_context(owner, cid, boundary)
        selected: list[list[dict[str, str]]] = []
        remaining = 24000
        complete = not omitted and len(pairs) <= 4
        for turn, result in pairs[:4]:
            question, answer = turn.original_question, result.answer
            size = len(question) + len(answer)
            if len(question) > 8000 or len(answer) > 8000 or size > remaining:
                complete = False
                break  # Never substitute an older answer as the latest answer.
            selected.append(
                [{"role": "user", "text": question}, {"role": "assistant", "text": answer}]
            )
            remaining -= size
        return [message for pair in reversed(selected) for message in pair], complete

    async def _cleanup(
        self,
        principal: ApplicationPrincipal,
        cid: UUID,
        tid: UUID,
        execution_id: UUID,
        code: str,
        *,
        interrupted: bool,
    ) -> None:
        # Fresh transaction after rollback/cancellation. Failure leaves RUNNING
        # durable and explicitly classifiable by the expired-interruption route.
        try:
            async with asyncio.timeout(10):
                async with self.sessions() as db, db.begin():
                    await db.execute(text("SET LOCAL lock_timeout='2s'"))
                    await db.execute(text("SET LOCAL statement_timeout='10s'"))
                    repo = ConversationRepository(db)
                    if interrupted:
                        await repo.interrupt_attempt(
                            principal.corpus_user_id,
                            cid,
                            tid,
                            execution_id=execution_id,
                            error_code=code,
                        )
                    else:
                        try:
                            await repo.fail(
                                principal.corpus_user_id,
                                cid,
                                tid,
                                execution_id=execution_id,
                                error_code=code,
                            )
                        except ConversationExecutionLost:
                            await repo.interrupt_attempt(
                                principal.corpus_user_id,
                                cid,
                                tid,
                                execution_id=execution_id,
                                error_code="EXECUTION_EXPIRED",
                                expired_only=True,
                            )
        except (ConversationNotFound, ConversationExecutionLost):
            return  # Deleted or newer/terminal execution cannot be overwritten.
        except Exception:
            # No success is returned. Durable expiry remains the recovery boundary.
            from app.core.public_safety import public_error_detail

            public_error_detail(RuntimeError("Conversation terminal persistence unavailable"))

    async def _citations(self, db: AsyncSession, owner: UUID, result: RagResult) -> None:
        if result.user_id != owner:
            raise CitationAuthorityLost()
        ids = {c.chunk_id for c in result.citations}
        if not ids:
            return
        rows = (
            await db.execute(
                select(Chunk.id, DriveFile.id)
                .join(Document, Chunk.document_id == Document.id)
                .join(DriveFile, Document.drive_file_id == DriveFile.id)
                .where(
                    Chunk.id.in_(ids),
                    DriveFile.user_id == owner,
                    DriveFile.status == DriveFileStatus.INDEXED,
                )
                .with_for_update(read=True, of=[Chunk, Document, DriveFile])
            )
        ).all()
        lineage = {r[0]: r[1] for r in rows}
        if any(lineage.get(c.chunk_id) != c.drive_file_id for c in result.citations):
            raise CitationAuthorityLost()

    async def submit(
        self, principal: ApplicationPrincipal, cid: UUID, body: ConversationSubmit
    ) -> tuple[ConversationSubmission, int]:
        async with ConversationService(self.db).transaction(principal, write=True):
            reserved = await ConversationRepository(self.db).reserve(
                principal.corpus_user_id,
                cid,
                request_id=body.client_request_id,
                question=body.question,
                session_id=principal.session_id,
                expected_content_version=body.expected_content_version,
                execution_seconds=self.execution_seconds,
            )
            turn = reserved.turn
            tid, execution_id, boundary = turn.id, turn.execution_id, turn.history_end_sequence
            response = ConversationSubmission(
                turn=await self._status(self.db, principal.corpus_user_id, cid, tid),
                replayed=reserved.replayed,
            )
        if reserved.replayed:
            return response, 202 if response.turn.status == TurnStatus.RUNNING else 200
        # Release the request's admission transaction before any external IO.
        task = asyncio.current_task()
        initial_cancellations = task.cancelling() if task is not None else 0
        try:
            async with asyncio.timeout(self.generation_timeout) as budget:
                async with self.read_sessions() as db:
                    await db.execute(text("SET LOCAL statement_timeout='10s'"))
                    history, complete = await self._context(
                        db, principal.corpus_user_id, cid, boundary
                    )
                    rag = self.rag_factory(db, self.settings)
                    if rag.persist_query_history:
                        raise ValueError("Generation cannot independently persist results")
                    result = await rag.ask(
                        body.question,
                        principal.corpus_user_id,
                        conversation_id=str(cid),
                        history=history,
                        history_window_complete=complete,
                    )
            if budget.expired():
                raise TimeoutError()
            if task is not None and task.cancelling() > initial_cancellations:
                raise asyncio.CancelledError()
            # Validate bounded canonical fields before entering publication.
            citations = [SavedCitation.model_validate(c) for c in result.citations]
            if (
                not result.answer.strip()
                or len(result.answer) > 131072
                or len(citations) > 64
                or result.retrieval_count < 0
            ):
                raise ValueError("Generation result exceeds publication contract")
            async with self.sessions() as db:
                async with ConversationService(db).transaction(principal, write=True):
                    repo = ConversationRepository(db)
                    _, active, _ = await repo._execution(
                        principal.corpus_user_id, cid, tid, execution_id
                    )
                    if active.initiating_session_id != principal.session_id:
                        raise ConversationExecutionLost()
                    await self._citations(db, principal.corpus_user_id, result)
                    stored = QueryHistory(
                        id=uuid4(),
                        user_id=principal.corpus_user_id,
                        question=result.question,
                        answer=result.answer,
                        citations_json=[c.model_dump(mode="json") for c in citations],
                    )
                    db.add(stored)
                    await repo.complete(
                        principal.corpus_user_id,
                        cid,
                        tid,
                        execution_id=execution_id,
                        result_id=stored.id,
                        retrieval_count=result.retrieval_count,
                    )
                    response = ConversationSubmission(
                        turn=await self._status(db, principal.corpus_user_id, cid, tid),
                        replayed=False,
                    )
            return response, 200
        except asyncio.CancelledError:
            await self._cleanup(
                principal, cid, tid, execution_id, "REQUEST_CANCELLED", interrupted=True
            )
            raise
        except TimeoutError:
            await self._cleanup(
                principal, cid, tid, execution_id, "GENERATION_TIMEOUT", interrupted=True
            )
        except (ConversationSessionExpired, ConversationNotFound) as exc:
            await self._cleanup(
                principal,
                cid,
                tid,
                execution_id,
                "SESSION_UNAVAILABLE"
                if isinstance(exc, ConversationSessionExpired)
                else "CONVERSATION_DELETED",
                interrupted=True,
            )
            raise
        except ConversationExecutionLost:
            await self._cleanup(
                principal, cid, tid, execution_id, "EXECUTION_EXPIRED", interrupted=True
            )
        except CitationAuthorityLost:
            await self._cleanup(
                principal, cid, tid, execution_id, "SOURCE_CHANGED", interrupted=False
            )
        except Exception:
            await self._cleanup(
                principal, cid, tid, execution_id, "GENERATION_OR_STORAGE_FAILED", interrupted=False
            )
        # Observe with a fresh authenticated read; never invent success on an
        # uncertain commit. A confirmed completed publication may safely replay.
        async with self.sessions() as db:
            async with ConversationService(db).transaction(principal, write=False):
                await ConversationService(db)._live_session(principal, lock=False)
                response = ConversationSubmission(
                    turn=await self._status(db, principal.corpus_user_id, cid, tid), replayed=False
                )
        return response, 200 if response.turn.status == TurnStatus.COMPLETED else 503
