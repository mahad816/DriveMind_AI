"""Known defects in the native tool agent's final answer. Correct behaviour is asserted."""

import pytest

from app.agents.tool_rag.agent_models import AgentStepResult
from tests.agents.tool_rag.test_agent_loop import call, run
from tests.agents.tool_rag.test_grounding_policy import SEARCH
from tests.known_issues import known_issue

# --- KI-002 -----------------------------------------------------------------------------


@known_issue(
    "KI-002", "a valid [source_N] marker is accepted even when the claim is not in the evidence"
)
@pytest.mark.asyncio
async def test_ki002_claim_absent_from_evidence_is_not_published_with_a_citation():
    # run() retrieves one chunk whose text is "Authoritative refund policy text.".
    fabricated = "Refunds are always approved within 90 days. [source_1]"
    state, _, _ = await run([call("search_knowledge", SEARCH), AgentStepResult(text=fabricated)])
    assert "90 days" not in state["final_answer"], (
        "Citation checking only proves source_1 exists; it never checks the claim "
        "against that source, so an unsupported statement is shown with a real citation."
    )
