"""Native OpenAI function calling, isolated from existing answer generation."""

import asyncio
import json
from collections.abc import Awaitable, Callable, Sequence
from typing import cast
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionToolParam
from app.llm.openai_service import OpenAIChatService, completion_options
from app.llm.base import ChatError
from app.core.paid_execution import mark_paid_started
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
            mark_paid_started()
            response = await self._client.chat.completions.create(
                model=self.model_name,
                temperature=0,
                extra_body=completion_options(self.model_name),
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

    async def stream_step(
        self,
        *,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition],
        on_text: Callable[[str], Awaitable[None]],
    ) -> AgentStepResult:
        """Same native calls and budgets; only text deltas reach the private callback.

        Tool argument fragments stay inside this adapter and pass the same strict
        parser as non-streaming calls. Never retry or issue a second completion.
        """
        if self._client is None:
            self._client = super()._get_client()
        response = None
        try:
            mark_paid_started()
            response = await self._client.with_options(max_retries=0).chat.completions.create(
                model=self.model_name,
                temperature=0,
                extra_body=completion_options(self.model_name),
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
                stream=True,
                stream_options={"include_usage": True},
            )
            text = ""
            calls: dict[int, dict[str, str]] = {}
            finish = None
            usage = AgentUsage()
            model = None
            async for chunk in response:
                model = chunk.model
                if chunk.usage:
                    usage = AgentUsage(
                        input_tokens=chunk.usage.prompt_tokens,
                        output_tokens=chunk.usage.completion_tokens,
                    )
                if not chunk.choices:
                    continue
                if len(chunk.choices) != 1 or chunk.choices[0].index != 0 or finish is not None:
                    raise ValueError("Invalid completion sequence")
                choice = chunk.choices[0]
                if choice.delta.refusal:
                    raise ValueError("Provider refusal")
                for call in choice.delta.tool_calls or ():
                    if call.index not in range(8) or call.type not in (None, "function"):
                        raise ValueError("Invalid native function call")
                    item = calls.setdefault(call.index, {"id": "", "name": "", "arguments": ""})
                    item["id"] += call.id or ""
                    if call.function:
                        item["name"] += call.function.name or ""
                        item["arguments"] += call.function.arguments or ""
                    if (
                        len(item["arguments"]) > 20000
                        or len(item["id"]) > 200
                        or len(item["name"]) > 64
                    ):
                        raise ValueError("Native call budget exceeded")
                if choice.delta.content:
                    text += choice.delta.content
                    if len(text) > 32000:
                        raise ValueError("Answer budget exceeded")
                    if not calls:
                        await on_text(text)
                if choice.finish_reason:
                    finish = choice.finish_reason
            if finish != ("tool_calls" if calls else "stop"):
                raise ValueError("Incomplete completion")
            if calls and sorted(calls) != list(range(len(calls))):
                raise ValueError("Incomplete tool calls")
            return AgentStepResult(
                text=text or None,
                tool_calls=tuple(
                    parse_call(calls[i]["id"], calls[i]["name"], calls[i]["arguments"])
                    for i in sorted(calls)
                ),
                usage=usage,
                returned_model=model,
            )
        except Exception:
            raise AgentResponseError("Agent provider stream could not complete safely") from None
        finally:
            if response is not None:
                async with asyncio.timeout(5):
                    await response.close()
