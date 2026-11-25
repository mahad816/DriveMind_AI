"""C2 (dual-query retrieval) through the real HTTP route, RagService, tool agent, executor and HybridRetriever.

Only the datastores and the language model are stand-ins (no network, no paid call). This is the free check that
a local request with ``RETRIEVAL_DUAL_QUERY_ENABLED`` on really runs both searches and hands the agent the merged
list, and that with the flag off the single-query path is unchanged.
"""

from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.agents.tool_rag.agent_models import AgentStepResult
from app.core.config import Settings
from app.retrieval.hybrid import HybridRetriever
from tests.agents.tool_rag.test_agent_loop import call
from tests.agents.tool_rag.test_revision_safety import row
from tests.agents.tool_rag.test_tool_execution import USER, chunk
from tests.test_tool_agent_api import api

QUESTION = "What is our policy for refunds?"
MODEL_QUERY = "refund policy days"
QUESTION_CHUNK = replace(
    chunk(), chunk_id=UUID(int=101), chunk_index=1, text="Refunds take 30 days."
)
MODEL_CHUNK = replace(chunk(), chunk_id=UUID(int=102), chunk_index=2, text="Approval is required.")


class Vector:
    """Returns a different chunk for the user's question than for the model's query, and records both."""

    def __init__(self) -> None:
        self.seen: list[tuple[str, UUID]] = []

    async def retrieve(self, req):
        self.seen.append((req.query, req.user_id))
        return [QUESTION_CHUNK] if req.query == QUESTION else [MODEL_CHUNK]


def wire(monkeypatch: pytest.MonkeyPatch, *, dual: bool) -> Vector:
    vector = Vector()
    empty = AsyncMock()
    empty.retrieve = AsyncMock(return_value=[])
    monkeypatch.setattr(
        "tests.test_tool_agent_api.Settings",
        lambda **kw: Settings(
            **{
                "_env_file": None,  # ignore any local .env
                "retrieval_dual_query_enabled": dual,
                "evidence_min_fusion_score": 0.01,
                **kw,
            }
        ),
    )
    monkeypatch.setattr(
        "tests.test_tool_agent_api.ScriptRetriever",
        lambda settings, chunks: HybridRetriever(
            db=AsyncMock(),
            settings=settings,
            vector_retriever=vector,  # type: ignore[arg-type]
            keyword_retriever=empty,
            metadata_retriever=empty,
        ),
    )
    return vector


def steps(answer: str = "Refunds take 30 days. [source_1] Approval is required. [source_2]"):
    return [
        call(
            "search_knowledge",
            {"query": MODEL_QUERY, "scope": {"kind": "ALL_ELIGIBLE_INDEXED_FILES"}},
            "search",
        ),
        AgentStepResult(text=answer),
    ]


ROWS = [row(1, "Refunds take 30 days."), row(2, "Approval is required.")]


@pytest.mark.asyncio
async def test_a_request_with_the_flag_on_searches_both_queries_and_cites_the_merged_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vector = wire(monkeypatch, dual=True)
    async with api(monkeypatch, steps(), rows=ROWS) as (client, *_):
        response = await client.post("/api/v1/chat", json={"question": QUESTION})
    assert response.status_code == 200, response.text
    assert sorted(q for q, _ in vector.seen) == sorted([QUESTION, MODEL_QUERY])
    assert {u for _, u in vector.seen} == {USER}
    body = response.json()
    assert body["retrieval_count"] == 2  # each chunk once: the merged list, not both lists appended
    assert [c["chunk_id"] for c in body["citations"]] == [str(UUID(int=101)), str(UUID(int=102))]


@pytest.mark.asyncio
async def test_a_request_with_the_flag_off_searches_only_the_models_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vector = wire(monkeypatch, dual=False)
    async with api(monkeypatch, steps("Approval is required. [source_1]"), rows=ROWS) as (
        client,
        *_,
    ):
        response = await client.post("/api/v1/chat", json={"question": QUESTION})
    assert response.status_code == 200, response.text
    assert [q for q, _ in vector.seen] == [MODEL_QUERY]
    assert response.json()["retrieval_count"] == 1
