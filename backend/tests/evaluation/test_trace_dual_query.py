"""``RecordingRetriever`` with the dual-query strategy (C2-cap3): one logical search, the merged evidence.

Regression for review finding P1 of ``docs/tickets/hybrid-retrieval-comparison/02-answer-quality-pilot.md``:
``retrieve_dual`` calls ``retrieve_with_grade`` twice, so the recorder logged two searches (the user's question
as an extra "agent query") with the two unmerged candidate lists, and never the merged top 8 the agent received.
Everything here is free and synthetic: the pipeline stage under the recorder is replaced by a stub.
"""

import asyncio
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.config import Settings
from app.retrieval.grade import EvidenceGrade
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.types import RetrievedChunk
from app.routing.intent_frame.execution import RetrievalRequest
from app.routing.intent_frame.scope import EligibleCollectionScope, ResolvedFileScope
from evaluation.rag_eval import deep, target
from evaluation.rag_eval.anchors import AnchorMap
from evaluation.rag_eval.trace import (
    CaseTrace,
    RecordingRetriever,
    execution_summary,
    trace_var,
)

QUESTION = "What is the policy on remote work?"
MODEL_QUERY = "remote work policy days per week"


def chunk(index: int, name: str | None = None) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.UUID(int=index),
        document_id=uuid.UUID(int=100 + index),
        drive_file_id=uuid.UUID(int=200 + index),
        filename=name or f"file{index}.txt",
        mime_type="text/plain",
        modified_at=datetime(2026, 1, 1, tzinfo=UTC),
        chunk_index=0,
        text=f"text {index}",
        score=1 - index / 100,
        source_scores={"vector": 0.5},
        fusion_score=0.5,
    )


MODEL_LIST = [chunk(i) for i in range(1, 9)]  # 1..8, the model query's graded list
ORIGINAL_LIST = [chunk(i) for i in range(11, 19)]  # 11..18, the question's graded list
# Round robin, original first, one distinct file per chunk (the per-file cap never bites):
MERGED_IDS = [11, 1, 12, 2, 13, 3, 14, 4]


def ids(entries: list[dict[str, Any]]) -> list[int]:
    return [uuid.UUID(e["chunk_id"]).int for e in entries]


def settings(*, dual: bool = True) -> Settings:
    return target.with_retrieval_strategy(target.eval_settings(), "C2-cap3" if dual else "A")


def request(query: str = MODEL_QUERY, scope: Any = None) -> RetrievalRequest:
    return RetrievalRequest(
        user_id=uuid.uuid4(),
        query=query,
        scope=scope or EligibleCollectionScope(),
        candidate_limit=20,
    )


@pytest.fixture
def stage(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace the pipeline stage under the recorder; count its calls (each one is a provider-call stand-in)."""
    state: dict[str, Any] = {"calls": [], "fail": {}}

    async def inner(self: Any, req: Any, *, trace: Any = None) -> EvidenceGrade:
        state["calls"].append(req.query)
        await asyncio.sleep(0)  # let both searches be in flight together, as in production
        if req.query in state["fail"]:
            raise state["fail"][req.query]
        chunks = MODEL_LIST if req.query == MODEL_QUERY else ORIGINAL_LIST
        return EvidenceGrade(sufficient=True, reason="ok", chunks=list(chunks))

    monkeypatch.setattr(HybridRetriever, "retrieve_with_grade", inner)
    return state


def recorder(*, dual: bool = True) -> RecordingRetriever:
    return RecordingRetriever(SimpleNamespace(), settings(dual=dual))  # type: ignore[arg-type]


@pytest.fixture
def case() -> CaseTrace:
    trace = CaseTrace()
    trace_var.set(trace)
    return trace


async def test_a_dual_search_is_one_logical_search_with_the_merged_chunks(
    stage: dict[str, Any], case: CaseTrace
) -> None:
    found = await recorder().retrieve_dual(request(), QUESTION)
    assert [c.chunk_id.int for c in found.chunks] == MERGED_IDS  # the retriever is unchanged
    (search,) = case.searches  # one, not two
    assert search["query"] == MODEL_QUERY
    assert ids(search["chunks"]) == MERGED_IDS  # exactly what the agent receives, in order
    assert [e["rank"] for e in search["chunks"]] == list(range(1, 9))
    dual = search["dual"]
    assert dual["strategy"] == "C2" and dual["skipped_reason"] is None
    assert dual["supplemental_query"] == {"source": "user_question"}
    assert QUESTION not in repr(
        case.as_dict()
    )  # the question is a flag here, never a second "query"
    assert [uuid.UUID(i).int for i in dual["model_chunk_ids"]] == list(range(1, 9))
    assert [uuid.UUID(i).int for i in dual["original_chunk_ids"]] == list(range(11, 19))


async def test_the_execution_summary_counts_one_search_and_one_agent_query(
    stage: dict[str, Any], case: CaseTrace
) -> None:
    await recorder().retrieve_dual(request(), QUESTION)
    summary = execution_summary(case)
    assert summary["search_count"] == 1 and summary["agent_queries"] == [MODEL_QUERY]


async def test_the_underlying_pipeline_still_runs_twice_and_the_accounting_says_so(
    stage: dict[str, Any], case: CaseTrace
) -> None:
    await recorder().retrieve_dual(request(), QUESTION)
    assert sorted(stage["calls"]) == sorted(
        [MODEL_QUERY, QUESTION]
    )  # nothing suppressed or skipped
    dual = case.searches[0]["dual"]
    assert (dual["retrieval_calls"], dual["embedding_calls"]) == (2, 2)


async def test_a_candidate_removed_by_the_merge_is_not_counted_as_retrieved(
    stage: dict[str, Any], case: CaseTrace
) -> None:
    await recorder().retrieve_dual(request(), QUESTION)
    recorded = {i for s in case.searches for i in ids(s["chunks"])}
    assert recorded == set(MERGED_IDS)
    assert 8 not in recorded and 18 not in recorded  # in a candidate list, dropped by the merge
    dropped = AnchorMap("x.txt", "q", "single", (str(uuid.UUID(int=8)),))  # type: ignore[arg-type]
    kept = AnchorMap("x.txt", "q", "single", (str(uuid.UUID(int=11)),))  # type: ignore[arg-type]
    case_def = {
        "id": "t1",
        "expected_behavior": "answer",
        "expected_files": ["x.txt"],
        "citation_mode": "any",
    }
    row = {"trace": case.as_dict()}
    for anchor, retrieved in ((dropped, False), (kept, True)):
        resolved = deep.Resolved(
            "o", {"x.txt": "file8.txt"}, anchors={"t1": [anchor]}, database=True
        )
        result = deep._retrieval(case_def, row, resolved)
        assert result is not None
        assert result["anchor_retrieved"] is retrieved and result["searches"] == 1


async def test_a_single_query_search_is_recorded_as_before_also_after_a_dual_one(
    stage: dict[str, Any], case: CaseTrace
) -> None:
    retriever = recorder()
    await retriever.retrieve_dual(request(), QUESTION)
    await retriever.retrieve(
        request("a refinement")
    )  # the later, single-query search of the same run
    first, second = case.searches
    assert "dual" in first and "dual" not in second
    assert second["query"] == "a refinement" and ids(second["chunks"]) == list(range(11, 19))
    assert execution_summary(case)["search_count"] == 2


async def test_the_default_strategy_records_exactly_one_plain_search(
    stage: dict[str, Any], case: CaseTrace
) -> None:
    await recorder(dual=False).retrieve(request())
    (search,) = case.searches
    assert "dual" not in search and ids(search["chunks"]) == list(range(1, 9))


async def test_a_failed_supplemental_search_degrades_and_is_recorded_once(
    stage: dict[str, Any], case: CaseTrace
) -> None:
    stage["fail"][QUESTION] = ConnectionError("store down")
    found = await recorder().retrieve_dual(request(), QUESTION)
    assert [c.chunk_id.int for c in found.chunks] == list(range(1, 9))  # the model's list alone
    (search,) = case.searches
    assert ids(search["chunks"]) == list(range(1, 9))
    assert search["dual"]["degraded_reason"] == "original_question_search_failed:ConnectionError"
    assert "error" not in search


async def test_a_failed_model_search_is_recorded_and_still_raises(
    stage: dict[str, Any], case: CaseTrace
) -> None:
    stage["fail"][MODEL_QUERY] = ConnectionError("store down")
    with pytest.raises(ConnectionError):
        await recorder().retrieve_dual(request(), QUESTION)
    (search,) = case.searches
    assert search["error"] == "ConnectionError" and "chunks" not in search


async def test_identical_queries_search_once_and_record_the_skip(
    stage: dict[str, Any], case: CaseTrace
) -> None:
    await recorder().retrieve_dual(request(QUESTION), QUESTION)
    assert stage["calls"] == [QUESTION]
    (search,) = case.searches
    assert search["dual"]["strategy"] == "A" and search["dual"]["skipped_reason"]
    assert search["dual"]["retrieval_calls"] == 1


async def test_an_exact_file_scope_is_recorded_with_its_scope(
    stage: dict[str, Any], case: CaseTrace
) -> None:
    scoped = request(scope=ResolvedFileScope(file_ids=(uuid.UUID(int=5),)))
    await recorder().retrieve_dual(scoped, QUESTION)
    (search,) = case.searches
    assert (search["scope"], search["scope_files"]) == ("files", 1)


async def test_without_a_case_trace_the_dual_search_just_runs(stage: dict[str, Any]) -> None:
    trace_var.set(None)
    found = await recorder().retrieve_dual(request(), QUESTION)
    assert [c.chunk_id.int for c in found.chunks] == MERGED_IDS
