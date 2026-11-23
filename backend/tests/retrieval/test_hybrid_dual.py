"""Original question plus the model's query (hybrid retrieval C2): ``HybridRetriever.retrieve_dual``."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.types import RetrievedChunk
from app.routing.intent_frame.execution import RetrievalRequest
from app.routing.intent_frame.scope import EligibleCollectionScope, ResolvedFileScope

USER = uuid.UUID(int=7)
QUESTION = "How many days of annual leave do employees get?"
MODEL_QUERY = "annual leave days per year"


def chunk(n: int, score: float = 0.9) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.UUID(int=n),
        document_id=uuid.UUID(int=1000 + n),
        drive_file_id=uuid.UUID(int=2000 + n),
        filename=f"f{n}.txt",
        mime_type="text/plain",
        modified_at=datetime(2026, 1, 1, tzinfo=UTC),
        chunk_index=0,
        text=f"text {n}",
        score=score,
        primary_source="vector",
        source_scores={"vector": score},
    )


def ranked(*numbers: int) -> list[RetrievedChunk]:
    # Descending vector scores keep the reranked order equal to the given order.
    return [chunk(n, 0.9 - 0.05 * i) for i, n in enumerate(numbers)]


def request(query: str = MODEL_QUERY, scope=None, limit: int = 20) -> RetrievalRequest:
    return RetrievalRequest(
        user_id=USER, query=query, scope=scope or EligibleCollectionScope(), candidate_limit=limit
    )


class Source:
    """A stand-in retriever: answers per query text, records every request it receives."""

    def __init__(self, by_query: dict[str, object]) -> None:
        self.by_query = by_query
        self.requests: list[RetrievalRequest] = []

    async def retrieve(self, req: RetrievalRequest) -> list[RetrievedChunk]:
        self.requests.append(req)
        outcome = self.by_query.get(req.query.strip(), [])
        if isinstance(outcome, BaseException):
            raise outcome
        assert isinstance(outcome, list)
        return outcome


def make(vector: Source, **settings) -> HybridRetriever:
    empty = AsyncMock()
    empty.retrieve = AsyncMock(return_value=[])
    return HybridRetriever(
        db=AsyncMock(),
        settings=Settings(evidence_min_fusion_score=0.01, retrieval_top_k=8, **settings),
        vector_retriever=vector,  # type: ignore[arg-type]
        keyword_retriever=empty,
        metadata_retriever=empty,
    )


@pytest.mark.asyncio
async def test_both_queries_reach_the_retriever_with_identical_authorization_scope() -> None:
    vector = Source({QUESTION: ranked(1, 2), MODEL_QUERY: ranked(11, 12)})
    result = await make(vector).retrieve_dual(request(), QUESTION)

    assert sorted(r.query for r in vector.requests) == sorted([QUESTION, MODEL_QUERY])
    assert len(vector.requests) == 2
    for sent in vector.requests:
        assert sent.user_id == USER
        assert sent.scope == EligibleCollectionScope()
        assert sent.candidate_limit == 20
        assert sent.candidate_policy == "BOUNDED"
    assert result.strategy == "C2"


@pytest.mark.asyncio
async def test_an_exact_file_scope_is_copied_to_the_original_question_search() -> None:
    scope = ResolvedFileScope(file_ids=(uuid.UUID(int=2001),))
    vector = Source({QUESTION: ranked(1), MODEL_QUERY: ranked(1)})
    await make(vector).retrieve_dual(request(scope=scope, limit=7), QUESTION)
    assert {(r.scope, r.candidate_limit) for r in vector.requests} == {(scope, 7)}


@pytest.mark.asyncio
async def test_result_alternates_original_question_first() -> None:
    vector = Source({QUESTION: ranked(1, 2, 3), MODEL_QUERY: ranked(11, 12, 13)})
    result = await make(vector).retrieve_dual(request(), QUESTION)
    assert [c.chunk_id.int for c in result.chunks] == [1, 11, 2, 12, 3, 13]
    assert [c.chunk_id.int for c in result.original_chunks] == [1, 2, 3]
    assert [c.chunk_id.int for c in result.model_chunks] == [11, 12, 13]


@pytest.mark.asyncio
async def test_model_list_is_exactly_what_the_control_strategy_returns() -> None:
    vector = Source({QUESTION: ranked(1, 2), MODEL_QUERY: ranked(11, 12, 13)})
    retriever = make(vector)
    control = await retriever.retrieve(request())
    result = await retriever.retrieve_dual(request(), QUESTION)
    assert [c.chunk_id for c in result.model_chunks] == [c.chunk_id for c in control]


@pytest.mark.asyncio
async def test_final_list_is_capped_at_top_k_and_has_no_duplicates() -> None:
    vector = Source(
        {QUESTION: ranked(1, 2, 3, 4, 5, 6, 7, 8), MODEL_QUERY: ranked(8, 7, 6, 5, 4, 3, 2, 1)}
    )
    result = await make(vector).retrieve_dual(request(), QUESTION)
    found = [c.chunk_id for c in result.chunks]
    assert len(found) == len(set(found)) == 8


@pytest.mark.asyncio
async def test_identical_queries_after_normalization_search_once_and_use_the_control() -> None:
    vector = Source({MODEL_QUERY: ranked(1, 2)})
    result = await make(vector).retrieve_dual(request(), "  " + MODEL_QUERY + "\n")
    assert len(vector.requests) == 1
    assert result.strategy == "A"
    assert result.skipped_reason == "identical_queries"
    assert result.retrieval_calls == 1 and result.embedding_calls == 1
    assert [c.chunk_id.int for c in result.chunks] == [1, 2]


@pytest.mark.asyncio
async def test_original_search_failure_keeps_model_results_and_records_degradation() -> None:
    vector = Source({QUESTION: RuntimeError("secret detail 42"), MODEL_QUERY: ranked(11, 12)})
    result = await make(vector).retrieve_dual(request(), QUESTION)
    assert [c.chunk_id.int for c in result.chunks] == [11, 12]
    assert result.degraded_reason == "original_question_search_failed:RuntimeError"
    assert "secret" not in result.degraded_reason  # only the class name, never the message
    assert result.strategy == "C2"


@pytest.mark.asyncio
async def test_model_query_failure_is_raised_as_before() -> None:
    vector = Source({QUESTION: ranked(1), MODEL_QUERY: RuntimeError("boom")})
    with pytest.raises(RuntimeError, match="boom"):
        await make(vector).retrieve_dual(request(), QUESTION)


@pytest.mark.asyncio
async def test_model_query_failure_leaves_no_task_running() -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    class Slow(Source):
        async def retrieve(self, req: RetrievalRequest) -> list[RetrievedChunk]:
            if req.query == QUESTION:
                started.set()
                try:
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    cancelled.set()
                    raise
                return []
            await started.wait()
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await make(Slow({})).retrieve_dual(request(), QUESTION)
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_outer_cancellation_cancels_both_searches() -> None:
    both_running = asyncio.Event()
    running = 0
    cancelled = 0

    class Hang(Source):
        async def retrieve(self, req: RetrievalRequest) -> list[RetrievedChunk]:
            nonlocal running, cancelled
            running += 1
            if running == 2:
                both_running.set()
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                cancelled += 1
                raise
            return []

    task = asyncio.ensure_future(make(Hang({})).retrieve_dual(request(), QUESTION))
    await asyncio.wait_for(both_running.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled == 2


@pytest.mark.asyncio
async def test_the_two_searches_really_run_concurrently() -> None:
    barrier: asyncio.Barrier = asyncio.Barrier(2)

    class Rendezvous(Source):
        async def retrieve(self, req: RetrievalRequest) -> list[RetrievedChunk]:
            # Deadlocks (and times out) unless both searches are in flight together.
            await asyncio.wait_for(barrier.wait(), 2)
            return await super().retrieve(req)

    vector = Rendezvous({QUESTION: ranked(1), MODEL_QUERY: ranked(11)})
    result = await make(vector).retrieve_dual(request(), QUESTION)
    assert len(result.chunks) == 2


@pytest.mark.asyncio
async def test_evidence_grading_still_applies_to_each_search() -> None:
    weak = [chunk(1, 0.01)]  # fusion score far below the minimum
    vector = Source({QUESTION: weak, MODEL_QUERY: ranked(11)})
    retriever = HybridRetriever(
        db=AsyncMock(),
        settings=Settings(evidence_min_fusion_score=0.3, retrieval_top_k=8),
        vector_retriever=vector,  # type: ignore[arg-type]
        keyword_retriever=AsyncMock(retrieve=AsyncMock(return_value=[])),
        metadata_retriever=AsyncMock(retrieve=AsyncMock(return_value=[])),
    )
    result = await retriever.retrieve_dual(request(), QUESTION)
    # The original question's list failed grading and contributes nothing; the model's list passed.
    assert [c.chunk_id.int for c in result.chunks] == [11]
    assert result.original_chunks == []


@pytest.mark.asyncio
async def test_both_insufficient_returns_empty_not_an_error() -> None:
    vector = Source({QUESTION: [chunk(1, 0.01)], MODEL_QUERY: [chunk(2, 0.01)]})
    retriever = HybridRetriever(
        db=AsyncMock(),
        settings=Settings(evidence_min_fusion_score=0.3, retrieval_top_k=8),
        vector_retriever=vector,  # type: ignore[arg-type]
        keyword_retriever=AsyncMock(retrieve=AsyncMock(return_value=[])),
        metadata_retriever=AsyncMock(retrieve=AsyncMock(return_value=[])),
    )
    result = await retriever.retrieve_dual(request(), QUESTION)
    assert result.chunks == [] and result.degraded_reason is None


@pytest.mark.asyncio
async def test_instrumentation_counts_calls_and_overlap_without_content() -> None:
    vector = Source({QUESTION: ranked(1, 2), MODEL_QUERY: ranked(2, 3)})
    result = await make(vector).retrieve_dual(request(), QUESTION)
    assert (result.retrieval_calls, result.embedding_calls) == (2, 2)
    assert result.latency_ms >= 0
    assert result.overlap == 1
    assert result.strategy == "C2" and result.degraded_reason is None
    assert not hasattr(result, "query") and not hasattr(result, "original_question")


@pytest.mark.asyncio
async def test_a_blank_original_question_is_refused_not_searched() -> None:
    vector = Source({MODEL_QUERY: ranked(1)})
    result = await make(vector).retrieve_dual(request(), "   ")
    assert len(vector.requests) == 1
    assert result.strategy == "A" and result.skipped_reason == "blank_original_question"


# ---- per-file behaviour of the merged list (characterization, not a new rule) --------------------------------


def file_chunk(n: int, file_no: int, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.UUID(int=n),
        document_id=uuid.UUID(int=1000 + file_no),
        drive_file_id=uuid.UUID(int=2000 + file_no),
        filename=f"file{file_no}.txt",
        mime_type="text/plain",
        modified_at=datetime(2026, 1, 1, tzinfo=UTC),
        chunk_index=n,
        text=f"text {n}",
        score=score,
        primary_source="vector",
        source_scores={"vector": score},
    )


def per_file(chunks: list[RetrievedChunk]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for c in chunks:
        counts[c.drive_file_id.int - 2000] = counts.get(c.drive_file_id.int - 2000, 0) + 1
    return counts


@pytest.mark.asyncio
async def test_per_file_cap_holds_inside_each_list_but_the_merged_list_can_hold_twice_the_cap() -> (
    None
):
    # Each list: three strong chunks of file 1, then five chunks of five other files.
    question = [file_chunk(10 + i, 1, 0.95 - 0.01 * i) for i in range(3)] + [
        file_chunk(20 + i, 100 + i, 0.5 - 0.01 * i) for i in range(5)
    ]
    model = [file_chunk(30 + i, 1, 0.94 - 0.01 * i) for i in range(3)] + [
        file_chunk(40 + i, 200 + i, 0.5 - 0.01 * i) for i in range(5)
    ]
    vector = Source({QUESTION: question, MODEL_QUERY: model})
    result = await make(vector).retrieve_dual(request(), QUESTION)  # default cap: 3 per file

    assert max(per_file(result.original_chunks).values()) == 3
    assert max(per_file(result.model_chunks).values()) == 3
    assert per_file(result.chunks)[1] == 6  # 3 + 3: the cap is not applied again after the merge
    assert len(result.chunks) == 8


@pytest.mark.asyncio
async def test_without_a_per_file_cap_the_whole_merged_list_can_be_one_file() -> None:
    # An exact-file scope (like a named file) has no per-file limit: both lists may fill up with that file.
    scope = ResolvedFileScope(file_ids=(uuid.UUID(int=2001),))
    question = [file_chunk(10 + i, 1, 0.9 - 0.01 * i) for i in range(8)]
    model = [file_chunk(30 + i, 1, 0.9 - 0.01 * i) for i in range(8)]
    vector = Source({QUESTION: question, MODEL_QUERY: model})
    result = await make(vector).retrieve_dual(request(scope=scope), QUESTION)
    assert per_file(result.chunks) == {1: 8}


@pytest.mark.asyncio
async def test_the_per_list_cap_is_soft_when_no_other_file_has_candidates() -> None:
    question = [file_chunk(10 + i, 1, 0.9 - 0.01 * i) for i in range(5)]
    model = [file_chunk(30 + i, 1, 0.9 - 0.01 * i) for i in range(5)]
    vector = Source({QUESTION: question, MODEL_QUERY: model})
    result = await make(vector).retrieve_dual(request(), QUESTION)
    assert per_file(result.original_chunks) == {1: 5}  # existing refill rule, unchanged by C2
    assert per_file(result.chunks) == {1: 8}
