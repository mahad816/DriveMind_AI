"""Bounded per-file summaries and generation contracts, without live API calls."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.drive_graph.nodes import make_generate_answer_node
from app.agents.drive_graph.state import create_initial_state
from app.core.config import Settings
from app.db.models.user import User
from app.demo.manifest import load_manifest
from app.llm.base import ChatError
from app.llm.openai_service import OpenAIChatService
from app.llm.prompts import NO_EVIDENCE_ANSWER, FILE_INFORMATION_UNAVAILABLE
from app.retrieval.collection_summary import CollectionSummaryResult, CollectionSummaryRetriever
from app.retrieval.query_router import QueryRoute, classify_query
from app.retrieval.types import RetrievedChunk
from app.services.rag_service import RagService


@pytest.mark.parametrize(
    "question",
    [
        "tell me summary in one sentence each for the doc we have",
        "summarize each document",
        "give me one sentence for every file",
        "summarize every document",
        "give me one summary per document",
        "what does each document contain",
        "summarize all available files",
    ],
)
def test_collection_summary_intent(question: str) -> None:
    assert classify_query(question) == QueryRoute.COLLECTION_SUMMARY


@pytest.mark.parametrize(
    ("question", "route"),
    [
        ("List all files in this knowledge base.", QueryRoute.FILE_INVENTORY),
        ('Summarize "architecture_notes.txt".', QueryRoute.FILE_TARGET),
        ("Summarize notification decisions.", QueryRoute.GROUNDED_RAG),
        ("Summarize all documents about notifications.", QueryRoute.GROUNDED_RAG),
        ("What does architecture_notes.txt contain?", QueryRoute.GROUNDED_RAG),
    ],
)
def test_existing_routes_stay_distinct(question: str, route: QueryRoute) -> None:
    assert classify_query(question) == route


def chunk(
    filename: str = "notes.txt", text: str = "A support inbox for bicycle shops."
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        drive_file_id=uuid.uuid4(),
        filename=filename,
        mime_type="text/plain",
        modified_at=datetime.now(UTC),
        chunk_index=0,
        text=text,
        score=1,
    )


def response(answer: str) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=answer))])


@pytest.mark.asyncio
@pytest.mark.parametrize("first", ["A summary with no citations.", "A summary [99]."])
async def test_named_file_corrects_missing_or_invalid_markers_once(first: str) -> None:
    client = MagicMock()
    client.chat.completions.create = AsyncMock(
        side_effect=[response(first), response("A summary [1].")]
    )
    service = OpenAIChatService(Settings(demo_mode=False), client=client)
    answer = await service.generate_file_target_answer(
        "Summarize notes.txt", [chunk()], max_context_chars=12000
    )
    assert answer == "A summary [1]."
    assert client.chat.completions.create.await_count == 2
    assert client.chat.completions.create.await_args is not None
    assert (
        "Regenerate your answer"
        in client.chat.completions.create.await_args.kwargs["messages"][1]["content"]
    )


@pytest.mark.asyncio
async def test_named_file_correction_is_bounded_and_does_not_fabricate_sources() -> None:
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=response("A summary without markers."))
    with pytest.raises(ChatError, match="source citations"):
        await OpenAIChatService(
            Settings(demo_mode=False), client=client
        ).generate_file_target_answer("Summarize notes.txt", [chunk()], max_context_chars=12000)
    assert client.chat.completions.create.await_count == 2


@pytest.mark.asyncio
async def test_update_date_and_unavailable_event_date_contract() -> None:
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=response(FILE_INFORMATION_UNAVAILABLE))
    evidence = chunk(text="Updated: 2030-03-06. Retry tests must finish before launch.")
    answer = await OpenAIChatService(
        Settings(demo_mode=False), client=client
    ).generate_file_target_answer("When is launch?", [evidence], max_context_chars=12000)
    assert client.chat.completions.create.await_args is not None
    messages = client.chat.completions.create.await_args.kwargs["messages"]
    assert "2030-03-06" in messages[1]["content"]
    assert "not unrelated events" in messages[0]["content"]
    assert "event date is unavailable" in messages[0]["content"]
    assert "2030-03-06" not in answer
    assert client.chat.completions.create.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("demo", [False, True])
async def test_greeting_prompt_and_abstention_wording(demo: bool) -> None:
    client = MagicMock()
    greeting = (
        "Hello! Explore the sample knowledge base." if demo else "Hello! Explore your Google Drive."
    )
    client.chat.completions.create = AsyncMock(return_value=response(greeting))
    settings = Settings(demo_mode=demo, hybrid_retrieval_enabled=False, agent_graph_enabled=False)
    chat = OpenAIChatService(settings, client=client)
    assert await chat.generate_direct_answer("hello") == greeting
    assert client.chat.completions.create.await_args is not None
    prompt = client.chat.completions.create.await_args.kwargs["messages"][0]["content"]
    assert ("controlled sample" in prompt) is demo
    db = AsyncMock()
    retriever = AsyncMock()
    retriever.retrieve.return_value = []
    rag = RagService(
        db, settings, retriever=retriever, chat_service=chat, persist_query_history=False
    )
    rag._resolve_user = AsyncMock(return_value=User(id=uuid.uuid4()))
    result = await rag.ask("an unavailable technical fact")
    assert ("Google Drive" in result.answer) is not demo
    if not demo:
        assert result.answer == NO_EVIDENCE_ANSWER
    node = make_generate_answer_node(settings=settings, chat_service=chat)
    graph_result = await node(create_initial_state(question="Missing fact", user_id=uuid.uuid4()))
    assert graph_result["answer"] == result.answer


@pytest.mark.asyncio
async def test_collection_covers_small_corpus_and_preserves_source_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files = [
        (e.filename, [chunk(e.filename, load_manifest().read_sample(e.filename))])
        for e in load_manifest().files
    ]
    lookup = AsyncMock(return_value=CollectionSummaryResult(total=7, files=files))
    monkeypatch.setattr(CollectionSummaryRetriever, "search", lookup)
    chat = AsyncMock()
    chat.generate_collection_answer.return_value = "\n".join(
        f"- **{filename}**: A concise supported summary [{index}]."
        for index, (filename, _) in enumerate(files, 1)
    )
    db = AsyncMock()
    rag = RagService(db, Settings(demo_mode=False), chat_service=chat, persist_query_history=False)
    user = User(id=uuid.uuid4())
    rag._resolve_user = AsyncMock(return_value=user)
    result = await rag.ask("summarize each document")
    assert "Covering 7 of 7" in result.answer
    assert len(result.citations) == 7
    for index, (filename, chunks) in enumerate(files, 1):
        assert f"**{filename}**: A concise supported summary [{index}]." in result.answer
        assert result.citations[index - 1].chunk_id == chunks[0].chunk_id
    assert lookup.await_args is not None
    assert lookup.await_args.args == (user.id,)
    assert chat.generate_collection_answer.await_count == 1
    chat.generate_file_target_answer.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_collection_reports_limited_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    files = [(f"file-{i}.txt", [chunk(f"file-{i}.txt")]) for i in range(10)]
    monkeypatch.setattr(
        CollectionSummaryRetriever,
        "search",
        AsyncMock(return_value=CollectionSummaryResult(total=18, files=files)),
    )
    chat = AsyncMock()
    chat.generate_collection_answer.return_value = "A summary [1]."
    rag = RagService(
        AsyncMock(), Settings(demo_mode=False), chat_service=chat, persist_query_history=False
    )
    rag._resolve_user = AsyncMock(return_value=User(id=uuid.uuid4()))
    result = await rag.ask("give me one sentence for every file")
    assert "Covering 10 of 18" in result.answer
    assert "large files may not be covered in full" in result.answer
    assert chat.generate_collection_answer.await_count == 1


@pytest.mark.asyncio
async def test_collection_lookup_scopes_user_and_bounds_database_reads() -> None:
    user_id = uuid.uuid4()
    evidence = chunk()
    file = SimpleNamespace(
        id=evidence.drive_file_id,
        name=evidence.filename,
        mime_type="text/plain",
        modified_at=evidence.modified_at,
    )
    db = AsyncMock()
    db.scalar.return_value = 12
    db.scalars.return_value = MagicMock(all=lambda: [file])
    db.execute.return_value = MagicMock(
        all=lambda: [(evidence.chunk_id, evidence.document_id, 0, evidence.text)]
    )
    result = await CollectionSummaryRetriever(db).search(user_id, max_chars=1200)
    assert result.total == 12 and result.files[0][0] == file.name
    query = db.scalars.await_args.args[0]
    assert user_id in query.compile().params.values()
    assert "drive_files.status" in str(query) and query._limit_clause.value == 10
    content_query = db.execute.await_args.args[0]
    assert content_query._limit_clause.value == 4
    assert "substr" in str(content_query)


@pytest.mark.asyncio
async def test_named_file_valid_markers_need_no_correction() -> None:
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=response("A supported summary [1]."))
    answer = await OpenAIChatService(
        Settings(demo_mode=False), client=client
    ).generate_file_target_answer("Summarize notes.txt", [chunk()], max_context_chars=12000)
    assert answer == "A supported summary [1]."
    client.chat.completions.create.assert_awaited_once()
