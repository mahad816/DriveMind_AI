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
from app.schemas.query import CitationItem
from app.services.rag_service import RagResult, RagService

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
        settings=Settings(
            rag_max_context_chars=12000,
            hybrid_retrieval_enabled=False,
            agent_graph_enabled=False,
        ),
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

    # Use a knowledge question (not chitchat) so we exercise the RAG path.
    result = await service.ask("What is tensile strength?", user_id=USER_ID)

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

    result = await service.ask("What does the blank section mean?")

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
        settings=Settings(
            rag_max_context_chars=12000,
            hybrid_retrieval_enabled=True,
            agent_graph_enabled=False,
        ),
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


@pytest.mark.asyncio
async def test_ask_uses_drive_graph_when_agent_enabled(
    mock_db: AsyncMock,
    mock_retriever: AsyncMock,
    mock_chat: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        agent_graph_enabled=True,
        hybrid_retrieval_enabled=False,
        rag_max_context_chars=12000,
    )
    service = RagService(
        db=mock_db,
        settings=settings,
        retriever=mock_retriever,
        chat_service=mock_chat,
    )
    mock_db.get = AsyncMock(return_value=USER)

    citation = CitationItem(
        chunk_id=CHUNK_ID,
        drive_file_id=DRIVE_FILE_ID,
        filename="notes.txt",
        snippet="graph citation",
        score=0.8,
    )

    fake_graph_result = RagResult(
        query_id=uuid.uuid4(),
        user_id=USER_ID,
        question="What is tensile strength?",
        answer="Graph answer [1].",
        citations=[citation],
        retrieval_count=1,
    )

    async def fake_run_drive_graph(*args: object, **kwargs: object) -> RagResult:
        return fake_graph_result

    monkeypatch.setattr(
        "app.agents.drive_graph.runner.run_drive_graph",
        fake_run_drive_graph,
    )

    async def refresh_history(history: QueryHistory) -> None:
        history.id = QUERY_ID

    mock_db.refresh = AsyncMock(side_effect=refresh_history)

    result = await service.ask("What is tensile strength?", user_id=USER_ID)

    assert result.query_id == QUERY_ID
    assert result.answer == "Graph answer [1]."
    assert result.citations[0].snippet == "graph citation"
    assert result.retrieval_count == 1
    mock_retriever.retrieve.assert_not_awaited()
    mock_chat.generate_grounded_answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_ask_uses_linear_path_when_agent_disabled_even_if_graph_available(
    mock_db: AsyncMock,
    mock_retriever: AsyncMock,
    mock_chat: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Agent flag off should continue using the existing linear retrieval path."""
    settings = Settings(
        agent_graph_enabled=False,
        hybrid_retrieval_enabled=False,
        rag_max_context_chars=12000,
    )
    service = RagService(
        db=mock_db,
        settings=settings,
        retriever=mock_retriever,
        chat_service=mock_chat,
    )
    mock_db.get = AsyncMock(return_value=USER)

    async def fail_if_called(*args: object, **kwargs: object) -> RagResult:
        raise AssertionError(
            "run_drive_graph should not be called when agent_graph_enabled is false"
        )

    monkeypatch.setattr(
        "app.agents.drive_graph.runner.run_drive_graph",
        fail_if_called,
    )

    async def refresh_history(history: QueryHistory) -> None:
        history.id = QUERY_ID

    mock_db.refresh = AsyncMock(side_effect=refresh_history)

    result = await service.ask("What is tensile strength?", user_id=USER_ID)

    assert result.query_id == QUERY_ID
    assert result.answer == "Tensile strength is discussed in [1]."
    mock_retriever.retrieve.assert_awaited_once_with("What is tensile strength?")


# ── Chitchat bypass ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ask_chitchat_bypasses_retrieval_and_has_no_citations(
    mock_db: AsyncMock,
    mock_retriever: AsyncMock,
    mock_chat: AsyncMock,
) -> None:
    """Greeting messages must not trigger retrieval or produce source citations."""
    mock_chat.generate_direct_answer = AsyncMock(
        return_value="Hello! How can I help you today?"
    )
    service = RagService(
        db=mock_db,
        settings=Settings(
            rag_max_context_chars=12000,
            hybrid_retrieval_enabled=False,
            agent_graph_enabled=False,
        ),
        retriever=mock_retriever,
        chat_service=mock_chat,
    )
    mock_db.get = AsyncMock(return_value=USER)
    mock_db.scalar = AsyncMock(return_value=TOKEN_ROW)

    async def refresh_history(history: QueryHistory) -> None:
        history.id = QUERY_ID

    mock_db.refresh = AsyncMock(side_effect=refresh_history)

    result = await service.ask("hi", user_id=USER_ID)

    assert result.answer == "Hello! How can I help you today?"
    assert result.citations == []
    assert result.retrieval_count == 0
    mock_retriever.retrieve.assert_not_awaited()
    mock_chat.generate_grounded_answer.assert_not_awaited()
    mock_chat.generate_direct_answer.assert_awaited_once_with("hi")


@pytest.mark.asyncio
async def test_ask_chitchat_persists_history_with_empty_citations(
    mock_db: AsyncMock,
    mock_retriever: AsyncMock,
    mock_chat: AsyncMock,
) -> None:
    mock_chat.generate_direct_answer = AsyncMock(return_value="Hi! How can I help?")
    service = RagService(
        db=mock_db,
        settings=Settings(
            rag_max_context_chars=12000,
            hybrid_retrieval_enabled=False,
            agent_graph_enabled=False,
        ),
        retriever=mock_retriever,
        chat_service=mock_chat,
    )
    mock_db.get = AsyncMock(return_value=USER)

    async def refresh_history(history: QueryHistory) -> None:
        history.id = QUERY_ID

    mock_db.refresh = AsyncMock(side_effect=refresh_history)

    await service.ask("hello!", user_id=USER_ID)

    added = mock_db.add.call_args.args[0]
    assert isinstance(added, QueryHistory)
    assert added.citations_json == []


# ── File inventory path ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ask_file_inventory_bypasses_chunk_retrieval(
    mock_db: AsyncMock,
    mock_retriever: AsyncMock,
    mock_chat: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resume/CV inventory questions must not use chunk retrieval."""
    from unittest.mock import AsyncMock as AM
    from app.retrieval.file_inventory import InventoryResult

    mock_chat.generate_inventory_answer = AM(
        return_value="You have 3 resume files. The latest is Resume_2024.pdf (2024-03-12). It does not mention GPA."
    )

    fake_result = InventoryResult(
        search_terms=["resume", "cv"],
        total_count=3,
        files=[],
        latest_file=None,
    )

    async def fake_search(self: object, question: str) -> InventoryResult:
        return fake_result

    monkeypatch.setattr(
        "app.retrieval.file_inventory.FileInventoryRetriever.search",
        fake_search,
    )

    service = RagService(
        db=mock_db,
        settings=Settings(
            rag_max_context_chars=12000,
            hybrid_retrieval_enabled=False,
            agent_graph_enabled=False,
        ),
        retriever=mock_retriever,
        chat_service=mock_chat,
    )
    mock_db.get = AsyncMock(return_value=USER)

    async def refresh_history(history: QueryHistory) -> None:
        history.id = QUERY_ID

    mock_db.refresh = AsyncMock(side_effect=refresh_history)

    result = await service.ask(
        "can you check all files which have resume name or CV and tell how many",
        user_id=USER_ID,
    )

    assert "3 resume files" in result.answer or "resume" in result.answer.lower()
    assert result.citations == []
    mock_retriever.retrieve.assert_not_awaited()
    mock_chat.generate_grounded_answer.assert_not_awaited()
    mock_chat.generate_inventory_answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_ask_file_inventory_retrieval_count_reflects_file_count(
    mock_db: AsyncMock,
    mock_retriever: AsyncMock,
    mock_chat: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.retrieval.file_inventory import InventoryResult

    mock_chat.generate_inventory_answer = AsyncMock(return_value="Found 2 files.")

    fake_result = InventoryResult(
        search_terms=["resume"],
        total_count=2,
        files=[],
        latest_file=None,
    )

    async def fake_search(self: object, question: str) -> InventoryResult:
        return fake_result

    monkeypatch.setattr(
        "app.retrieval.file_inventory.FileInventoryRetriever.search",
        fake_search,
    )

    service = RagService(
        db=mock_db,
        settings=Settings(hybrid_retrieval_enabled=False, agent_graph_enabled=False),
        retriever=mock_retriever,
        chat_service=mock_chat,
    )
    mock_db.get = AsyncMock(return_value=USER)

    async def refresh_history(history: QueryHistory) -> None:
        history.id = QUERY_ID

    mock_db.refresh = AsyncMock(side_effect=refresh_history)

    result = await service.ask("find all my resumes", user_id=USER_ID)

    assert result.retrieval_count == 2


# ── Citation hygiene ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_grounded_rag_citations_filtered_to_referenced_only(
    mock_db: AsyncMock,
    mock_chat: AsyncMock,
) -> None:
    """Citations not referenced by [N] in the answer must not be returned."""
    # Provide two chunks but the LLM only references [1].
    chunk_a = _retrieved_chunk()
    chunk_b = RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        drive_file_id=uuid.uuid4(),
        filename="other.pdf",
        mime_type="application/pdf",
        modified_at=chunk_a.modified_at,
        chunk_index=0,
        text="Unrelated content.",
        score=0.5,
    )
    mock_retriever = AsyncMock()
    mock_retriever.retrieve = AsyncMock(return_value=[chunk_a, chunk_b])
    mock_chat.generate_grounded_answer = AsyncMock(
        return_value="Tensile strength is discussed in [1]."
    )

    service = RagService(
        db=mock_db,
        settings=Settings(hybrid_retrieval_enabled=False, agent_graph_enabled=False),
        retriever=mock_retriever,
        chat_service=mock_chat,
    )
    mock_db.get = AsyncMock(return_value=USER)

    async def refresh_history(history: QueryHistory) -> None:
        history.id = QUERY_ID

    mock_db.refresh = AsyncMock(side_effect=refresh_history)

    result = await service.ask("What is tensile strength?", user_id=USER_ID)

    # Only chunk_a ([1]) should be cited — chunk_b is not referenced
    assert len(result.citations) == 1
    assert result.citations[0].filename == "notes.txt"


@pytest.mark.asyncio
async def test_grounded_rag_keeps_citations_when_llm_omits_brackets(
    mock_db: AsyncMock,
    mock_chat: AsyncMock,
) -> None:
    """If the LLM omits [N] refs, still return grounded sources for the UI."""
    mock_retriever = AsyncMock()
    mock_retriever.retrieve = AsyncMock(return_value=[_retrieved_chunk()])
    mock_chat.generate_grounded_answer = AsyncMock(
        return_value="Tensile strength describes the maximum stress a material can sustain."
    )

    service = RagService(
        db=mock_db,
        settings=Settings(hybrid_retrieval_enabled=False, agent_graph_enabled=False),
        retriever=mock_retriever,
        chat_service=mock_chat,
    )
    mock_db.get = AsyncMock(return_value=USER)

    async def refresh_history(history: QueryHistory) -> None:
        history.id = QUERY_ID

    mock_db.refresh = AsyncMock(side_effect=refresh_history)

    result = await service.ask("What is tensile strength?", user_id=USER_ID)

    assert len(result.citations) == 1
    assert result.citations[0].filename == "notes.txt"


# ── Phase A: routing applies before agent_graph_enabled ───────────────────────

@pytest.mark.asyncio
async def test_ask_chitchat_bypasses_graph_when_agent_enabled(
    mock_db: AsyncMock,
    mock_retriever: AsyncMock,
    mock_chat: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With agent_graph_enabled=True, chitchat must NOT reach run_drive_graph."""
    mock_chat.generate_direct_answer = AsyncMock(return_value="Hello! How can I help?")

    graph_call_count = 0

    async def fail_if_graph_called(*args: object, **kwargs: object) -> object:
        nonlocal graph_call_count
        graph_call_count += 1
        raise AssertionError("run_drive_graph must not be called for chitchat")

    monkeypatch.setattr(
        "app.agents.drive_graph.runner.run_drive_graph",
        fail_if_graph_called,
    )

    service = RagService(
        db=mock_db,
        settings=Settings(
            agent_graph_enabled=True,
            hybrid_retrieval_enabled=False,
            rag_max_context_chars=12000,
        ),
        retriever=mock_retriever,
        chat_service=mock_chat,
    )
    mock_db.get = AsyncMock(return_value=USER)

    async def refresh_history(history: QueryHistory) -> None:
        history.id = QUERY_ID

    mock_db.refresh = AsyncMock(side_effect=refresh_history)

    result = await service.ask("hi", user_id=USER_ID)

    assert graph_call_count == 0, "run_drive_graph was called for chitchat"
    assert result.citations == []
    assert result.retrieval_count == 0
    mock_chat.generate_direct_answer.assert_awaited_once_with("hi")
    mock_retriever.retrieve.assert_not_awaited()


@pytest.mark.asyncio
async def test_ask_file_inventory_bypasses_graph_when_agent_enabled(
    mock_db: AsyncMock,
    mock_retriever: AsyncMock,
    mock_chat: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With agent_graph_enabled=True, file inventory questions must NOT reach run_drive_graph."""
    from app.retrieval.file_inventory import InventoryResult

    mock_chat.generate_inventory_answer = AsyncMock(
        return_value="Found 2 resume files. Latest: Resume_2024.pdf."
    )

    fake_inv_result = InventoryResult(
        search_terms=["resume"],
        total_count=2,
        files=[],
        latest_file=None,
    )

    async def fake_search(self: object, question: str) -> InventoryResult:
        return fake_inv_result

    monkeypatch.setattr(
        "app.retrieval.file_inventory.FileInventoryRetriever.search",
        fake_search,
    )

    graph_call_count = 0

    async def fail_if_graph_called(*args: object, **kwargs: object) -> object:
        nonlocal graph_call_count
        graph_call_count += 1
        raise AssertionError("run_drive_graph must not be called for file inventory")

    monkeypatch.setattr(
        "app.agents.drive_graph.runner.run_drive_graph",
        fail_if_graph_called,
    )

    service = RagService(
        db=mock_db,
        settings=Settings(
            agent_graph_enabled=True,
            hybrid_retrieval_enabled=False,
            rag_max_context_chars=12000,
        ),
        retriever=mock_retriever,
        chat_service=mock_chat,
    )
    mock_db.get = AsyncMock(return_value=USER)

    async def refresh_history(history: QueryHistory) -> None:
        history.id = QUERY_ID

    mock_db.refresh = AsyncMock(side_effect=refresh_history)

    result = await service.ask("find all my resume files", user_id=USER_ID)

    assert graph_call_count == 0, "run_drive_graph was called for file inventory"
    assert result.citations == []
    mock_chat.generate_inventory_answer.assert_awaited_once()
    mock_retriever.retrieve.assert_not_awaited()
