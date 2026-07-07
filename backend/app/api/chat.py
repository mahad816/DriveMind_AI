"""Grounded chat routes."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.embeddings.base import EmbeddingConfigurationError, EmbeddingError
from app.embeddings.vector_store import VectorStoreError
from app.llm.base import ChatConfigurationError, ChatError
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.rag_service import RagService

router = APIRouter(prefix="/chat")


def get_rag_service(db: AsyncSession = Depends(get_db)) -> RagService:
    """Dependency provider for grounded RAG service."""
    return RagService(db=db)


@router.post("", summary="Ask a grounded question over indexed Drive content")
async def ask_grounded_question(
    payload: ChatRequest,
    service: RagService = Depends(get_rag_service),
) -> ChatResponse:
    """Retrieve relevant chunks, generate a grounded answer, and return citations."""
    try:
        result = await service.ask(payload.question)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
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
            detail=str(exc),
        ) from exc

    return ChatResponse(
        query_id=result.query_id,
        user_id=result.user_id,
        answer=result.answer,
        citations=result.citations,
        retrieval_count=result.retrieval_count,
        message="Answer generated from indexed Drive content",
    )
