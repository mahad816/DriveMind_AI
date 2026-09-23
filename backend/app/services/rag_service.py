"""Grounded RAG orchestration — retrieve, generate, cite, and persist."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.models.google_oauth_token import GoogleOAuthToken
from app.db.models.query_history import QueryHistory
from app.db.models.user import User
from app.evaluation.trace import (
    AbstentionReason,
    EvalTraceCollector,
    FileSnapshot,
    TraceOutcome,
    elapsed_ms,
)
from app.llm.base import ChatService
from app.llm.factory import get_chat_service
from app.llm.prompts import (
    NO_EVIDENCE_ANSWER,
    format_citation_snippet,
    normalize_answer_citations,
    select_prompt_chunks,
)
from app.retrieval.conversation_intent import classify_conversation_reference
from app.retrieval.base import Retriever
from app.retrieval.file_inventory import FileInventoryRetriever, build_inventory_context
from app.retrieval.file_target import FileTargetRetriever
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.query_router import QueryRoute, classify_query
from app.retrieval.types import RetrievedChunk
from app.retrieval.vector import VectorRetriever
from app.schemas.chat import ChatHistoryTurn
from app.schemas.query import CitationItem
from app.services.conversation_history import render_history_answer, select_history_turn


@dataclass
class RagResult:
    """Internal result from a grounded RAG question-answering run."""

    query_id: uuid.UUID
    user_id: uuid.UUID
    question: str
    answer: str
    citations: list[CitationItem]
    retrieval_count: int


class RagService:
    """Orchestrate retrieval, grounded answer generation, and query history.

    Query routing applies to ALL execution paths (linear and LangGraph agent):

    1. CONVERSATION_HISTORY → deterministic prior-message recall, no document retrieval.
    2. CHITCHAT       → generate_direct_answer(), no retrieval, no citations.
    3. FILE_INVENTORY → FileInventoryRetriever SQL path, no chunk retrieval, no citations.
    4. FILE_TARGET    → direct lookup of a named file + all its chunks, no hybrid noise.
    5. GROUNDED_RAG   → hybrid/vector retrieval then grounded answer.
                        Uses LangGraph agent when agent_graph_enabled=True,
                        otherwise the linear path.
    """

    def __init__(
        self,
        db: AsyncSession,
        settings: Settings | None = None,
        *,
        retriever: Retriever | None = None,
        chat_service: ChatService | None = None,
        persist_query_history: bool = True,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.persist_query_history = persist_query_history
        if retriever is not None:
            self.retriever = retriever
        elif self.settings.hybrid_retrieval_enabled:
            self.retriever = HybridRetriever(db, self.settings)
        else:
            self.retriever = VectorRetriever(db, self.settings)
        self.chat_service = chat_service or get_chat_service(self.settings)

    async def _resolve_user(self, user_id: uuid.UUID | None) -> User:
        if user_id is not None:
            user = await self.db.get(User, user_id)
            if user is None:
                raise ValueError("User not found")
            return user

        token_row = await self.db.scalar(select(GoogleOAuthToken).limit(1))
        if token_row is None:
            raise ValueError("No Google Drive connection found. Complete OAuth first.")
        user = await self.db.get(User, token_row.user_id)
        if user is None:
            raise ValueError("Connected Google account has no user record")
        return user

    async def ask(
        self,
        question: str,
        user_id: uuid.UUID | None = None,
        *,
        trace: EvalTraceCollector | None = None,
        conversation_id: str | None = None,
        history: Sequence[ChatHistoryTurn | Mapping[str, str]] = (),
        history_window_complete: bool = False,
    ) -> RagResult:
        """Answer a question and persist query history.

        Routing runs first regardless of agent_graph_enabled:
          CONVERSATION_HISTORY → deterministic prior-message recall, no sources.
          CHITCHAT       → direct reply, no retrieval, no sources shown.
          FILE_INVENTORY → SQL file search, no chunk retrieval, no sources shown.
          FILE_TARGET    → named file lookup, full file content, with citations.
          GROUNDED_RAG   → hybrid retrieval (LangGraph or linear).
        """
        normalized_question = question.strip()
        if trace is not None:
            trace.start(normalized_question)

        try:
            if not normalized_question:
                raise ValueError("Question must not be empty")
            if history and not conversation_id:
                raise ValueError("Non-empty history requires a conversation ID")
            return await self._ask_normalized(
                normalized_question,
                user_id,
                trace=trace,
                history=history,
                history_window_complete=history_window_complete,
            )
        except Exception as exc:
            if trace is not None:
                trace.record_error(exc)
            raise
        finally:
            if trace is not None:
                trace.finish()

    async def _ask_normalized(
        self,
        normalized_question: str,
        user_id: uuid.UUID | None,
        *,
        trace: EvalTraceCollector | None,
        history: Sequence[ChatHistoryTurn | Mapping[str, str]],
        history_window_complete: bool,
    ) -> RagResult:
        """Execute the existing routed pipeline for an already-normalized question."""
        if trace is not None:
            trace.set_stage("user_resolution")

        user = await self._resolve_user(user_id)

        # ── Route first — applies to ALL execution paths ──────────────────────
        if trace is not None:
            trace.set_stage("routing")
        route = classify_query(normalized_question)

        if route is QueryRoute.CONVERSATION_HISTORY:
            decision = classify_conversation_reference(normalized_question)
            if decision is None:
                raise RuntimeError("Conversation route requires a reference decision")
            selection = select_history_turn(
                history,
                target_role=decision.target_role,
                reference_kind=decision.reference_kind,
                history_window_complete=history_window_complete,
            )
            answer = render_history_answer(selection, decision.target_role)
            if trace is not None:
                trace.record_route(route, "conversation_history")
                trace.record_final(answer, [])
                trace.set_stage("persistence")
            query_id = await self._persist_query_history(
                user_id=user.id,
                question=normalized_question,
                answer=answer,
                citations=[],
            )
            return RagResult(
                query_id=query_id,
                user_id=user.id,
                question=normalized_question,
                answer=answer,
                citations=[],
                retrieval_count=0,
            )

        # ── 1. Chitchat bypass ────────────────────────────────────────────────
        if route is QueryRoute.CHITCHAT:
            generation_started = 0.0
            if trace is not None:
                trace.record_route(route, "chitchat")
                trace.set_stage("generation")
                generation_started = perf_counter()
            answer = await self.chat_service.generate_direct_answer(normalized_question)
            if trace is not None:
                trace.record_raw_generation(
                    answer,
                    [],
                    duration_ms=elapsed_ms(generation_started),
                )
                trace.record_final(answer, [])
                trace.set_stage("persistence")
            query_id = await self._persist_query_history(
                user_id=user.id,
                question=normalized_question,
                answer=answer,
                citations=[],
            )
            return RagResult(
                query_id=query_id,
                user_id=user.id,
                question=normalized_question,
                answer=answer,
                citations=[],
                retrieval_count=0,
            )

        # ── 2. File inventory path ────────────────────────────────────────────
        if route is QueryRoute.FILE_INVENTORY:
            retrieval_started = 0.0
            if trace is not None:
                trace.record_route(route, "file_inventory")
                trace.set_stage("inventory_lookup")
                retrieval_started = perf_counter()
            inv_retriever = FileInventoryRetriever(self.db)
            inv_result = await inv_retriever.search(normalized_question)
            context = build_inventory_context(inv_result)
            if trace is not None:
                trace.add_retrieval_duration(elapsed_ms(retrieval_started))
                trace.record_inventory(
                    total_count=inv_result.total_count,
                    files=tuple(
                        FileSnapshot(file_id=file.drive_file_id, filename=file.name)
                        for file in inv_result.files
                    ),
                    context=context,
                )
                trace.set_stage("generation")
                generation_started = perf_counter()
            else:
                generation_started = 0.0
            answer = await self.chat_service.generate_inventory_answer(normalized_question, context)
            if trace is not None:
                trace.record_raw_generation(
                    answer,
                    [],
                    duration_ms=elapsed_ms(generation_started),
                )
                trace.record_final(answer, [])
                trace.set_stage("persistence")
            query_id = await self._persist_query_history(
                user_id=user.id,
                question=normalized_question,
                answer=answer,
                citations=[],
            )
            return RagResult(
                query_id=query_id,
                user_id=user.id,
                question=normalized_question,
                answer=answer,
                citations=[],
                retrieval_count=inv_result.total_count,
            )

        # ── 3. Named file target path ─────────────────────────────────────────
        if route is QueryRoute.FILE_TARGET:
            retrieval_started = 0.0
            if trace is not None:
                trace.record_route(route, "file_target")
                trace.set_stage("file_target_lookup")
                retrieval_started = perf_counter()
            target_result = await FileTargetRetriever(self.db).search(
                normalized_question, user_id=user.id
            )
            if trace is not None:
                trace.add_retrieval_duration(elapsed_ms(retrieval_started))
                trace.record_file_target(
                    targets=tuple(target_result.targets),
                    files=tuple(
                        FileSnapshot(
                            file_id=file.drive_file_id,
                            filename=file.name,
                            status=str(file.status),
                        )
                        for file in target_result.files
                    ),
                    chunks=target_result.chunks,
                )
            if target_result.found:
                generation_started = 0.0
                if trace is not None:
                    trace.set_stage("context_selection")
                    # OpenAIChatService uses this same deterministic selector internally.
                    # The trace mirrors its output without changing the chat protocol.
                    traced_prompt_chunks = select_prompt_chunks(
                        normalized_question,
                        target_result.chunks,
                        max_context_chars=self.settings.rag_max_context_chars,
                    )
                    trace.record_prompt_chunks(
                        traced_prompt_chunks,
                        original_chunks=target_result.chunks,
                    )
                    trace.set_stage("generation")
                    generation_started = perf_counter()
                answer = await self.chat_service.generate_file_target_answer(
                    normalized_question,
                    target_result.chunks,
                    max_context_chars=self.settings.rag_max_context_chars,
                )
                generation_duration = elapsed_ms(generation_started) if trace is not None else 0.0
                prompt_chunks = select_prompt_chunks(
                    normalized_question,
                    target_result.chunks,
                    max_context_chars=self.settings.rag_max_context_chars,
                )
                all_citations = [_build_citation(chunk) for chunk in prompt_chunks]
                if trace is not None:
                    trace.record_raw_generation(
                        answer,
                        all_citations,
                        duration_ms=generation_duration,
                    )
                    trace.set_stage("citation_normalization")
                answer, file_citations = normalize_answer_citations(
                    answer,
                    all_citations,
                )
                if trace is not None:
                    trace.record_final(answer, file_citations)
                    trace.set_stage("persistence")
                query_id = await self._persist_query_history(
                    user_id=user.id,
                    question=normalized_question,
                    answer=answer,
                    citations=file_citations,
                )
                return RagResult(
                    query_id=query_id,
                    user_id=user.id,
                    question=normalized_question,
                    answer=answer,
                    citations=file_citations,
                    retrieval_count=len(target_result.chunks),
                )

            if target_result.files and target_result.not_indexed:
                file_names = ", ".join(f.name for f in target_result.files)
                answer = (
                    f'I found "{file_names}" in your Drive, but it is still being prepared. '
                    "Go to **Build knowledge** and run **Set up my assistant** to finish indexing it, "
                    "then ask again."
                )
                if trace is not None:
                    trace.record_abstention(AbstentionReason.FILE_NOT_INDEXED, answer)
                    trace.set_stage("persistence")
                query_id = await self._persist_query_history(
                    user_id=user.id,
                    question=normalized_question,
                    answer=answer,
                    citations=[],
                )
                return RagResult(
                    query_id=query_id,
                    user_id=user.id,
                    question=normalized_question,
                    answer=answer,
                    citations=[],
                    retrieval_count=0,
                )

            if target_result.targets and not target_result.files:
                names = ", ".join(f'"{t}"' for t in target_result.targets)
                answer = (
                    f"I could not find a file named {names} in your synced Google Drive. "
                    "Try **Build knowledge → Set up my assistant** if you added it recently."
                )
                if trace is not None:
                    trace.record_abstention(AbstentionReason.FILE_NOT_FOUND, answer)
                    trace.set_stage("persistence")
                query_id = await self._persist_query_history(
                    user_id=user.id,
                    question=normalized_question,
                    answer=answer,
                    citations=[],
                )
                return RagResult(
                    query_id=query_id,
                    user_id=user.id,
                    question=normalized_question,
                    answer=answer,
                    citations=[],
                    retrieval_count=0,
                )
            # No resolvable target — fall through to grounded RAG.

        # ── 4. Grounded RAG — LangGraph agent path ────────────────────────────
        if self.settings.agent_graph_enabled:
            from app.agents.drive_graph.runner import run_drive_graph

            if trace is not None:
                trace.record_route(route, "langgraph")
                trace.set_stage("retrieval")
            graph_result = await run_drive_graph(
                self.db,
                self.settings,
                question=normalized_question,
                user_id=user.id,
                chat_service=self.chat_service,
                trace=trace,
            )
            if trace is not None:
                trace.set_stage("persistence")
            query_id = await self._persist_query_history(
                user_id=user.id,
                question=graph_result.question,
                answer=graph_result.answer,
                citations=graph_result.citations,
            )
            return RagResult(
                query_id=query_id,
                user_id=user.id,
                question=graph_result.question,
                answer=graph_result.answer,
                citations=graph_result.citations,
                retrieval_count=graph_result.retrieval_count,
            )

        # ── 5. Grounded RAG — linear path ─────────────────────────────────────
        if trace is not None:
            trace.record_route(route, "linear")
            trace.set_stage("retrieval")
        evidence = None
        if self.settings.hybrid_retrieval_enabled and isinstance(self.retriever, HybridRetriever):
            if trace is None:
                evidence = await self.retriever.retrieve_with_grade(normalized_question)
            else:
                evidence = await self.retriever.retrieve_with_grade(
                    normalized_question,
                    trace=trace,
                )
            retrieved = evidence.chunks
        else:
            if trace is None:
                retrieved = await self.retriever.retrieve(normalized_question)
            else:
                trace.begin_attempt(
                    attempt_number=1,
                    working_query=normalized_question,
                    active_retrievers=("vector",),
                )
                retrieval_started = perf_counter()
                try:
                    retrieved = await self.retriever.retrieve(normalized_question)
                except Exception as exc:
                    trace.record_error(exc, stage="retrieval", component="vector")
                    trace.finish_attempt(1)
                    raise
                trace.record_retriever_result(
                    1,
                    "vector",
                    retrieved,
                    elapsed_ms(retrieval_started),
                )
                trace.finish_attempt(1)

        if not retrieved:
            answer = NO_EVIDENCE_ANSWER
            citations: list[CitationItem] = []
            if trace is not None:
                rejected = bool(
                    evidence is not None
                    and trace.trace.attempts
                    and trace.trace.attempts[0].reranked_candidates
                )
                trace.record_abstention(
                    AbstentionReason.EVIDENCE_REJECTED
                    if rejected
                    else AbstentionReason.NO_RETRIEVAL_EVIDENCE,
                    answer,
                )
        else:
            generation_started = 0.0
            if trace is not None:
                trace.set_stage("context_selection")
                # This mirrors the deterministic selector used by the current chat
                # provider without changing ChatService or the production prompt API.
                traced_prompt_chunks = select_prompt_chunks(
                    normalized_question,
                    retrieved,
                    max_context_chars=self.settings.rag_max_context_chars,
                )
                trace.record_prompt_chunks(
                    traced_prompt_chunks,
                    original_chunks=retrieved,
                )
                trace.set_stage("generation")
                generation_started = perf_counter()
            answer = await self.chat_service.generate_grounded_answer(
                normalized_question,
                retrieved,
                max_context_chars=self.settings.rag_max_context_chars,
            )
            generation_duration = elapsed_ms(generation_started) if trace is not None else 0.0
            prompt_chunks = select_prompt_chunks(
                normalized_question,
                retrieved,
                max_context_chars=self.settings.rag_max_context_chars,
            )
            all_citations = [_build_citation(chunk) for chunk in prompt_chunks]
            if trace is not None:
                trace.record_raw_generation(
                    answer,
                    all_citations,
                    duration_ms=generation_duration,
                )
                trace.set_stage("citation_normalization")
            answer, citations = normalize_answer_citations(
                answer,
                all_citations,
            )
            if trace is not None:
                trace.record_final(answer, citations, outcome=TraceOutcome.ANSWERED)

        if trace is not None:
            trace.set_stage("persistence")
        query_id = await self._persist_query_history(
            user_id=user.id,
            question=normalized_question,
            answer=answer,
            citations=citations,
        )

        return RagResult(
            query_id=query_id,
            user_id=user.id,
            question=normalized_question,
            answer=answer,
            citations=citations,
            retrieval_count=len(retrieved),
        )

    async def _persist_query_history(
        self,
        *,
        user_id: uuid.UUID,
        question: str,
        answer: str,
        citations: list[CitationItem],
    ) -> uuid.UUID:
        if not self.persist_query_history:
            return uuid.uuid4()

        history = QueryHistory(
            user_id=user_id,
            question=question,
            answer=answer,
            citations_json=[citation.model_dump(mode="json") for citation in citations],
        )
        self.db.add(history)
        await self.db.commit()
        await self.db.refresh(history)
        return history.id


def _build_citation(chunk: RetrievedChunk) -> CitationItem:
    snippet = format_citation_snippet(chunk.text)
    if not snippet:
        snippet = chunk.filename
    return CitationItem(
        chunk_id=chunk.chunk_id,
        drive_file_id=chunk.drive_file_id,
        filename=chunk.filename,
        snippet=snippet,
        score=chunk.score,
    )
