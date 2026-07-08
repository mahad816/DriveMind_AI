"""LangGraph node implementations for the DriveMind agent workflow."""

from __future__ import annotations

import asyncio
import json
import re
import uuid as uuid_module
from typing import Any, Awaitable, Callable, cast

from openai import APIError, AsyncOpenAI

from app.agents.drive_graph.state import DriveGraphState
from app.agents.drive_graph.types import QueryIntent, RetrievalPlan, RetrieverName
from app.core.config import Settings
from app.agents.drive_graph.prompts import REWRITE_QUERY_SYSTEM_PROMPT
from app.llm.base import ChatService
from app.llm.factory import get_chat_service
from app.llm.prompts import NO_EVIDENCE_ANSWER, filter_citations_to_answer
from app.llm.prompts import format_citation_snippet, select_prompt_chunks
from app.retrieval.base import Retriever
from app.retrieval.grade import grade_evidence as grade_retrieval_evidence
from app.retrieval.merge import reciprocal_rank_fusion_merge
from app.retrieval.rerank import weighted_fusion_rerank
from app.retrieval.types import RetrievedChunk, RetrievalSource
from app.schemas.query import CitationItem


def receive_question(state: DriveGraphState) -> dict[str, Any]:
    """Normalize question text and reset core state for a new run."""
    normalized = state["question"].strip()
    if not normalized:
        raise ValueError("Question must not be empty")

    return {
        "question": normalized,
        "working_query": normalized,
        "rewrite_count": 0,
        "raw_chunks": [],
        "ranked_chunks": [],
        "citations": [],
        "retrieval_count": 0,
    }


def classify_intent(state: DriveGraphState) -> dict[str, Any]:
    """Classify query intent using deterministic heuristic rules."""
    intent = classify_intent_heuristic(state["working_query"])
    return {"intent": intent}


def plan_retrieval(state: DriveGraphState) -> dict[str, Any]:
    """Build a retrieval plan from the selected intent."""
    intent = state.get("intent")
    if intent is None:
        raise ValueError("intent must be set before plan_retrieval")
    plan = build_retrieval_plan(intent)
    return {"retrieval_plan": plan}


def route_retriever(state: DriveGraphState) -> dict[str, Any]:
    """Expose active retrievers from the retrieval plan."""
    plan = state.get("retrieval_plan")
    if plan is None:
        raise ValueError("retrieval_plan must be set before route_retriever")
    return {"active_retrievers": plan.retrievers}


def retrieve(state: DriveGraphState) -> dict[str, Any]:
    """Retrieve raw evidence chunks (stubbed: no DB/Qdrant calls in M2)."""
    return {
        "raw_chunks": [],
        "ranked_chunks": [],
        "retrieval_count": 0,
    }


def make_retrieve_node(
    *,
    retrievers: dict[RetrieverName, Retriever],
    settings: Settings,
) -> Callable[[DriveGraphState], Awaitable[dict[str, Any]]]:
    """Create a routed retrieval node using only active retrievers.

    The closure keeps node functions testable without relying on global state.
    """

    async def _retrieve(state: DriveGraphState) -> dict[str, Any]:
        active = state.get("active_retrievers")
        if not active:
            return {"raw_chunks": [], "ranked_chunks": [], "retrieval_count": 0}

        working_query = state["working_query"]

        tasks: list[Awaitable[list[RetrievedChunk]]] = []
        source_order: list[RetrieverName] = []
        for raw_name in active:
            if raw_name not in {"vector", "keyword", "metadata"}:
                raise ValueError(f"Unsupported active retriever name: {raw_name}")
            name = cast(RetrieverName, raw_name)

            retriever = retrievers.get(name)
            if retriever is None:
                raise ValueError(f"Missing retriever for active name: {name}")
            tasks.append(retriever.retrieve(working_query))
            source_order.append(name)

        results = await asyncio.gather(*tasks)
        chunks_by_source: dict[RetrievalSource, list[RetrievedChunk]] = {
            cast(RetrievalSource, name): chunks for name, chunks in zip(source_order, results)
        }
        merged = reciprocal_rank_fusion_merge(chunks_by_source, settings=settings)

        return {
            "raw_chunks": merged,
            "ranked_chunks": [],
            "retrieval_count": len(merged),
        }

    return _retrieve


def make_rerank_node(*, settings: Settings) -> Callable[[DriveGraphState], dict[str, Any]]:
    """Create a rerank node that applies weighted fusion to merged candidates."""

    def _rerank(state: DriveGraphState) -> dict[str, Any]:
        ranked = weighted_fusion_rerank(
            state["raw_chunks"],
            settings=settings,
            question=state["question"],
        )
        return {"ranked_chunks": ranked}

    return _rerank


def make_grade_evidence_node(
    *,
    settings: Settings,
) -> Callable[[DriveGraphState], dict[str, Any]]:
    """Create an evidence grading node using Phase 7 threshold rules."""

    def _grade_evidence(state: DriveGraphState) -> dict[str, Any]:
        grade = grade_retrieval_evidence(state["ranked_chunks"], settings=settings)
        return {
            "evidence_sufficient": grade.sufficient,
            "evidence_reason": grade.reason,
            "ranked_chunks": grade.chunks,
            "retrieval_count": len(grade.chunks),
        }

    return _grade_evidence


async def rewrite_query(state: DriveGraphState) -> dict[str, Any]:
    """Rewrite query fallback node used by default graph."""
    next_count = state["rewrite_count"] + 1
    refined = _heuristic_rewrite_query(
        question=state["question"],
        working_query=state["working_query"],
        evidence_reason=state.get("evidence_reason", ""),
    )
    return {"working_query": refined, "rewrite_count": next_count}


def make_rewrite_query_node(
    *,
    settings: Settings,
    rewrite_fn: Callable[[str, str, str], Awaitable[str]] | None = None,
) -> Callable[[DriveGraphState], Awaitable[dict[str, Any]]]:
    """Create rewrite node with injectable LLM-backed or custom rewriter."""

    async def _rewrite_query(state: DriveGraphState) -> dict[str, Any]:
        next_count = state["rewrite_count"] + 1
        question = state["question"]
        working_query = state["working_query"]
        reason = state.get("evidence_reason", "")

        rewritten: str | None = None
        if rewrite_fn is not None:
            rewritten = await rewrite_fn(question, working_query, reason)
        elif settings.openai_api_key:
            rewritten = await _rewrite_with_openai(
                settings=settings,
                question=question,
                working_query=working_query,
                evidence_reason=reason,
            )

        if not rewritten or not rewritten.strip():
            rewritten = _heuristic_rewrite_query(
                question=question,
                working_query=working_query,
                evidence_reason=reason,
            )
        else:
            rewritten = rewritten.strip()

        if rewritten == working_query:
            rewritten = _heuristic_rewrite_query(
                question=question,
                working_query=working_query,
                evidence_reason=reason,
            )

        return {"working_query": rewritten, "rewrite_count": next_count}

    return _rewrite_query


def make_generate_answer_node(
    *,
    settings: Settings,
    chat_service: ChatService | None = None,
) -> Callable[[DriveGraphState], Awaitable[dict[str, Any]]]:
    """Create grounded answer generation node with citation construction."""
    service = chat_service or get_chat_service(settings)

    async def _generate_answer(state: DriveGraphState) -> dict[str, Any]:
        ranked = state["ranked_chunks"]
        question = state["question"]
        if not ranked:
            return {"answer": NO_EVIDENCE_ANSWER, "citations": []}

        answer = await service.generate_grounded_answer(
            question,
            ranked,
            max_context_chars=settings.rag_max_context_chars,
        )
        prompt_chunks = select_prompt_chunks(
            question,
            ranked,
            max_context_chars=settings.rag_max_context_chars,
        )
        all_citations = [build_citation(chunk) for chunk in prompt_chunks]
        # Only include citations the LLM actually referenced with [N] markers.
        citations = cast(
            list[CitationItem],
            filter_citations_to_answer(answer, all_citations),  # type: ignore[arg-type]
        )
        return {"answer": answer, "citations": citations}

    return _generate_answer


def verify_citations(state: DriveGraphState) -> dict[str, Any]:
    """Remove invalid citation references and align citation payload."""
    answer = state.get("answer", "")
    citations = state.get("citations", [])
    if not answer or not citations:
        return {}

    refs = [int(match) for match in re.findall(r"\[(\d+)\]", answer)]
    if not refs:
        # No bracket references in the answer — clear all citations so the UI
        # does not show irrelevant source pills (e.g. for chitchat responses).
        return {"citations": []}

    valid_indices = {index for index in refs if 1 <= index <= len(citations)}
    invalid_indices = {index for index in refs if index < 1 or index > len(citations)}

    sanitized_answer = answer
    for invalid in sorted(invalid_indices, reverse=True):
        sanitized_answer = re.sub(rf"\[{invalid}\]", "", sanitized_answer)
    sanitized_answer = re.sub(r"\s{2,}", " ", sanitized_answer).strip()

    if not valid_indices:
        return {"answer": sanitized_answer, "citations": []}

    ordered_valid = sorted(valid_indices)
    selected_citations = [citations[index - 1] for index in ordered_valid]
    old_to_new = {old: new for new, old in enumerate(ordered_valid, start=1)}

    normalized_answer = sanitized_answer
    for old_index, new_index in old_to_new.items():
        if old_index != new_index:
            normalized_answer = re.sub(rf"\[{old_index}\]", f"[{new_index}]", normalized_answer)

    return {"answer": normalized_answer, "citations": selected_citations}


def return_response(state: DriveGraphState) -> dict[str, Any]:
    """Finalize response envelope values used by the graph runner."""
    citations = state.get("citations", [])
    return {
        "query_id": uuid_module.uuid4(),
        "retrieval_count": len(citations) or state["retrieval_count"],
    }


def classify_intent_heuristic(question: str) -> QueryIntent:
    """Classify query intent using lightweight deterministic rules.

    This keeps M3 reliable and testable. LLM-assisted fallback can be layered in M4+.

    Priority order (highest to lowest):
    1. LIST_OR_FILTER with inventory domain term  — count/all/list + resume/cv/…
    2. FIND_LATEST                                 — latest/recent/newest
    3. SUMMARIZE_TOPIC
    4. LIST_OR_FILTER (generic file listing)
    5. KEYWORD_SEARCH
    6. SEMANTIC_QUESTION
    7. UNKNOWN
    """
    normalized = question.strip().lower()
    if not normalized:
        return QueryIntent.UNKNOWN

    # LIST_OR_FILTER takes priority over FIND_LATEST when the user is asking
    # for an enumeration or count of a specific file type (e.g. "find all resume
    # files, how many", "list every CV").  Bare "find" is intentionally excluded
    # so that "Find my latest resume" still resolves to FIND_LATEST.
    _has_list_signal = re.search(
        r"\b(how many|count|total|all|every|each|list)\b",
        normalized,
    )
    _has_inventory_domain = re.search(
        r"\b(resume|resumes|cv|cvs|certificate|certificates|"
        r"certification|certifications|transcript|transcripts|"
        r"thesis|dissertation)\b",
        normalized,
    )
    if _has_list_signal and _has_inventory_domain:
        return QueryIntent.LIST_OR_FILTER

    if re.search(r"\b(latest|recent|newest)\b", normalized):
        return QueryIntent.FIND_LATEST

    if re.search(r"\b(summarize|summary|overview)\b", normalized):
        return QueryIntent.SUMMARIZE_TOPIC

    if re.search(r"\b(list|show|filter|only)\b", normalized) and re.search(
        r"\b(files?|docs?|documents?|pdf|docx|txt|folder)\b",
        normalized,
    ):
        return QueryIntent.LIST_OR_FILTER

    if re.search(r"\b(mention|mentions|mentioning|contains|exact|keyword|phrase)\b", normalized):
        return QueryIntent.KEYWORD_SEARCH

    if re.search(r"\b(what|why|how|explain|tell me)\b", normalized):
        return QueryIntent.SEMANTIC_QUESTION

    return QueryIntent.UNKNOWN


def build_retrieval_plan(intent: QueryIntent) -> RetrievalPlan:
    """Map intent to retriever strategy for later nodes."""
    if intent is QueryIntent.FIND_LATEST:
        return RetrievalPlan(
            intent=intent,
            retrievers=("metadata", "keyword"),
            sort_by_modified_desc=True,
        )

    if intent is QueryIntent.KEYWORD_SEARCH:
        return RetrievalPlan(intent=intent, retrievers=("keyword", "vector"))

    if intent is QueryIntent.SEMANTIC_QUESTION:
        return RetrievalPlan(intent=intent, retrievers=("vector", "keyword"))

    if intent is QueryIntent.SUMMARIZE_TOPIC:
        return RetrievalPlan(intent=intent, retrievers=("vector", "keyword", "metadata"))

    if intent is QueryIntent.LIST_OR_FILTER:
        return RetrievalPlan(intent=intent, retrievers=("metadata",))

    return RetrievalPlan(intent=QueryIntent.UNKNOWN, retrievers=("vector", "keyword", "metadata"))


def _heuristic_rewrite_query(*, question: str, working_query: str, evidence_reason: str) -> str:
    """Fallback query rewrite when no LLM rewriter is available."""
    base = working_query.strip() or question.strip()
    if not base:
        return "refined query"
    if "exact terms" in base:
        return base
    if "keyword evidence is absent" in evidence_reason.lower():
        return f"{base} with exact terms and filenames"
    if "below minimum threshold" in evidence_reason.lower():
        return f"{base} with more specific document keywords"
    return f"{base} with precise keywords"


async def _rewrite_with_openai(
    *,
    settings: Settings,
    question: str,
    working_query: str,
    evidence_reason: str,
) -> str | None:
    """Use chat completion model to generate an improved retrieval query."""
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    user_prompt = (
        "Original question:\n"
        f"{question}\n\n"
        "Current retrieval query:\n"
        f"{working_query}\n\n"
        "Evidence grade reason:\n"
        f"{evidence_reason or 'No reason provided'}\n\n"
        'Return JSON only: {"rewritten_query":"..."}'
    )

    try:
        response = await client.chat.completions.create(
            model=settings.chat_model,
            messages=[
                {"role": "system", "content": REWRITE_QUERY_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
        )
    except APIError:
        return None

    choice = response.choices[0] if response.choices else None
    content = choice.message.content if choice and choice.message else None
    if not content:
        return None
    return _extract_rewritten_query(content)


def _extract_rewritten_query(content: str) -> str | None:
    """Extract rewritten_query from JSON-like LLM output."""
    text = content.strip()
    try:
        parsed = json.loads(text)
        value = parsed.get("rewritten_query")
        return value.strip() if isinstance(value, str) and value.strip() else None
    except json.JSONDecodeError:
        # Fallback: attempt to capture JSON object inside surrounding text.
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < 0 or end <= start:
            return None
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
        value = parsed.get("rewritten_query")
        return value.strip() if isinstance(value, str) and value.strip() else None


def build_citation(chunk: RetrievedChunk) -> CitationItem:
    """Create API citation payload from retrieved chunk."""
    snippet = format_citation_snippet(chunk.text)
    if not snippet:
        snippet = chunk.filename
    return CitationItem(
        chunk_id=chunk.chunk_id,
        drive_file_id=chunk.drive_file_id,
        filename=chunk.filename,
        snippet=snippet,
        score=chunk.score,
    )
