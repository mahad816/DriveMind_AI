"""``search_knowledge`` with the original-question search alongside the model's query (C2), behind a flag."""

import logging
from typing import Literal
from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.agents.tool_rag.errors import ToolErrorCode
from app.agents.tool_rag.execution.executor import ToolExecutor
from app.retrieval.hybrid import DualRetrieval
from app.routing.intent_frame.scope import EligibleCollectionScope, ResolvedFileScope
from tests.agents.tool_rag.test_tool_execution import USER, chunk, context, execute, file

QUESTION = "What is the refund window for customers?"
MODEL_QUERY = "refund window days"
ALL = {"kind": "ALL_ELIGIBLE_INDEXED_FILES"}


def dual_result(
    *chunks, strategy: Literal["A", "C2"] = "C2", degraded=None, skipped=None
) -> DualRetrieval:
    return DualRetrieval(
        chunks=list(chunks),
        original_chunks=list(chunks),
        model_chunks=list(chunks),
        strategy=strategy,
        degraded_reason=degraded,
        skipped_reason=skipped,
        retrieval_calls=2,
        embedding_calls=2,
        latency_ms=1.5,
        overlap=0,
    )


def setup(*, enabled=True, history=False, question=QUESTION, files=None, retriever=None):
    retriever = retriever or AsyncMock()
    retriever.retrieve.return_value = [chunk()]
    retriever.retrieve_dual.return_value = dual_result(chunk())
    ctx = replace(
        context(files if files is not None else [file()], retriever),
        dual_query_enabled=enabled,
        original_question=question,
        has_prior_history=history,
    )
    return retriever, ctx


async def search(ctx, query=MODEL_QUERY, scope=None):
    return await execute(
        "search_knowledge", {"query": query, "scope": scope or ALL, "candidate_limit": 7}, ctx
    )


@pytest.mark.asyncio
async def test_flag_off_by_default_keeps_the_single_query_path():
    retriever, ctx = setup(enabled=False)
    out = await search(ctx)
    assert out.error is None
    retriever.retrieve.assert_awaited_once()
    retriever.retrieve_dual.assert_not_awaited()


@pytest.mark.asyncio
async def test_the_context_flag_defaults_to_off():
    assert context([file()], AsyncMock()).dual_query_enabled is False


@pytest.mark.asyncio
async def test_flag_on_uses_both_queries_and_the_current_turn_question():
    retriever, ctx = setup()
    out = await search(ctx)
    assert out.error is None
    retriever.retrieve.assert_not_awaited()
    retriever.retrieve_dual.assert_awaited_once()
    request, original = retriever.retrieve_dual.await_args.args
    assert request.query == MODEL_QUERY  # the primary search is the model's query, unchanged
    assert original == QUESTION  # the current user turn, not a model-written text
    assert request.user_id == USER and request.candidate_limit == 7
    assert isinstance(request.scope, EligibleCollectionScope)
    assert out.internal_result.sections[0].combined_text == chunk().text


@pytest.mark.asyncio
async def test_an_exact_file_scope_is_passed_through():
    retriever, ctx = setup()
    handle = ctx.handles.register_file(UUID(int=10))
    scope = {"kind": "EXACT_FILES", "file_handles": [handle.model_dump()]}
    out = await search(ctx, scope=scope)
    assert out.error is None
    request, _ = retriever.retrieve_dual.await_args.args
    assert isinstance(request.scope, ResolvedFileScope)
    assert request.scope.file_ids == (UUID(int=10),)


@pytest.mark.asyncio
async def test_history_dependent_turn_keeps_the_single_query_path():
    retriever, ctx = setup(history=True)
    out = await search(ctx)
    assert out.error is None
    retriever.retrieve.assert_awaited_once()
    retriever.retrieve_dual.assert_not_awaited()


@pytest.mark.asyncio
async def test_blank_original_question_keeps_the_single_query_path():
    retriever, ctx = setup(question="  ")
    await search(ctx)
    retriever.retrieve.assert_awaited_once()
    retriever.retrieve_dual.assert_not_awaited()


@pytest.mark.asyncio
async def test_file_evidence_never_uses_the_second_query():
    retriever, ctx = setup()
    handle = ctx.handles.register_file(UUID(int=10))
    await execute("file_evidence", {"file_handle": handle.model_dump(), "query": "summary"}, ctx)
    retriever.retrieve_dual.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_chunk_of_another_users_file_from_either_search_is_rejected():
    foreign = chunk(11)
    retriever, ctx = setup(files=[file(10), file(11, user=UUID(int=2))])
    retriever.retrieve_dual.return_value = dual_result(chunk(), foreign)
    out = await search(ctx)
    assert out.error is not None and out.error.code == ToolErrorCode.NOT_FOUND
    assert out.internal_result is None


@pytest.mark.asyncio
async def test_exact_scope_violation_in_the_combined_list_is_rejected():
    retriever, ctx = setup(files=[file(10), file(11)])
    retriever.retrieve_dual.return_value = dual_result(chunk(11))
    handle = ctx.handles.register_file(UUID(int=10))
    scope = {"kind": "EXACT_FILES", "file_handles": [handle.model_dump()]}
    out = await search(ctx, scope=scope)
    assert out.error.code == ToolErrorCode.INTERNAL_ERROR and out.internal_result is None


@pytest.mark.asyncio
async def test_primary_failure_keeps_the_existing_error_behaviour():
    retriever, ctx = setup()
    retriever.retrieve_dual.side_effect = RuntimeError("vector store down")
    out = await search(ctx)
    assert out.error.code == ToolErrorCode.INTERNAL_ERROR
    assert out.internal_result is None


@pytest.mark.asyncio
async def test_empty_combined_result_is_an_empty_section_list_not_an_error():
    retriever, ctx = setup()
    retriever.retrieve_dual.return_value = dual_result()
    out = await search(ctx)
    assert out.error is None and out.internal_result.sections == ()


@pytest.mark.asyncio
async def test_strategy_and_counts_are_logged_without_any_query_text(caplog):
    retriever, ctx = setup()
    retriever.retrieve_dual.return_value = dual_result(
        chunk(), degraded="original_question_search_failed:RuntimeError"
    )
    with caplog.at_level(logging.INFO, logger="app.agents.tool_rag.execution.executor"):
        await search(ctx)
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "strategy=C2" in text and "retrieval_calls=2" in text and "embedding_calls=2" in text
    assert "original_question_search_failed:RuntimeError" in text
    assert QUESTION not in text and MODEL_QUERY not in text and chunk().text not in text


@pytest.mark.asyncio
async def test_executor_still_exposes_four_tools():
    assert len(list(ToolExecutor().registry.definitions())) == 4


# ---- through the real agent service and a real HybridRetriever on stub sources -------------------------------


class _Sources:
    """Vector stub that records the query text and user of every search it receives."""

    def __init__(self):
        self.seen = []

    async def retrieve(self, req):
        self.seen.append((req.query, req.user_id, req.scope))
        return [chunk()]


async def _agent_run(*, enabled, history=(), question=QUESTION):
    from typing import cast

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.agents.tool_rag.agent_models import AgentStepResult
    from app.agents.tool_rag.agent_service import ToolRagAgentService
    from app.core.config import Settings
    from app.retrieval.hybrid import HybridRetriever
    from tests.agents.tool_rag.test_agent_loop import ScriptChat, assert_consumed, call
    from tests.agents.tool_rag.test_tool_execution import InventoryDB

    vector = _Sources()
    empty = AsyncMock()
    empty.retrieve = AsyncMock(return_value=[])
    retriever = HybridRetriever(
        db=AsyncMock(),
        settings=Settings(retrieval_dual_query_enabled=enabled, evidence_min_fusion_score=0.01),
        vector_retriever=vector,  # type: ignore[arg-type]
        keyword_retriever=empty,
        metadata_retriever=empty,
    )
    chat = ScriptChat(
        [
            call("search_knowledge", {"query": MODEL_QUERY, "scope": ALL}),
            AgentStepResult(text="Thirty days. [source_1]"),
        ]
    )
    state = await ToolRagAgentService(chat).run(
        question,
        user_id=USER,
        db=cast(AsyncSession, InventoryDB([file()])),
        retriever=retriever,
        history=history,
    )
    assert_consumed(chat)
    return state, vector


@pytest.mark.asyncio
async def test_agent_run_with_the_flag_on_searches_the_question_and_the_model_query():
    state, vector = await _agent_run(enabled=True)
    assert sorted(q for q, _, _ in vector.seen) == sorted([QUESTION, MODEL_QUERY])
    assert {(u, s) for _, u, s in vector.seen} == {(USER, EligibleCollectionScope())}
    assert len(state["evidence"]) == 1  # the shared chunk appears once


@pytest.mark.asyncio
async def test_agent_run_with_the_flag_off_searches_only_the_model_query():
    _, vector = await _agent_run(enabled=False)
    assert [q for q, _, _ in vector.seen] == [MODEL_QUERY]


@pytest.mark.asyncio
async def test_agent_run_with_prior_history_searches_only_the_model_query():
    from app.agents.tool_rag.agent_models import AgentMessage

    history = (
        AgentMessage(role="USER", text="Tell me about the leave policy."),
        AgentMessage(role="ASSISTANT", text="It covers annual leave."),
    )
    _, vector = await _agent_run(enabled=True, history=history, question="and the refund one?")
    assert [q for q, _, _ in vector.seen] == [MODEL_QUERY]


@pytest.mark.asyncio
async def test_the_original_question_searched_is_the_question_of_this_run():
    _, vector = await _agent_run(enabled=True, question="A brand new standalone question?")
    assert "A brand new standalone question?" in [q for q, _, _ in vector.seen]
    assert all("leave policy" not in q for q, _, _ in vector.seen)


# ---- first eligible search only (Owner decision, 2026-11-24) ---------------------------------------------------


@pytest.mark.asyncio
async def test_only_the_first_search_of_a_run_uses_both_queries():
    retriever, ctx = setup()
    first = await search(ctx, query="first model query")
    second = await search(ctx, query="refined model query")
    third = await search(ctx, query="another refinement")
    assert first.error is None and second.error is None and third.error is None
    retriever.retrieve_dual.assert_awaited_once()
    assert retriever.retrieve_dual.await_args.args[0].query == "first model query"
    assert [c.args[0].query for c in retriever.retrieve.await_args_list] == [
        "refined model query",
        "another refinement",
    ]


@pytest.mark.asyncio
async def test_resolve_file_first_does_not_use_up_the_allowance():
    retriever, ctx = setup()
    out = await execute("resolve_file", {"reference": "report.pdf"}, ctx)
    assert out.error is None
    assert ctx.dual_query_allowance.used is False
    await search(ctx)
    retriever.retrieve_dual.assert_awaited_once()
    retriever.retrieve.assert_not_awaited()


@pytest.mark.asyncio
async def test_other_tools_never_claim_the_allowance():
    _, ctx = setup()
    await execute("files_query", {"operation": "COUNT", "scope": ALL}, ctx)
    handle = ctx.handles.register_file(UUID(int=10))
    await execute("file_evidence", {"file_handle": handle.model_dump(), "query": "summary"}, ctx)
    assert ctx.dual_query_allowance.used is False


@pytest.mark.asyncio
async def test_a_failed_first_search_still_uses_the_allowance_so_a_retry_cannot_reset_it():
    retriever, ctx = setup()
    retriever.retrieve_dual.side_effect = RuntimeError("vector store down")
    failed = await search(ctx, query="first attempt")
    assert failed.error.code == ToolErrorCode.INTERNAL_ERROR
    retried = await search(ctx, query="second attempt")
    assert retried.error is None
    retriever.retrieve_dual.assert_awaited_once()
    assert retriever.retrieve.await_args.args[0].query == "second attempt"


@pytest.mark.asyncio
async def test_a_search_that_fails_before_searching_claims_nothing():
    retriever, ctx = setup()
    bad = {"kind": "EXACT_FILES", "file_handles": [{"kind": "FILE", "value": "file_99"}]}
    out = await search(ctx, scope=bad)
    assert out.error is not None
    assert ctx.dual_query_allowance.used is False
    retriever.retrieve_dual.assert_not_awaited()
    await search(ctx)
    retriever.retrieve_dual.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled,history", [(True, True), (False, False)])
async def test_history_and_flag_off_never_claim_the_allowance(enabled, history):
    retriever, ctx = setup(enabled=enabled, history=history)
    await search(ctx)
    await search(ctx)
    assert ctx.dual_query_allowance.used is False
    retriever.retrieve_dual.assert_not_awaited()
    assert retriever.retrieve.await_count == 2


async def _two_search_runs(*, same_step: bool, runs: int = 1):
    from typing import cast

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.agents.tool_rag.agent_models import AgentStepResult, ToolCallRequest
    from app.agents.tool_rag.agent_service import ToolRagAgentService
    from app.core.config import Settings
    from app.retrieval.hybrid import HybridRetriever
    from tests.agents.tool_rag.test_agent_loop import ScriptChat, assert_consumed, call
    from tests.agents.tool_rag.test_tool_execution import InventoryDB

    vector = _Sources()
    empty = AsyncMock()
    empty.retrieve = AsyncMock(return_value=[])
    retriever = HybridRetriever(
        db=AsyncMock(),
        settings=Settings(retrieval_dual_query_enabled=True, evidence_min_fusion_score=0.01),
        vector_retriever=vector,  # type: ignore[arg-type]
        keyword_retriever=empty,
        metadata_retriever=empty,
    )
    args1 = {"query": "first model query", "scope": ALL}
    args2 = {"query": "refined model query", "scope": ALL}
    if same_step:
        steps = [
            AgentStepResult(
                tool_calls=(
                    ToolCallRequest(call_id="c1", tool_name="search_knowledge", arguments=args1),
                    ToolCallRequest(call_id="c2", tool_name="search_knowledge", arguments=args2),
                )
            ),
            AgentStepResult(text="Thirty days. [source_1]"),
        ]
    else:
        steps = [
            call("search_knowledge", args1, "c1"),
            call("search_knowledge", args2, "c2"),
            AgentStepResult(text="Thirty days. [source_1]"),
        ]
    per_run = []
    for _ in range(runs):
        chat = ScriptChat(list(steps))
        before = len(vector.seen)
        await ToolRagAgentService(chat).run(
            QUESTION,
            user_id=USER,
            db=cast(AsyncSession, InventoryDB([file()])),
            retriever=retriever,
        )
        assert_consumed(chat)
        per_run.append([q for q, _, _ in vector.seen[before:]])
    return per_run


FIRST, REFINED = "first model query", "refined model query"


def _assert_first_search_got_c2_and_second_got_a(seen: list[str]) -> None:
    # Three vector searches in total. The first search (C2) is two of them, the question and the model's first
    # query, in either order because they run concurrently; the second search (A) comes after and is the refined
    # model query alone. If the second call got C2 instead, seen[:2] would be {first, ...} followed by
    # {refined, question}, which these assertions reject.
    assert len(seen) == 3
    assert set(seen[:2]) == {QUESTION, FIRST}
    assert seen[2] == REFINED


@pytest.mark.asyncio
async def test_agent_run_first_search_uses_c2_and_the_second_uses_a():
    (seen,) = await _two_search_runs(same_step=False)
    _assert_first_search_got_c2_and_second_got_a(seen)


@pytest.mark.asyncio
async def test_two_searches_in_one_step_the_first_in_provider_order_gets_c2():
    (seen,) = await _two_search_runs(same_step=True)
    _assert_first_search_got_c2_and_second_got_a(seen)


@pytest.mark.asyncio
async def test_the_allowance_is_fresh_for_each_separate_agent_run():
    first_run, second_run = await _two_search_runs(same_step=False, runs=2)
    # The second run, with the same retriever, again asks the question once (in its first search), not zero times.
    _assert_first_search_got_c2_and_second_got_a(first_run)
    _assert_first_search_got_c2_and_second_got_a(second_run)
