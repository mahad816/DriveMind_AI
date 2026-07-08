"""Grounded RAG orchestration — retrieve, generate, cite, and persist."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

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
    format_citation_snippet,
    select_prompt_chunks,
)
from app.retrieval.base import Retriever
from app.retrieval.hybrid import HybridRetriever
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
    """Orchestrate retrieval, grounded answer generation, and query history."""

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
        """Answer a question using retrieved Drive chunks and persist query history."""
        normalized_question = question.strip()
        if not normalized_question:
            raise ValueError("Question must not be empty")

        user = await self._resolve_user(user_id)
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
            citations = [_build_citation(chunk) for chunk in prompt_chunks]

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
