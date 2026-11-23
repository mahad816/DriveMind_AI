"""M0-SEC ticket 04: characterize how many paid provider calls one question can make.

Counts are taken with fakes only: no network, no database, no key, no paid API. Each fake
stands for exactly one provider request (one chat completion, one embedding request), so
the assertions state the numbers that ticket 04's Findings table relies on. If a path starts
making more or fewer calls, these tests fail and the table must be revisited before the
quota design (tickets 05 and 06) is trusted.

Not counted here, because the fakes cannot show it: HTTP-level retries inside the OpenAI SDK
(default 2 on non-streaming calls); see the ticket's Findings.
"""

import json
from collections.abc import Sequence
import uuid
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.drive_graph.runner import run_drive_graph
from app.agents.drive_graph.types import RetrieverName
from app.retrieval.base import Retriever
from app.agents.tool_rag.agent_models import AgentStepResult, ToolCallRequest
from app.core.config import Settings
from app.embeddings.vector_store import ScoredChunkHit
from app.llm.base import ChatCitationValidationError, ChatError
from app.llm.openai_service import OpenAIChatService
from app.llm.prompts import NO_EVIDENCE_ANSWER
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.vector import VectorRetriever
from app.services.rag_service import RagService
from app.services.tool_agent_service import ToolAgentAdapter
from tests.agents.tool_rag.test_agent_loop import (
    InventoryDB,
    ScriptChat,
    assert_consumed,
    call,
    chunk,
    file,
)
from tests.agents.tool_rag.test_claim_check import make_settings
from tests.agents.tool_rag.test_grounding_policy import SEARCH
from tests.agents.tool_rag.test_tool_execution import USER
from tests.services.test_rag_service import _retrieved_chunk
from tests.retrieval.test_vector_retriever import CHUNK_ID, USER_ID, _chunk

CITED = "Approval is required. [source_1]"
QUESTION = "What is the refund policy?"


# --------------------------------------------------------------------------------------
# Tool agent (hosted path): intent gate + agent steps + retrievals + claim check
# --------------------------------------------------------------------------------------


class Counters:
    """Counts of paid-call stand-ins for one tool-agent question."""

    def __init__(self) -> None:
        self.intent = AsyncMock(return_value=json.dumps({"intent": "document_question"}))
        self.claim = AsyncMock(return_value=json.dumps({"unsupported": []}))
        self.retriever = AsyncMock()
        self.retriever.retrieve.return_value = [chunk()]


def adapter(
    counters: Counters, steps: Sequence[AgentStepResult | Exception], *, empty_corpus: bool = False
) -> tuple[ToolAgentAdapter, ScriptChat]:
    if empty_corpus:
        counters.retriever.retrieve.return_value = []
    chat = ScriptChat(steps)
    return (
        ToolAgentAdapter(
            cast(AsyncSession, InventoryDB([file()])),
            make_settings(tool_rag_agent_enabled=True),
            chat=chat,
            retriever=counters.retriever,
            intent_complete=counters.intent,
            claim_complete=counters.claim,
        ),
        chat,
    )


async def ask(a: ToolAgentAdapter, question: str = QUESTION):
    return await a.answer(question, user_id=USER, history=[], history_window_complete=True)


async def test_tool_agent_normal_question_with_evidence_counts() -> None:
    counters = Counters()
    a, chat = adapter(counters, [call("search_knowledge", SEARCH), AgentStepResult(text=CITED)])

    await ask(a)

    # 1 intent + 2 agent steps + 1 claim check = 4 chat calls; 1 retrieval = 1 embedding.
    assert counters.intent.await_count == 1
    assert chat.steps == [] and len(chat.received) == 2
    assert counters.claim.await_count == 1
    assert counters.retriever.retrieve.await_count == 1


async def test_tool_agent_conversational_intent_stops_after_the_gate() -> None:
    counters = Counters()
    counters.intent.return_value = json.dumps({"intent": "greeting"})
    a, chat = adapter(counters, [])

    result = await ask(a, "hello")

    assert result.citations == () and result.retrieval_count == 0
    assert counters.intent.await_count == 1  # the only paid call: minimum is 1
    assert chat.received == []
    assert counters.claim.await_count == 0
    assert counters.retriever.retrieve.await_count == 0


async def test_tool_agent_long_question_skips_the_intent_gate() -> None:
    counters = Counters()
    prose = AgentStepResult(text="Hello there, how can I help?")
    a, chat = adapter(
        counters, [prose, prose]
    )  # KI-034: a prose-only first step is asked once more

    await ask(a, "x " * 200)  # longer than the 300-character gate limit

    assert counters.intent.await_count == 0
    assert_consumed(chat)
    assert (
        len(chat.received) == 2
    )  # 1 first step + 1 corrective turn; no retrieval, so no embedding
    counters.retriever.retrieve.assert_not_awaited()


async def test_tool_agent_empty_corpus_still_pays_for_the_search_it_chooses() -> None:
    counters = Counters()
    a, chat = adapter(
        counters,
        [call("search_knowledge", SEARCH), AgentStepResult(text="There is nothing indexed.")],
        empty_corpus=True,
    )

    result = await ask(a)

    assert result.answer == NO_EVIDENCE_ANSWER
    assert counters.retriever.retrieve.await_count == 1  # embeds even though nothing matches
    assert counters.intent.await_count == 1
    assert len(chat.received) == 2
    assert counters.claim.await_count == 0  # no evidence, so no claim check


async def test_tool_agent_provider_failure_partway_keeps_the_calls_already_made() -> None:
    counters = Counters()
    a, chat = adapter(counters, [call("search_knowledge", SEARCH), ChatError("provider down")])

    with pytest.raises(ChatError):
        await ask(a)

    # No in-app retry: intent 1, agent steps 2 (one failed), 1 embedding already spent.
    assert counters.intent.await_count == 1
    assert len(chat.received) == 2
    assert counters.retriever.retrieve.await_count == 1
    assert counters.claim.await_count == 0


async def test_tool_agent_citation_correction_adds_one_step_and_a_second_claim_check() -> None:
    counters = Counters()
    a, chat = adapter(
        counters,
        [
            call("search_knowledge", SEARCH),
            AgentStepResult(text="Approval is required. [source_9]"),  # unknown marker
            AgentStepResult(text=CITED),
        ],
    )

    await ask(a)

    assert len(chat.received) == 3  # search, rejected answer, corrected answer
    assert counters.claim.await_count == 2  # the check runs on each finalization attempt
    assert counters.retriever.retrieve.await_count == 1


async def test_tool_agent_worst_case_is_bounded_by_cycles_and_tool_calls_per_step() -> None:
    counters = Counters()
    steps = [
        AgentStepResult(
            tool_calls=tuple(
                ToolCallRequest(
                    call_id=f"c{cycle}_{n}", tool_name="search_knowledge", arguments=SEARCH
                )
                for n in range(8)  # 8 is the per-step maximum
            )
        )
        for cycle in range(6)
    ]
    a, chat = adapter(counters, steps)

    result = await ask(a)  # the cycle limit is a published answer, not an error

    assert "available tool steps" in result.answer

    # 6 agent steps is the cap; the sixth step's tool calls are never executed, so tools run
    # in 5 cycles x 8 calls = 40 retrievals (40 embeddings), the theoretical maximum.
    assert len(chat.received) == 6
    assert counters.retriever.retrieve.await_count == 40
    assert counters.claim.await_count == 0


async def test_tool_agent_maximum_is_nine_chat_calls() -> None:
    counters = Counters()
    searches = [call("search_knowledge", SEARCH, f"s{n}") for n in range(4)]
    a, chat = adapter(
        counters,
        [
            *searches,
            AgentStepResult(text="Approval is required. [source_9]"),  # rejected marker
            AgentStepResult(text=CITED),  # the one corrective step, sixth and last
        ],
    )

    await ask(a)

    # intent 1 + 6 agent steps + 2 claim checks (one per finalization) = 9 chat requests.
    assert counters.intent.await_count == 1
    assert len(chat.received) == 6
    assert counters.claim.await_count == 2
    assert counters.retriever.retrieve.await_count == 4


# --------------------------------------------------------------------------------------
# Legacy linear path: rewrite + embedding + generation
# --------------------------------------------------------------------------------------


class Legacy:
    def __init__(self, hits: int = 1) -> None:
        self.settings = Settings(
            _env_file=None,  # type: ignore[call-arg]
            hybrid_retrieval_enabled=False,
            agent_graph_enabled=False,
            tool_rag_agent_enabled=False,
        )
        self.embedding = AsyncMock()
        self.embedding.embedding_dimension = 1536
        self.embedding.embed_texts = AsyncMock(return_value=[[0.1] * 1536])
        self.store = AsyncMock()
        self.store.search_similar = AsyncMock(
            return_value=[ScoredChunkHit(chunk_id=CHUNK_ID, score=0.91)] * hits
        )
        self.chat = AsyncMock()
        self.chat.generate_grounded_answer.return_value = "Strength is discussed in [1]."
        self.chat.generate_direct_answer.return_value = "Hello!"
        self.chat.rewrite_followup.return_value = "What is the tensile strength of steel?"
        self.db = AsyncMock()
        self.db.add = MagicMock()
        self.db.get = AsyncMock(
            return_value=SimpleNamespace(id=USER_ID, email="o@example.com", google_id="g")
        )
        self.db.scalars = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[_chunk()])))
        self.rag = RagService(
            self.db,
            self.settings,
            retriever=VectorRetriever(
                self.db,
                self.settings,
                embedding_service=self.embedding,
                vector_store=self.store,
            ),
            chat_service=self.chat,
            persist_query_history=False,
        )


@pytest.fixture
def legacy(monkeypatch: pytest.MonkeyPatch) -> Legacy:
    fake = Legacy()
    monkeypatch.setattr(
        "app.services.rag_service.RagService._resolve_user",
        AsyncMock(return_value=SimpleNamespace(id=USER_ID)),
    )
    return fake


async def test_legacy_linear_normal_question_makes_one_embedding_and_one_chat_call(
    legacy: Legacy,
) -> None:
    result = await legacy.rag.ask("What is tensile strength?", user_id=USER_ID)

    assert result.retrieval_count == 1
    assert legacy.embedding.embed_texts.await_count == 1
    assert legacy.chat.generate_grounded_answer.await_count == 1
    assert legacy.chat.rewrite_followup.await_count == 0


async def test_legacy_linear_empty_corpus_still_pays_for_the_embedding(legacy: Legacy) -> None:
    legacy.store.search_similar.return_value = []

    result = await legacy.rag.ask("What is tensile strength?", user_id=USER_ID)

    assert result.answer == NO_EVIDENCE_ANSWER
    assert legacy.embedding.embed_texts.await_count == 1  # embedded before anything is found
    assert legacy.chat.generate_grounded_answer.await_count == 0


async def test_legacy_chitchat_makes_one_chat_call_and_no_embedding(legacy: Legacy) -> None:
    await legacy.rag.ask("hi", user_id=USER_ID)

    assert legacy.chat.generate_direct_answer.await_count == 1
    assert legacy.embedding.embed_texts.await_count == 0


async def test_legacy_followup_with_history_adds_a_rewrite_call(legacy: Legacy) -> None:
    history = [
        {"role": "user", "text": "Tell me about steel."},
        {"role": "assistant", "text": "Steel is an alloy."},
    ]

    await legacy.rag.ask(
        "How strong is it?", user_id=USER_ID, conversation_id="c1", history=history
    )

    assert legacy.chat.rewrite_followup.await_count == 1
    assert legacy.embedding.embed_texts.await_count == 1
    assert legacy.chat.generate_grounded_answer.await_count == 1


async def test_legacy_hybrid_linear_still_makes_one_embedding(legacy: Legacy) -> None:
    """Production default is hybrid retrieval; the free keyword and metadata arms add no calls."""
    legacy.settings = legacy.settings.model_copy(update={"hybrid_retrieval_enabled": True})
    empty = AsyncMock()
    empty.retrieve = AsyncMock(return_value=[])
    legacy.rag.retriever = HybridRetriever(
        legacy.db,
        legacy.settings,
        vector_retriever=cast(VectorRetriever, legacy.rag.retriever),
        keyword_retriever=empty,
        metadata_retriever=empty,
    )
    legacy.rag.settings = legacy.settings

    await legacy.rag.ask("What is tensile strength?", user_id=USER_ID)

    assert legacy.embedding.embed_texts.await_count == 1
    assert legacy.chat.rewrite_followup.await_count == 0


async def test_legacy_failure_after_embedding_keeps_the_spent_call(legacy: Legacy) -> None:
    legacy.chat.generate_grounded_answer.side_effect = ChatError("provider down")

    with pytest.raises(ChatError):
        await legacy.rag.ask("What is tensile strength?", user_id=USER_ID)

    assert legacy.embedding.embed_texts.await_count == 1
    assert legacy.chat.generate_grounded_answer.await_count == 1  # no in-app retry


# --------------------------------------------------------------------------------------
# OpenAIChatService internals: citation-correction and rewrite retries (one request each)
# --------------------------------------------------------------------------------------


def counting_client(*contents: str) -> MagicMock:
    replies = list(contents)

    async def create(**_: object) -> SimpleNamespace:
        message = SimpleNamespace(content=replies.pop(0))
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=create)
    return client


async def test_cited_answer_regenerates_once_then_fails_after_two_requests() -> None:
    client = counting_client("No markers here.", "Still no markers.")
    service = OpenAIChatService(Settings(_env_file=None), client=client)  # type: ignore[call-arg]

    with pytest.raises(ChatCitationValidationError):
        await service.generate_grounded_answer(
            "What is tensile strength?",
            [_retrieved_chunk()],
            max_context_chars=12000,
        )

    assert client.chat.completions.create.await_count == 2  # maximum per generation


async def test_cited_answer_with_markers_needs_one_request() -> None:
    client = counting_client("Strength is a property [1].")
    service = OpenAIChatService(Settings(_env_file=None), client=client)  # type: ignore[call-arg]

    await service.generate_grounded_answer(
        "What is tensile strength?",
        [_retrieved_chunk()],
        max_context_chars=12000,
    )

    assert client.chat.completions.create.await_count == 1


async def test_followup_rewrite_makes_at_most_two_requests() -> None:
    same = json.dumps({"needs_context": True, "question": "What is it?"})
    client = counting_client(same, same)
    service = OpenAIChatService(Settings(_env_file=None), client=client)  # type: ignore[call-arg]

    out = await service.rewrite_followup("What is it?", [{"role": "user", "text": "steel"}])

    assert out == "What is it?"
    assert client.chat.completions.create.await_count == 2


# --------------------------------------------------------------------------------------
# Legacy LangGraph path: each retrieval round embeds; each rewrite is one chat request
# --------------------------------------------------------------------------------------


async def test_langgraph_empty_corpus_runs_three_embeddings_and_two_rewrite_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rewrite_requests = AsyncMock(
        side_effect=lambda **_: SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps({"rewritten_query": f"q{uuid.uuid4().hex[:6]}"})
                    )
                )
            ]
        )
    )
    fake_openai = MagicMock()
    fake_openai.chat.completions.create = rewrite_requests
    monkeypatch.setattr("app.agents.drive_graph.nodes.AsyncOpenAI", lambda **_: fake_openai)
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        openai_api_key="not-a-real-key",
        agent_max_rewrite_attempts=2,
    )
    embedding = AsyncMock()
    embedding.embedding_dimension = 1536
    embedding.embed_texts = AsyncMock(return_value=[[0.1] * 1536])
    store = AsyncMock()
    store.search_similar = AsyncMock(return_value=[])
    vector = VectorRetriever(AsyncMock(), settings, embedding_service=embedding, vector_store=store)
    empty = AsyncMock()
    empty.retrieve = AsyncMock(return_value=[])
    chat = AsyncMock()

    result = await run_drive_graph(
        AsyncMock(),
        settings,
        question="What is tensile strength?",
        user_id=USER,
        chat_service=chat,
        retrievers=cast(
            dict[RetrieverName, Retriever], {"vector": vector, "keyword": empty, "metadata": empty}
        ),
    )

    assert result.answer == NO_EVIDENCE_ANSWER
    assert embedding.embed_texts.await_count == 3  # first round + 2 rewrite rounds
    assert rewrite_requests.await_count == 2  # separate client, one chat request per rewrite
    chat.generate_grounded_answer.assert_not_awaited()
