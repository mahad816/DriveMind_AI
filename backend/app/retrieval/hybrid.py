"""Hybrid retrieval orchestration across vector, keyword, and metadata retrievers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import perf_counter
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.evaluation.trace import EvalTraceCollector, elapsed_ms
from app.retrieval.filename_targets import extract_filename_targets
from app.retrieval.grade import EvidenceGrade, grade_evidence
from app.retrieval.keyword import KeywordRetriever
from app.retrieval.merge import reciprocal_rank_fusion_merge
from app.retrieval.metadata import MetadataRetriever
from app.retrieval.rerank import weighted_fusion_rerank
from app.retrieval.owned import gather_owned
from app.retrieval.round_robin import round_robin_merge
from app.retrieval.types import RetrievedChunk
from app.retrieval.scope import require_request
from app.routing.intent_frame.execution import RetrievalRequest
from app.routing.intent_frame.scope import ResolvedFileScope
from app.retrieval.vector import VectorRetriever


@dataclass(frozen=True)
class DualRetrieval:
    """Outcome of ``HybridRetriever.retrieve_dual``: the chunks plus how they were found (no query text, no content).

    ``original_chunks`` and ``model_chunks`` are the two lists after the normal pipeline and evidence grading
    (empty when that search found no sufficient evidence or failed); ``model_chunks`` is exactly what the
    single-query strategy returns for the model's query.
    """

    chunks: list[RetrievedChunk]
    original_chunks: list[RetrievedChunk]
    model_chunks: list[RetrievedChunk]
    strategy: Literal["A", "C2"]
    degraded_reason: str | None
    skipped_reason: str | None
    retrieval_calls: int
    embedding_calls: int  # one per search: the vector retriever embeds each non-blank query once
    latency_ms: float
    overlap: int  # chunks present in both lists


class HybridRetriever:
    """Run retrieval strategies in parallel and return graded evidence."""

    def __init__(
        self,
        db: AsyncSession,
        settings: Settings | None = None,
        *,
        vector_retriever: VectorRetriever | None = None,
        keyword_retriever: KeywordRetriever | None = None,
        metadata_retriever: MetadataRetriever | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.vector_retriever = vector_retriever or VectorRetriever(db, self.settings)
        self.keyword_retriever = keyword_retriever or KeywordRetriever(db, self.settings)
        self.metadata_retriever = metadata_retriever or MetadataRetriever(db, self.settings)

    async def retrieve(self, request: RetrievalRequest) -> list[RetrievedChunk]:
        """Return reranked chunks that pass evidence grading."""
        evidence = await self.retrieve_with_grade(request)
        return evidence.chunks

    def _max_chunks_per_file(self, request: RetrievalRequest, question: str) -> int:
        """No per-file limit when the user already chose the file(s): then many chunks of one file
        is exactly what they want."""
        if isinstance(request.scope, ResolvedFileScope) or extract_filename_targets(question):
            return 0
        return self.settings.retrieval_max_chunks_per_file

    async def retrieve_with_grade(
        self,
        request: RetrievalRequest,
        *,
        trace: EvalTraceCollector | None = None,
    ) -> EvidenceGrade:
        """Run hybrid retrieval pipeline and return graded evidence."""
        require_request(request)
        normalized = request.query.strip()
        retrieval_input = request
        if not normalized:
            return EvidenceGrade(
                sufficient=False,
                reason="Question is empty after normalization.",
                chunks=[],
            )

        if trace is None:
            vector_chunks, keyword_chunks, metadata_chunks = await gather_owned(
                self.vector_retriever.retrieve(retrieval_input),
                self.keyword_retriever.retrieve(retrieval_input),
                self.metadata_retriever.retrieve(retrieval_input),
            )
        else:
            attempt_number = 1
            trace.begin_attempt(
                attempt_number=attempt_number,
                working_query=normalized,
                active_retrievers=("vector", "keyword", "metadata"),
            )

            async def timed_retrieve(
                name: str,
                retriever: VectorRetriever | KeywordRetriever | MetadataRetriever,
            ) -> tuple[list[RetrievedChunk], float]:
                started_at = perf_counter()
                try:
                    chunks = await retriever.retrieve(retrieval_input)
                except Exception as exc:
                    trace.record_error(exc, stage="retrieval", component=name)
                    raise
                return chunks, elapsed_ms(started_at)

            try:
                vector_result, keyword_result, metadata_result = await gather_owned(
                    timed_retrieve("vector", self.vector_retriever),
                    timed_retrieve("keyword", self.keyword_retriever),
                    timed_retrieve("metadata", self.metadata_retriever),
                )
            except Exception:
                trace.finish_attempt(attempt_number)
                raise

            vector_chunks, vector_ms = vector_result
            keyword_chunks, keyword_ms = keyword_result
            metadata_chunks, metadata_ms = metadata_result
            trace.record_retriever_result(attempt_number, "vector", vector_chunks, vector_ms)
            trace.record_retriever_result(attempt_number, "keyword", keyword_chunks, keyword_ms)
            trace.record_retriever_result(attempt_number, "metadata", metadata_chunks, metadata_ms)
            trace.set_stage("fusion")
        merged = reciprocal_rank_fusion_merge(
            {
                "vector": vector_chunks,
                "keyword": keyword_chunks,
                "metadata": metadata_chunks,
            },
            settings=self.settings,
        )
        if trace is not None:
            trace.record_merged(1, merged)
            trace.set_stage("reranking")
        reranked = weighted_fusion_rerank(
            merged,
            settings=self.settings,
            question=normalized,
            max_per_file=self._max_chunks_per_file(request, normalized),
        )
        if trace is not None:
            trace.record_reranked(1, reranked)
            trace.set_stage("evidence_grading")
        evidence = grade_evidence(reranked, settings=self.settings)
        if trace is not None:
            trace.record_evidence(
                1,
                sufficient=evidence.sufficient,
                reason=evidence.reason,
                chunks=evidence.chunks,
            )
            trace.finish_attempt(1)
        return evidence

    async def retrieve_dual(
        self, request: RetrievalRequest, original_question: str
    ) -> DualRetrieval:
        """C2: search the model's query (``request``) and the user's own question, then round-robin the two lists.

        The question search is the same request with only the query text replaced, so user, scope, candidate
        limit and policy cannot differ, and each search runs the full pipeline (fusion, rerank, evidence grading)
        on its own database sessions (each retriever opens one). The model-query search is primary: its failure is
        raised as in the single-query strategy. A failed question search keeps the model's results and is recorded
        as ``degraded_reason`` (exception class only). Identical queries, after ``strip``, search once.
        """
        started = perf_counter()
        original_query = original_question.strip()
        skipped: str | None = None
        if not original_query:
            skipped = "blank_original_question"
        elif original_query == request.query.strip():
            skipped = "identical_queries"
        if skipped is not None:
            grade = await self.retrieve_with_grade(request)
            return DualRetrieval(
                chunks=grade.chunks,
                original_chunks=[],
                model_chunks=grade.chunks,
                strategy="A",
                degraded_reason=None,
                skipped_reason=skipped,
                retrieval_calls=1,
                embedding_calls=1,
                latency_ms=elapsed_ms(started),
                overlap=0,
            )

        original_request = RetrievalRequest(
            user_id=request.user_id,
            query=original_query,
            scope=request.scope,
            candidate_limit=request.candidate_limit,
            candidate_policy=request.candidate_policy,
        )
        model_task = asyncio.ensure_future(self.retrieve_with_grade(request))
        original_task = asyncio.ensure_future(self.retrieve_with_grade(original_request))
        degraded: str | None = None
        original_chunks: list[RetrievedChunk] = []
        try:
            model_chunks = (await model_task).chunks
            try:
                original_chunks = (await original_task).chunks
            except Exception as exc:  # cancellation is a BaseException and passes through
                degraded = f"original_question_search_failed:{type(exc).__name__}"
        finally:
            for task in (model_task, original_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(model_task, original_task, return_exceptions=True)

        merged = round_robin_merge(
            original_chunks, model_chunks, limit=self.settings.retrieval_top_k
        )
        model_ids = {chunk.chunk_id for chunk in model_chunks}
        return DualRetrieval(
            chunks=merged,
            original_chunks=original_chunks,
            model_chunks=model_chunks,
            strategy="C2",
            degraded_reason=degraded,
            skipped_reason=None,
            retrieval_calls=2,
            embedding_calls=2,
            latency_ms=elapsed_ms(started),
            overlap=sum(1 for chunk in original_chunks if chunk.chunk_id in model_ids),
        )
