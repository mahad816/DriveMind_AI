"""Grounded chat routes."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.embeddings.base import EmbeddingConfigurationError, EmbeddingError
from app.embeddings.vector_store import VectorStoreError
from app.llm.base import ChatConfigurationError, ChatError
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.rag_service import RagService
from app.api.dependencies import require_demo_index
from app.core.config import Settings, get_settings
from app.core.public_safety import DemoChatLimits, public_error_detail

router = APIRouter(prefix="/chat", dependencies=[Depends(require_demo_index)])


def get_rag_service(db: AsyncSession = Depends(get_db)) -> RagService:
    """Dependency provider for grounded RAG service."""
    return RagService(db=db)


@router.post("", summary="Ask a grounded question over indexed Drive content")
async def ask_grounded_question(
    payload: ChatRequest,
    request: Request,
    service: RagService = Depends(get_rag_service),
    settings: Settings = Depends(get_settings),
) -> ChatResponse:
    """Retrieve relevant chunks, generate a grounded answer, and return citations."""
    try:
        limits: DemoChatLimits = request.app.state.demo_chat_limits
        async with limits.execution(settings):
            if {"conversation_id", "history", "history_window_complete"} & payload.model_fields_set:
                result = await service.ask(
                    payload.question,
                    conversation_id=payload.conversation_id,
                    history=[turn.model_dump() for turn in payload.history],
                    history_window_complete=payload.history_window_complete,
                )
            else:
                result = await service.ask(payload.question)
    except ValueError as exc:
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
