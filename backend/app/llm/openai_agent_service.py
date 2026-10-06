"""Native OpenAI function calling, isolated from existing answer generation."""

import json
from collections.abc import Sequence
from typing import cast
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionToolParam
from app.llm.openai_service import OpenAIChatService
from app.llm.base import ChatError
from app.agents.tool_rag.agent_models import (
    AgentMessage,
    AgentStepResult,
    AgentUsage,
    ToolCallRequest,
    ToolDefinition,
    AgentResponseError,
)


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON keys")
        result[key] = value
    return result


def parse_call(call_id: str, name: str, raw: str) -> ToolCallRequest:
    try:
        if len(raw) > 20000:
            raise ValueError("argument budget")
        arguments = json.loads(raw, object_pairs_hook=unique_object)
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be an object")
        return ToolCallRequest(call_id=call_id, tool_name=name, arguments=arguments)
    except (ValueError, TypeError, RecursionError):
        # Reject the malformed arguments, do not repair or execute them. Keep ID/name
        # only so the agent can return a matching safe tool error.
        return ToolCallRequest(
            call_id=call_id, tool_name=name, arguments={}, argument_error="INVALID_ARGUMENT"
        )


def native_messages(messages: Sequence[AgentMessage]) -> list[ChatCompletionMessageParam]:
    result = []
    for message in messages:
        item: dict[str, object] = {"role": message.role.lower(), "content": message.text}
        if message.role == "TOOL":
            item["tool_call_id"] = message.call_id
        if message.tool_calls:
            item["tool_calls"] = [
                {
                    "id": t.call_id,
                    "type": "function",
                    "function": {
                        "name": t.tool_name,
                        "arguments": json.dumps(t.arguments, allow_nan=False),
                    },
                }
                for t in message.tool_calls
            ]
        result.append(cast(ChatCompletionMessageParam, item))
    return result


class OpenAIAgentChatService(OpenAIChatService):
    """Reuse existing configurable model/authentication; no semantic retries."""

    async def aclose(self) -> None:
        """Close this service's client when its owning API orchestration finishes."""
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def step(
        self, *, messages: Sequence[AgentMessage], tools: Sequence[ToolDefinition]
    ) -> AgentStepResult:
        try:
            if self._client is None:
                self._client = super()._get_client()
            response = await self._client.chat.completions.create(
                model=self.model_name,
                temperature=0,
                messages=native_messages(messages),
                tools=[
                    cast(
                        ChatCompletionToolParam,
                        {"type": "function", "function": t.model_dump(mode="json")},
                    )
                    for t in tools
                ],
                tool_choice="auto",
                parallel_tool_calls=True,
            )
        except Exception:
            raise ChatError("Agent provider request failed") from None
        try:
            if len(response.choices) != 1:
                raise ValueError("one completion required")
            message = response.choices[0].message
            calls = []
            for call in message.tool_calls or ():
                if call.type != "function":
                    raise ValueError("native function calls required")
                calls.append(parse_call(call.id, call.function.name, call.function.arguments))
            return AgentStepResult(
                text=message.content,
                tool_calls=tuple(calls),
                returned_model=response.model,
                usage=AgentUsage(
                    input_tokens=response.usage.prompt_tokens if response.usage else None,
                    output_tokens=response.usage.completion_tokens if response.usage else None,
                ),
            )
        except Exception:
            raise AgentResponseError("Agent provider response is invalid") from None
