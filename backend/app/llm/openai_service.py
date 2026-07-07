"""OpenAI chat completion provider for grounded RAG answers."""

from __future__ import annotations

from openai import APIError, AsyncOpenAI

from app.core.config import Settings, get_settings
from app.llm.base import ChatConfigurationError, ChatError
from app.llm.prompts import RAG_SYSTEM_PROMPT, build_grounded_user_message
from app.retrieval.types import RetrievedChunk

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
        client = self._get_client()
        try:
            response = await client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": RAG_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
            )
        except APIError as exc:
            raise ChatError(f"OpenAI chat request failed: {exc}") from exc

        choice = response.choices[0] if response.choices else None
        content = choice.message.content if choice is not None and choice.message is not None else None
        if not content or not content.strip():
            raise ChatError("OpenAI chat request returned an empty answer")
        return content.strip()
