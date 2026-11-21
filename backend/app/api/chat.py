"""Grounded chat routes."""

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.embeddings.base import EmbeddingConfigurationError, EmbeddingError
from app.embeddings.vector_store import VectorStoreError
from app.llm.base import ChatConfigurationError, ChatError
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.paid_question_quota import PaidQuestionQuota
from app.services.rag_service import RagResult, RagService
from app.api.dependencies import require_chat_user
from app.api.paid_question import admit_or_refuse, get_paid_question_quota
from app.core.config import Settings, get_settings
from app.core.public_safety import DemoChatLimits, public_error_detail

router = APIRouter(prefix="/chat")


def get_rag_service(db: AsyncSession = Depends(get_db)) -> RagService:
    """Dependency provider for grounded RAG service."""
    return RagService(db=db)


async def _ask(payload: ChatRequest, service: RagService, user_id: UUID) -> RagResult:
    if {"conversation_id", "history", "history_window_complete"} & payload.model_fields_set:
        return await service.ask(
            payload.question,
            user_id=user_id,
            conversation_id=payload.conversation_id,
            history=[turn.model_dump() for turn in payload.history],
            history_window_complete=payload.history_window_complete,
        )
    return await service.ask(payload.question, user_id=user_id)


@router.post("", summary="Ask a grounded question over indexed Drive content")
async def ask_grounded_question(
    payload: ChatRequest,
    request: Request,
    user_id: UUID = Depends(require_chat_user),
    service: RagService = Depends(get_rag_service),
    settings: Settings = Depends(get_settings),
    quota: PaidQuestionQuota | None = Depends(get_paid_question_quota),
) -> ChatResponse:
    """Retrieve relevant chunks, generate a grounded answer, and return citations."""
    try:
        limits: DemoChatLimits = request.app.state.demo_chat_limits
        async with limits.execution(settings):
            if settings.demo_mode:
                result = await _ask(payload, service, user_id)
            else:
                # Owner mode (M0-SEC ticket 06): admit before any provider call (429 / 503), run
                # under an explicit execution bound, and settle the attempt in one `finally`:
                # finished if a provider request began, released otherwise. Each request is its
                # own attempt (there is no idempotency key).
                admission = await admit_or_refuse(quota, user_id)
                async with admission.running():
                    async with asyncio.timeout(settings.chat_execution_seconds):
                        result = await _ask(payload, service, user_id)
    except (ValueError, TimeoutError) as exc:
        # TimeoutError: the Owner-mode execution bound (or a provider timeout), mapped explicitly
        # to the existing safe 503 rather than a 500.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=public_error_detail(exc),
        ) from exc
    except (
        EmbeddingConfigurationError,
        EmbeddingError,
        VectorStoreError,
        ChatConfigurationError,
        ChatError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=public_error_detail(exc),
        ) from exc

    return ChatResponse(
        query_id=result.query_id,
        user_id=result.user_id,
        answer=result.answer,
        citations=result.citations,
        retrieval_count=result.retrieval_count,
        message="Answer generated from indexed Drive content",
    )
