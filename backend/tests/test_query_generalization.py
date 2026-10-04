"""General intent, discourse references, calendar matching, and grounding contracts."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest
from app.core.config import Settings
from app.db.models.user import User
from app.llm.openai_service import OpenAIChatService
from app.llm.prompts import GROUNDING_RULES
from app.retrieval.dates import date_patterns
from app.retrieval.keyword import KeywordRetriever
from app.retrieval.query_router import QueryRoute, classify_query
from app.services.conversation_history import bounded_rewrite_history
from app.services.rag_service import RagService


@pytest.mark.parametrize(
    "q",
    [
        "what all docs do we have and what are they for",
        "give me a quick rundown of every document",
        "what files are here and what does each one cover?",
        "Explain the purpose of all available documents",
        "Walk through every file and describe its contents",
        "tell me what each file is about in one line",
    ],
)
def test_collection_semantics(q: str) -> None:
    assert classify_query(q) == QueryRoute.COLLECTION_SUMMARY


@pytest.mark.parametrize(
    ("q", "route"),
    [
        ("List all files", QueryRoute.FILE_INVENTORY),
        ('Summarize "design.md"', QueryRoute.FILE_TARGET),
        ("Why was the migration cancelled?", QueryRoute.GROUNDED_RAG),
        ("Summarize all documents about backups", QueryRoute.GROUNDED_RAG),
    ],
)
def test_other_routes(q: str, route: QueryRoute) -> None:
    assert classify_query(q) == route


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("followup", "resolved"),
    [
        ("Who owns that?", "Who owns the database migration?"),
        ("What happens after it?", "What happens after the onboarding workshop?"),
        ("When was that decided?", "When was the backup retention policy decided?"),
        ("what has to be completed first?", "What are the prerequisites for the release review?"),
        ("Who handles those tasks?", "Who handles the restoration exercise and training?"),
    ],
)
async def test_followup_retrieval(followup: str, resolved: str) -> None:
    chat = AsyncMock()
    chat.rewrite_followup.return_value = resolved
    retriever = AsyncMock()
    retriever.retrieve.return_value = []
    rag = RagService(
        AsyncMock(),
        Settings(demo_mode=False, hybrid_retrieval_enabled=False, agent_graph_enabled=False),
        chat_service=chat,
        retriever=retriever,
        persist_query_history=False,
    )
    rag._resolve_user = AsyncMock(return_value=User(id=uuid.uuid4()))
    history = [
        {"role": "user", "text": "Tell me about the recent project milestone."},
        {"role": "assistant", "text": "The milestone is recorded in project notes."},
    ]
    result = await rag.ask(followup, conversation_id="test", history=history)
    chat.rewrite_followup.assert_awaited_once_with(followup, history)
    retriever.retrieve.assert_awaited_once_with(resolved)
    assert result.question == followup


@pytest.mark.asyncio
async def test_file_reference_rewrites_before_named_file_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.retrieval.file_target import FileTargetRetriever, FileTargetResult

    resolved = 'Tell me about "handover.txt"'
    lookup = AsyncMock(return_value=FileTargetResult(files=[], chunks=[], targets=["handover.txt"]))
    monkeypatch.setattr(FileTargetRetriever, "search", lookup)
    chat = AsyncMock()
    chat.rewrite_followup.return_value = resolved
    retriever = AsyncMock()
    rag = RagService(
        AsyncMock(),
        Settings(demo_mode=False),
        chat_service=chat,
        retriever=retriever,
        persist_query_history=False,
    )
    user = User(id=uuid.uuid4())
    rag._resolve_user = AsyncMock(return_value=user)
    result = await rag.ask(
        "What about that file?",
        conversation_id="test",
        history=[{"role": "assistant", "text": 'The file is "handover.txt".'}],
    )
    lookup.assert_awaited_once_with(resolved, user_id=user.id)
    retriever.retrieve.assert_not_called()
    assert result.question == "What about that file?"


@pytest.mark.asyncio
async def test_standalone_no_rewrite() -> None:
    chat = AsyncMock()
    retriever = AsyncMock()
    retriever.retrieve.return_value = []
    rag = RagService(
        AsyncMock(),
        Settings(demo_mode=False, hybrid_retrieval_enabled=False, agent_graph_enabled=False),
        chat_service=chat,
        retriever=retriever,
        persist_query_history=False,
    )
    rag._resolve_user = AsyncMock(return_value=User(id=uuid.uuid4()))
    await rag.ask(
        "What is database replication?",
        conversation_id="test",
        history=[{"role": "user", "text": "When is training?"}],
    )
    chat.rewrite_followup.assert_not_called()
    retriever.retrieve.assert_awaited_once_with("What is database replication?")


@pytest.mark.asyncio
async def test_grammatical_that_does_not_require_history_rewrite() -> None:
    question = "Does the policy state that backups are encrypted?"
    chat = AsyncMock()
    chat.rewrite_followup.return_value = question
    retriever = AsyncMock()
    retriever.retrieve.return_value = []
    rag = RagService(
        AsyncMock(),
        Settings(demo_mode=False, hybrid_retrieval_enabled=False, agent_graph_enabled=False),
        chat_service=chat,
        retriever=retriever,
        persist_query_history=False,
    )
    rag._resolve_user = AsyncMock(return_value=User(id=uuid.uuid4()))
    await rag.ask(
        question,
        conversation_id="test",
        history=[{"role": "assistant", "text": "The previous topic was the onboarding workshop."}],
    )
    retriever.retrieve.assert_awaited_once_with(question)


def test_rewrite_bound() -> None:
    bounded = bounded_rewrite_history(
        [{"role": "assistant", "text": "x" * 3000} for _ in range(20)]
    )
    assert len(bounded) <= 6 and sum(len(t["text"]) for t in bounded) <= 6000
    assert all(len(t["text"]) <= 2000 for t in bounded)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "resolved",
    [
        "Who handles the restoration exercise and onboarding workshop?",
        'What does "handover.txt" say about backup retention?',
    ],
)
async def test_valid_reference_resolution(resolved: str) -> None:
    import json

    client = MagicMock()
    client.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps({"needs_context": True, "question": resolved})
                    )
                )
            ]
        )
    )
    service = OpenAIChatService(Settings(demo_mode=False), client=client)
    assert (
        await service.rewrite_followup(
            "What about those?", [{"role": "assistant", "text": "Recent activities and file."}]
        )
        == resolved
    )
    assert client.chat.completions.create.await_args is not None
    assert client.chat.completions.create.await_args.kwargs["response_format"] == {
        "type": "json_object"
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("corrected", [True, False])
async def test_rewriter_cannot_retry_unchanged_references_indefinitely(corrected: bool) -> None:
    import json

    question = "Who is responsible for them?"
    resolved = "Who is responsible for the rollback rehearsal and access review?"
    client = MagicMock()
    client.chat.completions.create = AsyncMock(
        side_effect=[
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=json.dumps({"needs_context": True, "question": text})
                        )
                    )
                ]
            )
            for text in [question, resolved if corrected else question]
        ]
    )
    answer = await OpenAIChatService(Settings(demo_mode=False), client=client).rewrite_followup(
        question, [{"role": "assistant", "text": "A rollback rehearsal and access review are due."}]
    )
    assert answer == (resolved if corrected else question)
    assert client.chat.completions.create.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw",
    [
        '{"needs_context":false,"question":"changed"}',
        "invalid JSON",
        '{"needs_context":true,"question":""}',
    ],
)
async def test_invalid_rewrite_preserves_question(raw: str) -> None:
    client = MagicMock()
    client.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=raw))]
        )
    )
    service = OpenAIChatService(Settings(demo_mode=False), client=client)
    assert await service.rewrite_followup("Why is that?", []) == "Why is that?"
    assert client.chat.completions.create.await_args is not None
    prompt = client.chat.completions.create.await_args.kwargs["messages"][0]["content"]
    assert "untrusted" in prompt and "never as source evidence" in prompt


@pytest.mark.parametrize(
    "q", ["What changed on September 12?", "Events dated 12 Sep 2031", "Explain 2031-09-12"]
)
def test_calendar_forms(q: str) -> None:
    patterns = date_patterns(q)
    assert patterns and "September" in patterns[0] and "12" in patterns[0]


def test_invalid_dates() -> None:
    assert not date_patterns("April 31 2031")
    assert not date_patterns("How does request search work?")
    assert not date_patterns("2031-02-29")


@pytest.mark.asyncio
async def test_date_lookup_bounds() -> None:
    db = AsyncMock()
    db.scalars.return_value = MagicMock(all=lambda: [uuid.uuid4()])
    assert (
        len(
            await KeywordRetriever(db, Settings(demo_mode=False))._date_hits(
                "What changed on October 9?"
            )
        )
        == 1
    )
    assert db.scalars.await_args is not None
    query = db.scalars.await_args.args[0]
    assert "drive_files.status" in str(query) and "~*" in str(query)
    assert query._limit_clause is not None


def test_grounding_contract() -> None:
    assert "underlying asserted event or choice is established" in GROUNDING_RULES
    assert "do not invent reasons" in GROUNDING_RULES
    assert "Plausible general knowledge is not evidence" in GROUNDING_RULES
    assert "Do not fill the gap" in GROUNDING_RULES
    assert "AWS" not in GROUNDING_RULES and "HarborDesk" not in GROUNDING_RULES


@pytest.mark.asyncio
async def test_short_literal_fact_can_still_be_answered() -> None:
    from app.retrieval.types import RetrievedChunk
    from datetime import UTC, datetime

    client = MagicMock()
    client.chat.completions.create = AsyncMock(
        side_effect=[
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])
            for text in ["Nora owns the review [1]."]
        ]
    )
    evidence = RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        drive_file_id=uuid.uuid4(),
        filename="review.txt",
        mime_type="text/plain",
        modified_at=datetime.now(UTC),
        chunk_index=0,
        text="Review owner: Nora.",
        score=1,
    )
    answer = await OpenAIChatService(
        Settings(demo_mode=False), client=client
    ).generate_grounded_answer("Who owns the review?", [evidence], max_context_chars=12000)
    assert "Nora" in answer and "[1]" in answer
    assert client.chat.completions.create.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("history", "question", "resolved"),
    [
        (
            [
                {"role": "user", "text": "What must be done before the workshop?"},
                {"role": "assistant", "text": "Book the room and conduct an access review."},
                {"role": "user", "text": "Who is responsible for those activities?"},
                {
                    "role": "assistant",
                    "text": "Nora books the room; Eli conducts the access review.",
                },
            ],
            "Which of them is due last?",
            "Among booking the room and conducting the access review before the workshop, which is due last?",
        ),
        (
            [
                {"role": "user", "text": "Describe the two museum decisions."},
                {"role": "assistant", "text": "The ticketing decision and gallery-hours decision."},
                {"role": "user", "text": "Who owns these decisions?"},
                {"role": "assistant", "text": "Sam owns ticketing; Lee owns gallery hours."},
            ],
            "Which one happened first?",
            "Which happened first: the museum ticketing decision or gallery-hours decision?",
        ),
    ],
)
async def test_set_reference_survives_an_intervening_owner_turn(
    history: list[dict[str, str]], question: str, resolved: str
) -> None:
    import json

    service = OpenAIChatService(Settings(demo_mode=False))
    complete = AsyncMock(return_value=json.dumps({"needs_context": True, "question": resolved}))
    service._complete = complete
    assert await service.rewrite_followup(question, history) == resolved
    assert complete.await_args is not None
    prompt, message = complete.await_args.args
    assert "SETS" in prompt and "all" in prompt and "without answering" in prompt
    assert json.loads(message)["recent_conversation"] == history
    assert len(resolved) < 1600


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        "Summarize every file and explain their relationships.",
        "Give an overview of each document and identify which discuss staffing.",
    ],
)
async def test_collection_preserves_all_requested_operations(
    question: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime
    from app.retrieval.collection_summary import CollectionSummaryRetriever, CollectionSummaryResult
    from app.retrieval.types import RetrievedChunk

    chunks = [
        RetrievedChunk(
            chunk_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            drive_file_id=uuid.uuid4(),
            filename=name,
            mime_type="text/plain",
            modified_at=datetime.now(UTC),
            chunk_index=0,
            text=text,
            score=1,
        )
        for name, text in [
            ("plan.txt", "A workshop requires trained staff."),
            ("staffing.txt", "The workshop staffing plan assigns two trainers."),
        ]
    ]
    monkeypatch.setattr(
        CollectionSummaryRetriever,
        "search",
        AsyncMock(
            return_value=CollectionSummaryResult(total=2, files=[(c.filename, [c]) for c in chunks])
        ),
    )
    chat = AsyncMock()
    chat.generate_collection_answer.return_value = (
        "plan.txt describes the workshop [1]. staffing.txt supports its training needs [2]."
    )
    rag = RagService(
        AsyncMock(), Settings(demo_mode=False), chat_service=chat, persist_query_history=False
    )
    rag._resolve_user = AsyncMock(return_value=User(id=uuid.uuid4()))
    result = await rag.ask(question)
    chat.generate_collection_answer.assert_awaited_once()
    args = chat.generate_collection_answer.await_args.args
    assert args[0] == question
    assert {c.filename for c in args[1]} == {"plan.txt", "staffing.txt"}
    assert len(result.citations) == 2 and "training needs" in result.answer


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source",
    [
        "No replacement date is currently approved.",
        "The inspection may be delayed.",
        "The workshop is planned for Thursday.",
    ],
)
async def test_generation_receives_unchanged_modality_and_strength_contract(source: str) -> None:
    from datetime import UTC, datetime
    from app.retrieval.types import RetrievedChunk
    from app.llm.prompts import (
        COLLECTION_SYSTEM_PROMPT,
        FILE_TARGET_SYSTEM_PROMPT,
        RAG_SYSTEM_PROMPT,
    )

    for prompt in [COLLECTION_SYSTEM_PROMPT, FILE_TARGET_SYSTEM_PROMPT, RAG_SYSTEM_PROMPT]:
        assert "Preserve evidential strength and time scope" in prompt
        assert "A planned action is not a completed action" in prompt
    service = OpenAIChatService(Settings(demo_mode=False))
    complete = AsyncMock(return_value=source + " [1]")
    service._complete = complete
    evidence = RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        drive_file_id=uuid.uuid4(),
        filename="schedule.txt",
        mime_type="text/plain",
        modified_at=datetime.now(UTC),
        chunk_index=0,
        text=source,
        score=1,
    )
    answer = await service.generate_file_target_answer(
        "Summarize the schedule.", [evidence], max_context_chars=12000
    )
    assert complete.await_args is not None
    assert source in complete.await_args.args[1] and source in answer


@pytest.mark.asyncio
@pytest.mark.parametrize("corrected", [True, False])
async def test_grounded_citation_correction_remains_bounded(corrected: bool) -> None:
    from datetime import UTC, datetime
    from app.retrieval.types import RetrievedChunk
    from app.llm.base import ChatError

    evidence = RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        drive_file_id=uuid.uuid4(),
        filename="record.txt",
        mime_type="text/plain",
        modified_at=datetime.now(UTC),
        chunk_index=0,
        text="Nora owns the review.",
        score=1,
    )
    service = OpenAIChatService(Settings(demo_mode=False))
    complete = AsyncMock(
        side_effect=[
            "Nora owns the review.",
            "Nora owns the review [1]." if corrected else "Nora owns the review.",
        ]
    )
    service._complete = complete
    if corrected:
        answer = await service.generate_grounded_answer(
            "Who owns the review?", [evidence], max_context_chars=12000
        )
        assert "[1]" in answer
    else:
        with pytest.raises(ChatError, match="source citations"):
            await service.generate_grounded_answer(
                "Who owns the review?", [evidence], max_context_chars=12000
            )
    assert complete.await_count == 2


@pytest.mark.parametrize(
    "question",
    [
        "Out of the items we discussed, which comes last on the schedule?",
        "Which of the previously mentioned decisions affects staffing?",
    ],
)
def test_discourse_set_references_are_candidates_for_semantic_rewriting(question: str) -> None:
    from app.services.conversation_history import needs_followup_context

    assert needs_followup_context(question)


@pytest.mark.asyncio
async def test_open_assignment_request_is_not_negated_as_an_asserted_event() -> None:
    from datetime import UTC, datetime
    from app.retrieval.types import RetrievedChunk

    source = "Nora owns the access review."
    evidence = RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        drive_file_id=uuid.uuid4(),
        filename="record.txt",
        mime_type="text/plain",
        modified_at=datetime.now(UTC),
        chunk_index=0,
        text=source,
        score=1,
    )
    service = OpenAIChatService(Settings(demo_mode=False))
    complete = AsyncMock(return_value="Nora owns the access review [1].")
    service._complete = complete
    result = await service.generate_grounded_answer(
        "Who owns the access review?", [evidence], max_context_chars=12000
    )
    assert "Nora" in result and "do not establish" not in result
    assert complete.await_args is not None
    assert "Who owns the access review?" in complete.await_args.args[1]


@pytest.mark.parametrize(
    "question",
    [
        "Who is responsible for the restoration exercise?",
        "When is the review scheduled?",
        "What database is used?",
        "Which venue was selected?",
        "What tasks are listed?",
        "What does this document say?",
        "What happened on September 12?",
        "Order the access review and training by date; which is latest?",
    ],
)
@pytest.mark.asyncio
async def test_grounded_questions_use_generation_without_a_judge(question: str) -> None:
    from app.llm.prompts import INFORMATION_UNAVAILABLE
    from datetime import UTC, datetime
    from app.retrieval.types import RetrievedChunk

    chunk = RetrievedChunk(
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        "review.txt",
        "text/plain",
        datetime.now(UTC),
        0,
        "Nora owns the review.",
        1,
    )
    service = OpenAIChatService(Settings(demo_mode=False))
    complete = AsyncMock(return_value=INFORMATION_UNAVAILABLE)
    service._complete = complete
    assert (
        await service.generate_grounded_answer(question, [chunk], max_context_chars=12000)
        == INFORMATION_UNAVAILABLE
    )
    complete.assert_awaited_once()


def test_date_ordering_uses_full_calendar_dates_not_source_order() -> None:
    from app.retrieval.dates import ordered_date_context

    texts = [
        "Updated: 2031-12-30.\nJanuary 2, 2032: Sol runs staff training.\nDecember 20, 2031: Nora reviews the checklist.\n2031-12-18: Rui runs restoration testing."
    ]
    context = ordered_date_context("Which task has the latest scheduled date?", texts)
    assert context.index("2031-12-18") < context.index("2031-12-20") < context.index("2032-01-02")
    assert "2031-12-30" not in context
    assert "Sol runs staff training" in context and "[1]" in context
    assert "Filter to ALL members" in context
    assert "last/first matching row" in context


def test_date_ordering_omits_ambiguous_invalid_or_missing_year_facts() -> None:
    from app.retrieval.dates import ordered_date_context

    context = ordered_date_context(
        "Order these tasks by deadline.",
        [
            "April 31, 2031: Invalid date.\nMarch 12: Year is unknown.\nMarch 1, 2031: Preparation for March 15, 2031.\n12 Sep 2031: Accessibility review."
        ],
    )
    assert "Accessibility review" in context and "2031-09-12" in context
    assert (
        "Invalid" not in context
        and "Year is unknown" not in context
        and "Preparation" not in context
    )
    assert ordered_date_context("Who owns the review?", ["September 12, 2031: Review."]) == ""


def test_ordering_context_keeps_original_citation_indices_and_prompt_bound() -> None:
    from datetime import UTC, datetime
    from app.retrieval.types import RetrievedChunk
    from app.llm.prompts import build_grounded_user_message

    chunks = [
        RetrievedChunk(
            uuid.uuid4(),
            uuid.uuid4(),
            uuid.uuid4(),
            f"file-{i}.txt",
            "text/plain",
            datetime.now(UTC),
            0,
            text,
            1,
        )
        for i, text in enumerate(
            ["December 9, 2031: Room inspection.", "January 6, 2031: Staffing review."]
        )
    ]
    question = "Which task has the latest deadline?"
    message = build_grounded_user_message(question, chunks, max_context_chars=4000)
    assert "Staffing review. [2]" in message and "Room inspection. [1]" in message
    assert len(message) <= 4000
    assert "Dated source facts" in message
    constrained = build_grounded_user_message(question, chunks, max_context_chars=300)
    assert len(constrained) <= 300 and "Dated source facts" not in constrained


def test_ordering_fact_limit_is_bounded_without_implying_complete_coverage() -> None:
    from app.retrieval.dates import ordered_date_context

    lines = "\n".join(f"January {day}, 2031: Task number {day}." for day in range(1, 26))
    assert ordered_date_context("Which task has the latest deadline?", [lines]) == ""
