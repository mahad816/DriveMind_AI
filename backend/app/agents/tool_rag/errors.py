"""Bounded public failures with separately excluded private diagnostics."""

from enum import Enum
from pydantic import Field
from app.routing.intent_frame.references import ContractModel


class ToolErrorCode(str, Enum):
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    UNKNOWN_HANDLE = "UNKNOWN_HANDLE"
    NOT_FOUND = "NOT_FOUND"
    AMBIGUOUS = "AMBIGUOUS"
    UNSUPPORTED_SCOPE = "UNSUPPORTED_SCOPE"
    EMPTY_RESULT = "EMPTY_RESULT"
    INTERNAL_ERROR = "INTERNAL_ERROR"


MESSAGES = {
    ToolErrorCode.INVALID_ARGUMENT: "Tool arguments are invalid.",
    ToolErrorCode.UNKNOWN_HANDLE: "The handle is unknown or has the wrong type in this turn.",
    ToolErrorCode.NOT_FOUND: "No eligible indexed file matches the reference.",
    ToolErrorCode.AMBIGUOUS: "The reference matches multiple eligible files.",
    ToolErrorCode.UNSUPPORTED_SCOPE: "The requested scope is not supported.",
    ToolErrorCode.EMPTY_RESULT: "No eligible evidence was found.",
    ToolErrorCode.INTERNAL_ERROR: "The tool could not complete safely.",
}


class SafeToolError(ContractModel):
    code: ToolErrorCode
    message: str = Field(min_length=1, max_length=200)


class ToolError(ContractModel):
    code: ToolErrorCode
    private_diagnostic: str | None = Field(default=None, exclude=True, repr=False, max_length=2000)

    def to_llm_payload(self) -> SafeToolError:
        return SafeToolError(code=self.code, message=MESSAGES[self.code])


class ToolFailure(ValueError):
    def __init__(self, code: ToolErrorCode):
        self.error = ToolError(code=code)
        super().__init__(code.value)
