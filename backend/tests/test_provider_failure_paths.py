"""M0 ticket 05: provider failure on the path production reaches (tool agent, `/chat`).

The v1 spec requires that a provider failure never produces an ungrounded answer. These tests
fake the agent model and the claim-check model; no network, no database, no paid API.

* The answering model failing at any step, including after evidence was retrieved, must end in
  HTTP 503 with nothing saved and no fallback to the legacy pipeline (protective, pass today).
* The claim-check model failing is designed to fail open: the agent's answer is published
  without the claim check (characterises current behaviour; see the ticket's Findings).
"""

from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tool_rag.agent_models import AgentStepResult
from app.llm.base import ChatError
from app.services.tool_agent_service import ToolAgentAdapter
from tests.agents.tool_rag.test_agent_loop import InventoryDB, ScriptChat, call, chunk, file
from tests.agents.tool_rag.test_claim_check import make_settings
from tests.agents.tool_rag.test_grounding_policy import SEARCH
from tests.agents.tool_rag.test_tool_execution import USER
from tests.test_tool_agent_api import api, search

PROVIDER_BODY = "private provider body 7f3a"
EVIDENCE_TEXT = chunk().text  # what the scripted retriever returns


@pytest.mark.parametrize(
    "steps, expected_retrievals",
    [
        pytest.param([ChatError(PROVIDER_BODY)], 0, id="first-model-call"),
        pytest.param([search(), ChatError(PROVIDER_BODY)], 1, id="after-evidence-was-retrieved"),
        pytest.param(
            [
                search(),
                AgentStepResult(text="Approval is required. [source_9]"),
                ChatError(PROVIDER_BODY),
            ],
            1,
            id="during-the-citation-correction-retry",
        ),
    ],
)
async def test_answering_model_failure_returns_503_and_publishes_nothing(
    monkeypatch, steps, expected_retrievals
):
    async with api(monkeypatch, steps) as (client, db, chat, retriever, legacy):
        response = await client.post("/api/v1/chat", json={"question": "What is our policy?"})

    assert (
        len(retriever.requests) == expected_retrievals
    )  # evidence really was retrieved before the failure
    assert response.status_code == 503
    assert PROVIDER_BODY not in response.text and EVIDENCE_TEXT not in response.text
    assert not db.saved  # no query history row, so nothing is shown later either
    assert not chat.steps  # every scripted step ran: the failure came from the final one
    legacy.generate_grounded_answer.assert_not_awaited()
    legacy.generate_direct_answer.assert_not_awaited()
    legacy.generate_file_target_answer.assert_not_awaited()


async def test_claim_check_model_failure_publishes_the_unchecked_answer():
    unsupported = "Refunds are always approved within 90 days. [source_1]"
    retriever = AsyncMock()
    retriever.retrieve.return_value = [chunk()]
    checker = AsyncMock(side_effect=ChatError(PROVIDER_BODY))
    adapter = ToolAgentAdapter(
        cast(AsyncSession, InventoryDB([file()])),
        make_settings(tool_rag_agent_enabled=True),
        chat=ScriptChat([call("search_knowledge", SEARCH), AgentStepResult(text=unsupported)]),
        retriever=retriever,
        claim_complete=checker,
    )

    result = await adapter.answer(
        "What is the refund policy?", user_id=USER, history=[], history_window_complete=True
    )

    checker.assert_awaited_once()
    # Fail open: the statement the evidence does not contain is published with a real citation.
    assert "90 days" in result.answer
    assert len(result.citations) == 1 and result.citations[0].chunk_id == chunk().chunk_id
