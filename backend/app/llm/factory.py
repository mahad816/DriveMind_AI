"""Chat provider factory helpers."""

from __future__ import annotations

from app.core.config import Settings, get_settings
from app.llm.base import ChatService
from app.llm.openai_service import OpenAIChatService


def get_chat_service(settings: Settings | None = None) -> ChatService:
    """Return the configured chat provider for the MVP."""
    return OpenAIChatService(settings=settings or get_settings())
