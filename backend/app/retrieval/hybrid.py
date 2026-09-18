"""Hybrid retrieval orchestration across vector, keyword, and metadata retrievers."""

from __future__ import annotations

import asyncio
from time import perf_counter

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.evaluation.trace import EvalTraceCollector, elapsed_ms
from app.retrieval.grade import EvidenceGrade, grade_evidence
from app.retrieval.keyword import KeywordRetriever
from app.retrieval.merge import reciprocal_rank_fusion_merge
from app.retrieval.metadata import MetadataRetriever
from app.retrieval.rerank import weighted_fusion_rerank
from app.retrieval.types import RetrievedChunk
from app.retrieval.vector import VectorRetriever


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

    async def retrieve(self, question: str) -> list[RetrievedChunk]:
        """Return reranked chunks that pass evidence grading."""
        evidence = await self.retrieve_with_grade(question)
        return evidence.chunks

    async def retrieve_with_grade(
        self,
        question: str,
        *,
        trace: EvalTraceCollector | None = None,
    ) -> EvidenceGrade:
        """Run hybrid retrieval pipeline and return graded evidence."""
        normalized = question.strip()
        if not normalized:
            return EvidenceGrade(
                sufficient=False,
                reason="Question is empty after normalization.",
                chunks=[],
            )

        if trace is None:
            vector_chunks, keyword_chunks, metadata_chunks = await asyncio.gather(
                self.vector_retriever.retrieve(normalized),
                self.keyword_retriever.retrieve(normalized),
                self.metadata_retriever.retrieve(normalized),
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
                    chunks = await retriever.retrieve(normalized)
                except Exception as exc:
                    trace.record_error(exc, stage="retrieval", component=name)
                    raise
                return chunks, elapsed_ms(started_at)

            try:
                vector_result, keyword_result, metadata_result = await asyncio.gather(
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
