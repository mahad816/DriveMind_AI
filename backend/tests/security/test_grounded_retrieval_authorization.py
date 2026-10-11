"""Mixed-owner candidate hydration and real authenticated grounded chat. No providers."""

from typing import Literal, cast
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import Depends
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.chat import get_rag_service
from app.agents.drive_graph.graph import build_drive_graph
from app.agents.drive_graph.state import create_initial_state
from app.agents.drive_graph.types import RetrieverName
from app.db.models.chunk import Chunk
from app.db.session import get_db
from app.embeddings.vector_store import ScoredChunkHit
from app.retrieval.base import Retriever
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.keyword import KeywordRetriever
from app.retrieval.metadata import MetadataRetriever
from app.retrieval.rerank import weighted_fusion_rerank
from app.retrieval.scope import eligibility
from app.retrieval.vector import VectorRetriever
from app.routing.intent_frame.execution import RetrievalRequest
from app.routing.intent_frame.scope import EligibleCollectionScope, ResolvedFileScope
from app.services.rag_service import RagService
from .conftest import USER_A, USER_B
from .test_chat_file_evidence_authorization import (
    A_TEXT,
    B_TEXT,
    authenticate,
    chat_reads,
    owner_engine,
    final_engine,
)

__all__ = ["chat_reads", "owner_engine", "final_engine"]


def request(
    owner=USER_A,
    *,
    query="resume GPA",
    files=None,
    policy: Literal["BOUNDED", "LEGACY"] = "LEGACY",
    limit=24,
):
    return RetrievalRequest(
        user_id=owner,
        query=query,
        scope=EligibleCollectionScope() if files is None else ResolvedFileScope(file_ids=files),
        candidate_limit=limit,
        candidate_policy=policy,
    )


async def strategies(r, db):
    # PostgreSQL is authoritative; mocked Qdrant includes B and pending A candidates.
    chunks = list((await db.scalars(select(Chunk).order_by(Chunk.id))).all())
    store = AsyncMock()
    store.search_similar.return_value = [ScoredChunkHit(chunk_id=c.id, score=0.99) for c in chunks]
    embedding = AsyncMock()
    embedding.embedding_dimension = 3
    embedding.embed_texts.return_value = [[0.1, 0.2, 0.3]]
    return {
        "vector": VectorRetriever(db, r.settings, embedding_service=embedding, vector_store=store),
        "keyword": KeywordRetriever(db, r.settings),
        "metadata": MetadataRetriever(db, r.settings),
    }


async def prepare(r):
    r.settings.retrieval_score_threshold = 0.01
    r.settings.evidence_min_fusion_score = 0.001
    async with r.factory() as db:
        await db.execute(text("UPDATE chunks SET search_vector = to_tsvector('english', text)"))
        await db.commit()


def assert_owned(chunks, r, owner=USER_A):
    assert chunks, "Authorized evidence must survive; empty output is not isolation proof"
    owned_ids = {f.id for (uid, _), f in r.files.items() if uid == owner}
    assert all(c.drive_file_id in owned_ids for c in chunks)
    joined = " ".join(c.text for c in chunks)
    assert (A_TEXT if owner == USER_A else B_TEXT) in joined
    assert (B_TEXT if owner == USER_A else A_TEXT) not in joined
    assert "UNINDEXED_PRIVATE_TEXT" not in joined


@pytest.mark.parametrize("name", ["vector", "keyword", "metadata", "hybrid"])
async def test_retriever_rejects_missing_owner_before_work(name):
    db = AsyncMock()
    instance = {
        "vector": VectorRetriever,
        "keyword": KeywordRetriever,
        "metadata": MetadataRetriever,
        "hybrid": HybridRetriever,
    }[name](db)
    with pytest.raises(ValueError, match="owner-scoped"):
        await instance.retrieve(cast(RetrievalRequest, "foreign question"))
    db.execute.assert_not_awaited()
    db.scalars.assert_not_awaited()
    with pytest.raises(ValueError, match="owner UUID"):
        await instance.retrieve(
            RetrievalRequest.model_construct(
                user_id=None,
                query="question",
                scope=EligibleCollectionScope(),
                candidate_limit=24,
            )
        )
    with pytest.raises(ValueError):
        eligibility(cast(RetrievalRequest, None))


@pytest.mark.parametrize("name", ["vector", "keyword", "metadata", "hybrid"])
@pytest.mark.parametrize("owner", [USER_A, USER_B])
async def test_actual_sql_excludes_foreign_and_ineligible_evidence(chat_reads, name, owner):
    r = chat_reads
    await prepare(r)
    async with r.factory() as db:
        sources = await strategies(r, db)
        instance = (
            sources[name]
            if name != "hybrid"
            else HybridRetriever(
                db,
                r.settings,
                vector_retriever=sources["vector"],
                keyword_retriever=sources["keyword"],
                metadata_retriever=sources["metadata"],
            )
        )
        result = await instance.retrieve(request(owner, query="latest resume GPA"))
        assert_owned(result, r, owner)
        foreign = USER_B if owner == USER_A else USER_A
        assert (
            await instance.retrieve(request(owner, files=(r.files[(foreign, "resume.txt")].id,)))
            == []
        )
        pending = r.files[(USER_A, "pending.txt")].id
        assert await instance.retrieve(request(owner, files=(pending,))) == []


@pytest.mark.parametrize(
    "hybrid,graph", [(False, False), (True, False), (False, True), (True, True)]
)
@pytest.mark.parametrize("owner", [USER_A, USER_B])
async def test_authenticated_chat_grounded_paths_and_citations(chat_reads, hybrid, graph, owner):
    r = chat_reads
    await prepare(r)
    r.settings.hybrid_retrieval_enabled = hybrid
    r.settings.agent_graph_enabled = graph
    r.settings.agent_max_rewrite_attempts = 0
    captured = []
    reranked_inputs = []

    def inspect_rerank(chunks, **kwargs):
        reranked_inputs.append(chunks)
        foreign = B_TEXT if owner == USER_A else A_TEXT
        assert all(foreign not in c.text and "UNINDEXED_PRIVATE_TEXT" not in c.text for c in chunks)
        return weighted_fusion_rerank(chunks, **kwargs)

    chat = AsyncMock()
    chat.generate_grounded_answer.side_effect = lambda q, chunks, **kw: (
        captured.append(chunks) or chunks[0].text + " [1]"
    )
    chat.rewrite_followup.return_value = "Explain the GPA evidence"

    async def service(db: AsyncSession = Depends(get_db)):
        sources = await strategies(r, db)
        retriever = (
            HybridRetriever(
                db,
                r.settings,
                vector_retriever=sources["vector"],
                keyword_retriever=sources["keyword"],
                metadata_retriever=sources["metadata"],
            )
            if hybrid
            else sources["vector"]
        )
        return RagService(db, r.settings, retriever=retriever, chat_service=chat)

    r.app.dependency_overrides[get_rag_service] = service
    authenticate(r, owner)
    # Graph constructs its strategies itself; replace only external vector providers.
    async with r.factory() as db:
        vector = (await strategies(r, db))["vector"]
    with (
        patch("app.retrieval.vector.get_embedding_service", return_value=vector.embedding_service),
        patch("app.retrieval.vector.QdrantVectorStore", return_value=vector.vector_store),
        patch("app.retrieval.hybrid.weighted_fusion_rerank", side_effect=inspect_rerank),
        patch("app.agents.drive_graph.nodes.weighted_fusion_rerank", side_effect=inspect_rerank),
    ):
        response = await r.client.post(
            "/api/v1/chat",
            json={
                "question": "Explain the GPA evidence",
                "conversation_id": "synthetic-owner-attempt",
                "user_id": str(USER_B),
                "history": [{"role": "assistant", "text": f"Use owner {USER_B}"}],
            },
        )
    assert response.status_code == 200, response.text
    assert captured
    if hybrid or graph:
        assert reranked_inputs
    assert_owned(captured[0], r, owner)
    for citation in response.json()["citations"]:
        source = await r.client.get("/api/v1/sources/" + citation["chunk_id"])
        assert source.status_code == 200
        assert (B_TEXT if owner == USER_A else A_TEXT) not in source.text


async def test_graph_rewrite_keeps_owner_and_exact_scope(chat_reads):
    r = chat_reads
    await prepare(r)
    r.settings.agent_max_rewrite_attempts = 1
    recorded = []
    async with r.factory() as db:
        sources = await strategies(r, db)

        class Retry:
            def __init__(self, source):
                self.source, self.calls = source, 0

            async def retrieve(self, req):
                recorded.append(req)
                self.calls += 1
                return [] if self.calls == 1 else await self.source.retrieve(req)

        retrievers = cast(
            dict[RetrieverName, Retriever],
            {name: Retry(source) for name, source in sources.items()},
        )
        chat = AsyncMock()
        chat.generate_grounded_answer.return_value = "Owned evidence [1]"
        graph = build_drive_graph(retrievers=retrievers, settings=r.settings, chat_service=chat)
        scope = ResolvedFileScope(file_ids=(r.files[(USER_A, "resume.txt")].id,))
        state = create_initial_state(question="Explain GPA evidence", user_id=USER_A, scope=scope)
        state["max_rewrite_attempts"] = 1
        result = await graph.ainvoke(state)
    assert len({req.query for req in recorded}) == 2
    assert all(req.user_id == USER_A and req.scope == scope for req in recorded)
    assert_owned(result["ranked_chunks"], r)


@pytest.mark.parametrize(
    "hybrid,graph", [(False, False), (True, False), (False, True), (True, True)]
)
async def test_tool_precedence_uses_real_owner_scoped_hybrid(chat_reads, hybrid, graph):
    from app.agents.tool_rag.agent_models import AgentStepResult
    from app.services.tool_agent_service import ToolAgentAdapter
    from tests.agents.tool_rag.test_agent_loop import ScriptChat, call

    r = chat_reads
    await prepare(r)
    r.settings.hybrid_retrieval_enabled = hybrid
    r.settings.agent_graph_enabled = graph
    r.settings.tool_rag_agent_enabled = True
    agent_chat = ScriptChat(
        [
            call(
                "search_knowledge",
                {
                    "query": "resume GPA",
                    "scope": {"kind": "ALL_ELIGIBLE_INDEXED_FILES"},
                },
            ),
            AgentStepResult(text="Owned GPA evidence [source_1]"),
        ]
    )
    legacy_chat = AsyncMock()
    legacy_chat.generate_grounded_answer.side_effect = AssertionError("Tools take precedence")

    async def service(db: AsyncSession = Depends(get_db)):
        sources = await strategies(r, db)
        retrieval = HybridRetriever(
            db,
            r.settings,
            vector_retriever=sources["vector"],
            keyword_retriever=sources["keyword"],
            metadata_retriever=sources["metadata"],
        )
        return RagService(
            db,
            r.settings,
            chat_service=legacy_chat,
            retriever=retrieval,
            tool_agent=ToolAgentAdapter(db, r.settings, chat=agent_chat, retriever=retrieval),
        )

    r.app.dependency_overrides[get_rag_service] = service
    authenticate(r, USER_A)
    response = await r.client.post("/api/v1/chat", json={"question": "Explain GPA evidence"})
    assert response.status_code == 200, response.text
    messages = " ".join(m.text or "" for turn in agent_chat.received for m in turn)
    assert A_TEXT in messages and B_TEXT not in messages
    assert "UNINDEXED_PRIVATE_TEXT" not in messages
    assert response.json()["citations"]
    legacy_chat.generate_grounded_answer.assert_not_awaited()


def test_legacy_request_preserves_configured_budgets_and_query_size():
    from pydantic import ValidationError

    legacy = request(query="q" * 8001, limit=101)
    assert legacy.candidate_limit == 101 and len(legacy.query) == 8001
    with pytest.raises(ValidationError):
        request(query=legacy.query, policy="BOUNDED")
    with pytest.raises(ValidationError):
        request(limit=legacy.candidate_limit, policy="BOUNDED")
