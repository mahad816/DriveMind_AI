"""Provider-independent canonical agent messages and native-call observations."""

from collections.abc import Sequence
from typing import Literal, Protocol
import json
from pydantic import Field, JsonValue, model_validator
from app.routing.intent_frame.references import ContractModel
from app.llm.base import ChatError


class AgentResponseError(ChatError):
    """Invalid provider response; public message contains no provider body."""


class ToolDefinition(ContractModel):
    name: Literal["files_query", "resolve_file", "search_knowledge", "file_evidence"]
    description: str = Field(min_length=1, max_length=500)
    parameters: dict[str, JsonValue]


class ToolCallRequest(ContractModel):
    call_id: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")
    tool_name: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    arguments: dict[str, JsonValue]
    argument_error: Literal["INVALID_ARGUMENT"] | None = None

    @model_validator(mode="after")
    def bounded_arguments(self) -> "ToolCallRequest":
        if len(json.dumps(self.arguments, allow_nan=False)) > 20000:
            raise ValueError("arguments exceed budget")
        if self.argument_error is not None and self.arguments:
            raise ValueError("malformed argument calls cannot carry executable arguments")
        return self


class AgentMessage(ContractModel):
    role: Literal["SYSTEM", "USER", "ASSISTANT", "TOOL"]
    text: str | None = Field(default=None, max_length=750000)
    tool_calls: tuple[ToolCallRequest, ...] = Field(default=(), max_length=8)
    call_id: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def canonical_role(self) -> "AgentMessage":
        text_present = bool(self.text and self.text.strip())
        if self.role == "ASSISTANT":
            if self.call_id is not None or not (text_present or self.tool_calls):
                raise ValueError("invalid assistant message")
        elif self.role == "TOOL":
            if not self.call_id or self.tool_calls or not text_present:
                raise ValueError("tool message requires content and call ID")
        elif self.call_id is not None or self.tool_calls or not text_present:
            raise ValueError("user/system messages require text only")
        if len({t.call_id for t in self.tool_calls}) != len(self.tool_calls):
            raise ValueError("duplicate tool call IDs")
        return self


class AgentUsage(ContractModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class AgentStepResult(ContractModel):
    text: str | None = Field(default=None, max_length=32000)
    tool_calls: tuple[ToolCallRequest, ...] = Field(default=(), max_length=8)
    usage: AgentUsage = AgentUsage()
    returned_model: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def meaningful_result(self) -> "AgentStepResult":
        AgentMessage(role="ASSISTANT", text=self.text, tool_calls=self.tool_calls)
        return self


class AgentChatService(Protocol):
    async def step(
        self, *, messages: Sequence[AgentMessage], tools: Sequence[ToolDefinition]
    ) -> AgentStepResult: ...
