"""Hybrid retrieval orchestration across vector, keyword, and metadata retrievers."""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
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

    async def retrieve_with_grade(self, question: str) -> EvidenceGrade:
        """Run hybrid retrieval pipeline and return graded evidence."""
        normalized = question.strip()
        if not normalized:
            return EvidenceGrade(
                sufficient=False,
                reason="Question is empty after normalization.",
                chunks=[],
            )

        vector_chunks, keyword_chunks, metadata_chunks = await asyncio.gather(
            self.vector_retriever.retrieve(normalized),
            self.keyword_retriever.retrieve(normalized),
            self.metadata_retriever.retrieve(normalized),
        )
        merged = reciprocal_rank_fusion_merge(
            {
                "vector": vector_chunks,
                "keyword": keyword_chunks,
                "metadata": metadata_chunks,
            },
            settings=self.settings,
        )
        reranked = weighted_fusion_rerank(
            merged,
            settings=self.settings,
            question=normalized,
        )
        return grade_evidence(reranked, settings=self.settings)
