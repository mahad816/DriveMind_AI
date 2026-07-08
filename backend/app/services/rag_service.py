"""Grounded RAG orchestration — retrieve, generate, cite, and persist."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.models.google_oauth_token import GoogleOAuthToken
from app.db.models.query_history import QueryHistory
from app.db.models.user import User
from app.llm.base import ChatService
from app.llm.factory import get_chat_service
from app.llm.prompts import (
    NO_EVIDENCE_ANSWER,
    filter_citations_to_answer,
    format_citation_snippet,
    select_prompt_chunks,
)
from app.retrieval.base import Retriever
from app.retrieval.file_inventory import FileInventoryRetriever, build_inventory_context
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.query_router import QueryRoute, classify_query
from app.retrieval.types import RetrievedChunk
from app.retrieval.vector import VectorRetriever
from app.schemas.query import CitationItem


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

    1. CHITCHAT       → generate_direct_answer(), no retrieval, no citations.
    2. FILE_INVENTORY → FileInventoryRetriever SQL path, no chunk retrieval, no citations.
    3. GROUNDED_RAG   → hybrid/vector retrieval then grounded answer.
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
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
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
    ) -> RagResult:
        """Answer a question and persist query history.

        Routing runs first regardless of agent_graph_enabled:
          CHITCHAT       → direct reply, no retrieval, no sources shown.
          FILE_INVENTORY → SQL file search, no chunk retrieval, no sources shown.
          GROUNDED_RAG   → hybrid retrieval (LangGraph or linear).
        """
        normalized_question = question.strip()
        if not normalized_question:
            raise ValueError("Question must not be empty")

        user = await self._resolve_user(user_id)

        # ── Route first — applies to ALL execution paths ──────────────────────
        route = classify_query(normalized_question)

        # ── 1. Chitchat bypass ────────────────────────────────────────────────
        if route is QueryRoute.CHITCHAT:
            answer = await self.chat_service.generate_direct_answer(normalized_question)
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
            inv_retriever = FileInventoryRetriever(self.db)
            inv_result = await inv_retriever.search(normalized_question)
            context = build_inventory_context(inv_result)
            answer = await self.chat_service.generate_inventory_answer(
                normalized_question, context
            )
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

        # ── 3. Grounded RAG — LangGraph agent path ────────────────────────────
        if self.settings.agent_graph_enabled:
            from app.agents.drive_graph.runner import run_drive_graph

            graph_result = await run_drive_graph(
                self.db,
                self.settings,
                question=normalized_question,
                user_id=user.id,
                chat_service=self.chat_service,
            )
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

        # ── 4. Grounded RAG — linear path ─────────────────────────────────────
        if self.settings.hybrid_retrieval_enabled and isinstance(self.retriever, HybridRetriever):
            evidence = await self.retriever.retrieve_with_grade(normalized_question)
            retrieved = evidence.chunks
        else:
            retrieved = await self.retriever.retrieve(normalized_question)

        if not retrieved:
            answer = NO_EVIDENCE_ANSWER
            citations: list[CitationItem] = []
        else:
            answer = await self.chat_service.generate_grounded_answer(
                normalized_question,
                retrieved,
                max_context_chars=self.settings.rag_max_context_chars,
            )
            prompt_chunks = select_prompt_chunks(
                normalized_question,
                retrieved,
                max_context_chars=self.settings.rag_max_context_chars,
            )
            all_citations = [_build_citation(chunk) for chunk in prompt_chunks]
            citations = cast(
                list[CitationItem],
                filter_citations_to_answer(answer, all_citations),  # type: ignore[arg-type]
            )

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
