"""OpenAI chat completion provider for grounded RAG answers."""

from __future__ import annotations

import json
import re

from openai import APIError, AsyncOpenAI, omit

from app.core.config import Settings, get_settings
from app.llm.base import ChatConfigurationError, ChatError
from app.llm.prompts import (
    CHITCHAT_SYSTEM_PROMPT,
    COLLECTION_SYSTEM_PROMPT,
    FOLLOWUP_REWRITE_SYSTEM_PROMPT,
    DEMO_CHITCHAT_SYSTEM_PROMPT,
    FILE_INFORMATION_UNAVAILABLE,
    INFORMATION_UNAVAILABLE,
    normalize_answer_citations,
    select_prompt_chunks,
    FILE_INVENTORY_SYSTEM_PROMPT,
    FILE_TARGET_SYSTEM_PROMPT,
    RAG_SYSTEM_PROMPT,
    build_grounded_user_message,
    build_inventory_user_message,
)
from app.retrieval.types import RetrievedChunk
from app.retrieval.relationships import select_relationship_evidence

DEFAULT_CHAT_MODEL = "gpt-4o-mini"


class OpenAIChatService:
    """Generate grounded answers via the OpenAI chat completions API."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client

    @property
    def model_name(self) -> str:
        return self.settings.chat_model or DEFAULT_CHAT_MODEL

    def _get_client(self) -> AsyncOpenAI:
        if self._client is not None:
            return self._client
        if not self.settings.openai_api_key:
            raise ChatConfigurationError("OPENAI_API_KEY is not configured")
        return AsyncOpenAI(api_key=self.settings.openai_api_key)

    async def _complete(
        self, system_prompt: str, user_message: str, *, json_output: bool = False
    ) -> str:
        """Shared completion helper — one system + one user message."""
        client = self._get_client()
        try:
            response = await client.chat.completions.create(
                model=self.model_name,
                temperature=0,
                response_format={"type": "json_object"} if json_output else omit,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
            )
        except APIError as exc:
            raise ChatError(f"OpenAI chat request failed: {exc}") from exc

        choice = response.choices[0] if response.choices else None
        content = (
            choice.message.content if choice is not None and choice.message is not None else None
        )
        if not content or not content.strip():
            raise ChatError("OpenAI chat request returned an empty answer")
        return content.strip()

    async def generate_grounded_answer(
        self,
        question: str,
        chunks: list[RetrievedChunk],
        *,
        max_context_chars: int,
    ) -> str:
        """Generate a grounded answer from retrieved chunk context."""
        user_message = build_grounded_user_message(
            question,
            chunks,
            max_context_chars=max_context_chars,
        )
        selected = select_prompt_chunks(question, chunks, max_context_chars=max_context_chars)
        return await self._generate_with_evidence(
            RAG_SYSTEM_PROMPT, question, user_message, selected
        )

    async def generate_direct_answer(self, question: str) -> str:
        """Generate a direct conversational reply without file context.

        Used for chitchat messages like greetings and social exchanges.
        No citations are produced for this path.
        """
        prompt = DEMO_CHITCHAT_SYSTEM_PROMPT if self.settings.demo_mode else CHITCHAT_SYSTEM_PROMPT
        return await self._complete(prompt, question.strip())

    async def generate_inventory_answer(
        self,
        question: str,
        inventory_context: str,
    ) -> str:
        """Answer a file-inventory question from a structured file list context.

        ``inventory_context`` must be produced by ``build_inventory_context()``.
        No chunk citations are produced for this path.
        """
        user_message = build_inventory_user_message(question, inventory_context)
        return await self._complete(FILE_INVENTORY_SYSTEM_PROMPT, user_message)

    async def generate_file_target_answer(
        self,
        question: str,
        chunks: list[RetrievedChunk],
        *,
        max_context_chars: int,
    ) -> str:
        """Answer a question about one specific file using its full indexed content."""
        user_message = build_grounded_user_message(
            question,
            chunks,
            max_context_chars=max_context_chars,
        )
        selected = select_prompt_chunks(question, chunks, max_context_chars=max_context_chars)
        return await self._generate_with_evidence(
            FILE_TARGET_SYSTEM_PROMPT, question, user_message, selected
        )

    async def generate_collection_answer(
        self, question: str, chunks: list[RetrievedChunk], *, max_context_chars: int
    ) -> str:
        message = build_grounded_user_message(question, chunks, max_context_chars=max_context_chars)
        selected = select_prompt_chunks(question, chunks, max_context_chars=max_context_chars)
        return await self._generate_cited_answer(COLLECTION_SYSTEM_PROMPT, message, selected)

    async def _generate_with_evidence(
        self, prompt: str, question: str, message: str, selected: list[RetrievedChunk]
    ) -> str:
        evidence = select_relationship_evidence(question, selected)
        if evidence is None:
            return await self._generate_cited_answer(prompt, message, selected)
        if not evidence.passages:
            return evidence.limitation
        blocks = [
            f"[{index}] {selected[index - 1].filename}\n{text}"
            for index, text in evidence.passages.items()
        ]
        message = f"Question:\n{evidence.question}\n\nContext:\n" + "\n\n".join(blocks)
        answer = await self._generate_cited_answer(
            prompt, message, selected, allowed_indices=set(evidence.passages)
        )
        return answer + ("\n\n" + evidence.limitation if evidence.limitation else "")

    async def _generate_cited_answer(
        self,
        prompt: str,
        message: str,
        selected: list[RetrievedChunk],
        *,
        allowed_indices: set[int] | None = None,
    ) -> str:
        """Existing citation contract, shared by named files and bounded collections."""
        answer = await self._complete(prompt, message)
        for attempt in range(2):
            _, cited = normalize_answer_citations(answer, selected)
            markers = {int(index) for index in re.findall(r"\[(\d+)\]", answer)}
            if (cited and (allowed_indices is None or markers <= allowed_indices)) or answer in (
                FILE_INFORMATION_UNAVAILABLE,
                INFORMATION_UNAVAILABLE,
            ):
                return answer
            if attempt == 0:
                answer = await self._complete(
                    prompt,
                    message
                    + "\n\nRegenerate your answer: the previous draft omitted valid source citations. "
                    "Use [N] markers for supported claims. Recheck every date against the source. "
                    "Return only the corrected answer.",
                )
        raise ChatError("The answer could not be verified with source citations")

    async def rewrite_followup(self, question: str, history: list[dict[str, str]]) -> str:
        message = json.dumps({"question": question, "recent_conversation": history})
        for attempt in range(2):
            raw = await self._complete(FOLLOWUP_REWRITE_SYSTEM_PROMPT, message, json_output=True)
            try:
                data = json.loads(raw)
                rewritten = data.get("question")
                if (
                    data.get("needs_context") is True
                    and isinstance(rewritten, str)
                    and 0 < len(rewritten.strip()) <= 1600
                ):
                    if rewritten.strip().casefold() != question.strip().casefold():
                        return rewritten.strip()
                    if attempt == 0:
                        message += (
                            "\nThe previous output said context was needed but copied the question. "
                            "Replace its references with concrete antecedents, preserving all "
                            "members of a referenced set and the requested operation; "
                            "if no unambiguous antecedent exists, return needs_context=false."
                        )
                        continue
            except (ValueError, AttributeError):
                pass
            break
        return question
