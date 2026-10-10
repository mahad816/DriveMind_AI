"""Fixed diagnostics for credential-bearing boundaries; never inspect exception text."""

import logging

from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError


class CredentialFailure(Exception):
    """Application-owned safe failure classification, without a provider exception."""

    def __init__(self, message: str, *, category: str = "unexpected_failure") -> None:
        super().__init__(message)
        self.category = (
            category
            if category
            in {
                "unexpected_failure",
                "reauthorization_required",
                "authentication_expired",
                "temporary_provider_failure",
                "configuration_error",
            }
            else "unexpected_failure"
        )


class OAuthCredentialFailure(CredentialFailure, ValueError):
    """Preserve the existing OAuth ValueError API boundary."""


def failure_category(exc: Exception) -> str:
    """Classify only trusted SDK types and structured status/error codes."""
    if isinstance(exc, CredentialFailure):
        return exc.category
    if isinstance(exc, RefreshError):
        if any(isinstance(arg, dict) and arg.get("error") == "invalid_grant" for arg in exc.args):
            return "reauthorization_required"
    if isinstance(exc, HttpError):
        if exc.resp.status == 401:
            return "authentication_expired"
        if exc.resp.status == 429 or 500 <= exc.resp.status <= 599:
            return "temporary_provider_failure"
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return "temporary_provider_failure"
    return "unexpected_failure"


def safe_failure(exc: Exception, operation: str) -> str:
    """Operation must be an application-owned constant, never provider/browser input."""
    return f"{operation} failed ({failure_category(exc)})."


def log_safe_failure(logger: logging.Logger, operation: str, exc: Exception) -> None:
    """Do not attach traceback, exception object, headers or response bodies."""
    logger.error("%s", safe_failure(exc, operation))
