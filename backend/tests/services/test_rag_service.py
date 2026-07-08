"""Tests for grounded RAG orchestration service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import Settings
from app.db.models.google_oauth_token import GoogleOAuthToken
from app.db.models.query_history import QueryHistory
from app.db.models.user import User
from app.llm.prompts import NO_EVIDENCE_ANSWER
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.types import RetrievedChunk
from app.retrieval.vector import VectorRetriever
from app.services.rag_service import RagService

USER_ID = uuid.uuid4()
CHUNK_ID = uuid.uuid4()
DRIVE_FILE_ID = uuid.uuid4()
DOCUMENT_ID = uuid.uuid4()
QUERY_ID = uuid.uuid4()
TOKEN_ROW = GoogleOAuthToken(
    id=uuid.uuid4(),
    user_id=USER_ID,
    access_token="access",
    refresh_token="refresh",
    token_expiry=datetime.now(UTC),
    scopes="https://www.googleapis.com/auth/drive.readonly",
)
USER = User(id=USER_ID, email="user@example.com", google_id="gid-1")


def _retrieved_chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=CHUNK_ID,
        document_id=DOCUMENT_ID,
        drive_file_id=DRIVE_FILE_ID,
        filename="notes.txt",
        mime_type="text/plain",
        modified_at=datetime.now(UTC),
        chunk_index=0,
        text="Tensile strength is a key materials property.",
        score=0.91,
    )


@pytest.fixture
def mock_db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.fixture
def mock_retriever() -> AsyncMock:
    retriever = AsyncMock()
    retriever.retrieve = AsyncMock(return_value=[_retrieved_chunk()])
    return retriever


@pytest.fixture
def mock_chat() -> AsyncMock:
    chat = AsyncMock()
    chat.generate_grounded_answer = AsyncMock(
        return_value="Tensile strength is discussed in [1].",
    )
    return chat


@pytest.fixture
def service(
    mock_db: AsyncMock,
    mock_retriever: AsyncMock,
    mock_chat: AsyncMock,
) -> RagService:
    return RagService(
        db=mock_db,
        settings=MagicMock(rag_max_context_chars=12000, hybrid_retrieval_enabled=False),
        retriever=mock_retriever,
        chat_service=mock_chat,
    )


@pytest.mark.asyncio
async def test_ask_generates_answer_and_persists_history(
    service: RagService,
    mock_db: AsyncMock,
    mock_retriever: AsyncMock,
    mock_chat: AsyncMock,
) -> None:
    mock_db.get = AsyncMock(return_value=USER)
    mock_db.scalar = AsyncMock(return_value=TOKEN_ROW)

    async def refresh_history(history: QueryHistory) -> None:
        history.id = QUERY_ID

    mock_db.refresh = AsyncMock(side_effect=refresh_history)

    result = await service.ask("What is tensile strength?")

    assert result.query_id == QUERY_ID
    assert result.user_id == USER_ID
    assert result.answer == "Tensile strength is discussed in [1]."
    assert result.retrieval_count == 1
    assert len(result.citations) == 1
    assert result.citations[0].chunk_id == CHUNK_ID
    assert result.citations[0].filename == "notes.txt"
    assert "Tensile strength" in result.citations[0].snippet
    mock_retriever.retrieve.assert_awaited_once_with("What is tensile strength?")
    mock_chat.generate_grounded_answer.assert_awaited_once()
    mock_db.commit.assert_awaited_once()
    added = mock_db.add.call_args.args[0]
    assert isinstance(added, QueryHistory)
    assert added.question == "What is tensile strength?"
    assert added.answer == "Tensile strength is discussed in [1]."
    assert len(added.citations_json) == 1


@pytest.mark.asyncio
async def test_ask_returns_no_evidence_answer_without_retrieval(
    service: RagService,
    mock_db: AsyncMock,
    mock_retriever: AsyncMock,
    mock_chat: AsyncMock,
) -> None:
    mock_db.get = AsyncMock(return_value=USER)
    mock_db.scalar = AsyncMock(return_value=TOKEN_ROW)
    mock_retriever.retrieve = AsyncMock(return_value=[])

    async def refresh_history(history: QueryHistory) -> None:
        history.id = QUERY_ID

    mock_db.refresh = AsyncMock(side_effect=refresh_history)

    result = await service.ask("What is quantum foam?")

    assert result.answer == NO_EVIDENCE_ANSWER
    assert result.citations == []
    assert result.retrieval_count == 0
    mock_chat.generate_grounded_answer.assert_not_awaited()
    added = mock_db.add.call_args.args[0]
    assert added.citations_json == []


@pytest.mark.asyncio
async def test_ask_rejects_empty_question(service: RagService) -> None:
    with pytest.raises(ValueError, match="Question must not be empty"):
        await service.ask("   ")


@pytest.mark.asyncio
async def test_ask_resolves_explicit_user_id(
    service: RagService,
    mock_db: AsyncMock,
    mock_retriever: AsyncMock,
) -> None:
    mock_db.get = AsyncMock(return_value=USER)
    mock_retriever.retrieve = AsyncMock(return_value=[])

    async def refresh_history(history: QueryHistory) -> None:
        history.id = QUERY_ID

    mock_db.refresh = AsyncMock(side_effect=refresh_history)

    result = await service.ask("hello?", user_id=USER_ID)

    assert result.user_id == USER_ID
    mock_db.scalar.assert_not_awaited()


@pytest.mark.asyncio
async def test_ask_raises_when_no_oauth_connection(
    service: RagService,
    mock_db: AsyncMock,
) -> None:
    mock_db.scalar = AsyncMock(return_value=None)

    with pytest.raises(ValueError, match="No Google Drive connection"):
        await service.ask("What files do I have?")


@pytest.mark.asyncio
async def test_ask_passes_max_context_chars_to_chat_service(
    service: RagService,
    mock_db: AsyncMock,
    mock_chat: AsyncMock,
) -> None:
    mock_db.get = AsyncMock(return_value=USER)
    mock_db.scalar = AsyncMock(return_value=TOKEN_ROW)

    async def refresh_history(history: QueryHistory) -> None:
        history.id = QUERY_ID

    mock_db.refresh = AsyncMock(side_effect=refresh_history)

    await service.ask("What is tensile strength?")

    call_kwargs = mock_chat.generate_grounded_answer.await_args.kwargs
    assert call_kwargs["max_context_chars"] == 12000


@pytest.mark.asyncio
async def test_ask_uses_filename_when_chunk_text_is_blank(
    service: RagService,
    mock_db: AsyncMock,
    mock_retriever: AsyncMock,
    mock_chat: AsyncMock,
) -> None:
    blank_chunk = RetrievedChunk(
        chunk_id=CHUNK_ID,
        document_id=DOCUMENT_ID,
        drive_file_id=DRIVE_FILE_ID,
        filename="notes.txt",
        mime_type="text/plain",
        modified_at=datetime.now(UTC),
        chunk_index=0,
        text="   ",
        score=0.91,
    )
    mock_db.get = AsyncMock(return_value=USER)
    mock_db.scalar = AsyncMock(return_value=TOKEN_ROW)
    mock_retriever.retrieve = AsyncMock(return_value=[blank_chunk])
    mock_chat.generate_grounded_answer = AsyncMock(return_value="See [1].")

    async def refresh_history(history: QueryHistory) -> None:
        history.id = QUERY_ID

    mock_db.refresh = AsyncMock(side_effect=refresh_history)

    result = await service.ask("What is in notes.txt?")

    assert len(result.citations) == 1
    assert result.citations[0].snippet == "notes.txt"


def test_service_uses_hybrid_retriever_when_enabled(mock_db: AsyncMock) -> None:
    service = RagService(
        db=mock_db,
        settings=Settings(hybrid_retrieval_enabled=True),
        chat_service=AsyncMock(),
    )
    assert isinstance(service.retriever, HybridRetriever)


def test_service_uses_vector_retriever_when_hybrid_disabled(mock_db: AsyncMock) -> None:
    service = RagService(
        db=mock_db,
        settings=Settings(hybrid_retrieval_enabled=False),
        chat_service=AsyncMock(),
    )
    assert isinstance(service.retriever, VectorRetriever)


@pytest.mark.asyncio
async def test_ask_uses_evidence_grading_path_when_retriever_supports_it(
    mock_db: AsyncMock,
    mock_chat: AsyncMock,
) -> None:
    graded_retriever = HybridRetriever(
        db=mock_db,
        settings=Settings(hybrid_retrieval_enabled=True),
        vector_retriever=AsyncMock(),
        keyword_retriever=AsyncMock(),
        metadata_retriever=AsyncMock(),
    )
    graded_retriever.retrieve_with_grade = AsyncMock(  # type: ignore[method-assign]
        return_value=MagicMock(chunks=[]),
    )
    service = RagService(
        db=mock_db,
        settings=MagicMock(rag_max_context_chars=12000, hybrid_retrieval_enabled=True),
        retriever=graded_retriever,
        chat_service=mock_chat,
    )
    mock_db.get = AsyncMock(return_value=USER)
    mock_db.scalar = AsyncMock(return_value=TOKEN_ROW)

    async def refresh_history(history: QueryHistory) -> None:
        history.id = QUERY_ID

    mock_db.refresh = AsyncMock(side_effect=refresh_history)

    result = await service.ask("What is tensile strength?")

    assert result.answer == NO_EVIDENCE_ANSWER
    graded_retriever.retrieve_with_grade.assert_awaited_once_with("What is tensile strength?")
    mock_chat.generate_grounded_answer.assert_not_awaited()
