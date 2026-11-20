"""Tests for hybrid retrieval orchestration."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.routing.intent_frame.execution import RetrievalRequest
from app.routing.intent_frame.scope import EligibleCollectionScope, ResolvedFileScope
from pydantic import ValidationError
from app.evaluation.trace import EvalTraceCollector
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.types import RetrievalSource, RetrievedChunk


USER_ID = uuid.uuid4()


def _chunk(*, score: float, source: RetrievalSource) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        drive_file_id=uuid.uuid4(),
        filename="doc.txt",
        mime_type="text/plain",
        modified_at=datetime.now(UTC),
        chunk_index=0,
        text="chunk text",
        score=score,
        primary_source=source,
        source_scores={source: score},
    )


@pytest.mark.asyncio
async def test_hybrid_retriever_runs_sources_and_returns_graded_chunks() -> None:
    vector = AsyncMock()
    keyword = AsyncMock()
    metadata = AsyncMock()
    vector.retrieve = AsyncMock(return_value=[_chunk(score=0.9, source="vector")])
    keyword.retrieve = AsyncMock(return_value=[_chunk(score=0.7, source="keyword")])
    metadata.retrieve = AsyncMock(return_value=[])

    retriever = HybridRetriever(
        db=AsyncMock(),
        settings=Settings(
            retrieval_candidate_k=8,
            retrieval_top_k=4,
            hybrid_rrf_k=20,
            hybrid_weight_vector=0.5,
            hybrid_weight_keyword=0.3,
            hybrid_weight_metadata=0.2,
            evidence_min_fusion_score=0.01,
            retrieval_score_threshold=0.35,
        ),
        vector_retriever=vector,
        keyword_retriever=keyword,
        metadata_retriever=metadata,
    )

    chunks = await retriever.retrieve(_request("latest pdf"))

    assert len(chunks) >= 1
    vector.retrieve.assert_awaited_once()
    keyword.retrieve.assert_awaited_once()
    metadata.retrieve.assert_awaited_once()


@pytest.mark.asyncio
async def test_hybrid_retriever_rejects_blank_request() -> None:
    retriever = HybridRetriever(
        db=AsyncMock(),
        settings=Settings(),
        vector_retriever=AsyncMock(),
        keyword_retriever=AsyncMock(),
        metadata_retriever=AsyncMock(),
    )
    with pytest.raises(ValidationError):
        await retriever.retrieve_with_grade(_request("   "))


@pytest.mark.asyncio
async def test_hybrid_retriever_retrieve_returns_empty_for_insufficient_evidence() -> None:
    vector = AsyncMock()
    keyword = AsyncMock()
    metadata = AsyncMock()
    vector.retrieve = AsyncMock(return_value=[_chunk(score=0.2, source="vector")])
    keyword.retrieve = AsyncMock(return_value=[])
    metadata.retrieve = AsyncMock(return_value=[])

    retriever = HybridRetriever(
        db=AsyncMock(),
        settings=Settings(
            retrieval_candidate_k=8,
            retrieval_top_k=4,
            hybrid_rrf_k=20,
            hybrid_weight_vector=0.5,
            hybrid_weight_keyword=0.3,
            hybrid_weight_metadata=0.2,
            evidence_min_fusion_score=0.9,
            retrieval_score_threshold=0.35,
        ),
        vector_retriever=vector,
        keyword_retriever=keyword,
        metadata_retriever=metadata,
    )

    chunks = await retriever.retrieve(_request("latest pdf"))
    assert chunks == []


@pytest.mark.asyncio
async def test_hybrid_retriever_returns_grade_reason() -> None:
    vector = AsyncMock()
    keyword = AsyncMock()
    metadata = AsyncMock()
    vector.retrieve = AsyncMock(return_value=[])
    keyword.retrieve = AsyncMock(return_value=[])
    metadata.retrieve = AsyncMock(return_value=[])

    retriever = HybridRetriever(
        db=AsyncMock(),
        settings=Settings(),
        vector_retriever=vector,
        keyword_retriever=keyword,
        metadata_retriever=metadata,
    )
    evidence = await retriever.retrieve_with_grade(_request("latest file"))
    assert evidence.sufficient is False
    assert "No retrieval evidence" in evidence.reason


@pytest.mark.asyncio
async def test_hybrid_trace_preserves_raw_fusion_rerank_and_grade() -> None:
    shared = _chunk(score=0.9, source="vector")
    keyword_copy = RetrievedChunk(
        chunk_id=shared.chunk_id,
        document_id=shared.document_id,
        drive_file_id=shared.drive_file_id,
        filename=shared.filename,
        mime_type=shared.mime_type,
        modified_at=shared.modified_at,
        chunk_index=shared.chunk_index,
        text=shared.text,
        score=0.4,
        primary_source="keyword",
        source_scores={"keyword": 0.4},
    )
    keyword_only = _chunk(score=0.8, source="keyword")
    vector = AsyncMock()
    keyword = AsyncMock()
    metadata = AsyncMock()
    vector.retrieve = AsyncMock(return_value=[shared])
    keyword.retrieve = AsyncMock(return_value=[keyword_only, keyword_copy])
    metadata.retrieve = AsyncMock(return_value=[])
    settings = Settings(
        retrieval_candidate_k=8,
        retrieval_top_k=4,
        hybrid_rrf_k=20,
        evidence_min_fusion_score=0.01,
        retrieval_score_threshold=0.1,
    )
    retriever = HybridRetriever(
        db=AsyncMock(),
        settings=settings,
        vector_retriever=vector,
        keyword_retriever=keyword,
        metadata_retriever=metadata,
    )
    trace = EvalTraceCollector()
    trace.start("topic")

    evidence = await retriever.retrieve_with_grade(_request("topic"), trace=trace)

    attempt = trace.trace.attempts[0]
    assert [result.retriever for result in attempt.retriever_results] == [
        "vector",
        "keyword",
        "metadata",
    ]
    assert [candidate.chunk_id for candidate in attempt.retriever_results[0].candidates] == [
        shared.chunk_id
    ]
    assert [candidate.chunk_id for candidate in attempt.retriever_results[1].candidates] == [
        keyword_only.chunk_id,
        shared.chunk_id,
    ]
    assert attempt.merged_candidates
    assert attempt.reranked_candidates
    assert attempt.merged_candidates[0].score != attempt.reranked_candidates[0].score
    assert attempt.evidence is not None
    assert attempt.evidence.sufficient is evidence.sufficient
    assert attempt.duration_ms is not None


@pytest.mark.asyncio
async def test_hybrid_without_trace_does_not_build_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vector = AsyncMock()
    keyword = AsyncMock()
    metadata = AsyncMock()
    vector.retrieve = AsyncMock(return_value=[])
    keyword.retrieve = AsyncMock(return_value=[])
    metadata.retrieve = AsyncMock(return_value=[])
    retriever = HybridRetriever(
        db=AsyncMock(),
        vector_retriever=vector,
        keyword_retriever=keyword,
        metadata_retriever=metadata,
    )

    def fail_snapshot(*args: object, **kwargs: object) -> object:
        raise AssertionError("snapshot creation must be trace-only")

    monkeypatch.setattr("app.evaluation.trace.snapshot_candidates", fail_snapshot)

    evidence = await retriever.retrieve_with_grade(_request("topic"))

    assert evidence.sufficient is False


def _request(query: str) -> RetrievalRequest:
    return RetrievalRequest(
        user_id=USER_ID,
        query=query,
        scope=EligibleCollectionScope(),
        candidate_limit=8,
        candidate_policy="LEGACY",
    )


# ---- per-file limit: applied for open searches, skipped when the user chose the file(s) -------------


def _file_chunk(
    file_id: uuid.UUID, index: int, score: float, name: str = "doc.txt"
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        drive_file_id=file_id,
        filename=name,
        mime_type="text/plain",
        modified_at=datetime.now(UTC),
        chunk_index=index,
        text="chunk text",
        score=score,
        primary_source="vector",
        source_scores={"vector": score},
    )


def _limit_retriever(max_per_file: int) -> tuple[HybridRetriever, uuid.UUID, uuid.UUID]:
    long_file, short_file = uuid.uuid4(), uuid.uuid4()
    vector = AsyncMock()
    vector.retrieve = AsyncMock(
        return_value=[_file_chunk(long_file, i, 0.9 - i / 50, "long.pdf") for i in range(6)]
        + [_file_chunk(short_file, 0, 0.6, "short.txt")]
    )
    empty = AsyncMock()
    empty.retrieve = AsyncMock(return_value=[])
    retriever = HybridRetriever(
        db=AsyncMock(),
        settings=Settings(
            retrieval_top_k=3,
            retrieval_max_chunks_per_file=max_per_file,
            evidence_min_fusion_score=0.01,
        ),
        vector_retriever=vector,
        keyword_retriever=empty,
        metadata_retriever=empty,
    )
    return retriever, long_file, short_file


def _scoped(query: str, scope) -> RetrievalRequest:
    return RetrievalRequest(user_id=USER_ID, query=query, scope=scope, candidate_limit=20)


@pytest.mark.asyncio
async def test_open_search_limits_chunks_per_file_so_another_file_gets_a_slot() -> None:
    retriever, long_file, short_file = _limit_retriever(max_per_file=2)
    chunks = await retriever.retrieve(
        _scoped("how do we handle incidents", EligibleCollectionScope())
    )
    assert sum(c.drive_file_id == long_file for c in chunks) == 2
    assert any(c.drive_file_id == short_file for c in chunks)


@pytest.mark.asyncio
async def test_limit_is_off_when_the_setting_is_zero() -> None:
    retriever, long_file, _ = _limit_retriever(max_per_file=0)
    chunks = await retriever.retrieve(
        _scoped("how do we handle incidents", EligibleCollectionScope())
    )
    assert [c.drive_file_id for c in chunks] == [long_file] * 3


@pytest.mark.asyncio
async def test_no_limit_when_the_search_is_restricted_to_chosen_files() -> None:
    retriever, long_file, _ = _limit_retriever(max_per_file=2)
    scope = ResolvedFileScope(file_ids=(long_file,))
    chunks = await retriever.retrieve(_scoped("summarise this", scope))
    assert [c.drive_file_id for c in chunks] == [long_file] * 3


@pytest.mark.asyncio
async def test_no_limit_when_the_question_names_a_file() -> None:
    retriever, long_file, _ = _limit_retriever(max_per_file=2)
    chunks = await retriever.retrieve(
        _scoped('what does "long.pdf" say about incidents', EligibleCollectionScope())
    )
    assert sum(c.drive_file_id == long_file for c in chunks) == 3
