from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ERROR_CODES = {
    "invalid_model",
    "provider_unavailable",
    "all_providers_failed",
    "missing_api_key",
    "streaming_not_implemented",
    "invalid_request",
    "search_failed",
    "context_sanitization_failed",
    "invalid_search_mode",
    "unsafe_url_blocked",
    "fetch_failed",
    "invalid_tools_mode",
    "unknown_tool",
    "tool_execution_failed",
    "tool_timeout",
    "tool_not_configured",
}


@dataclass
class APIError(Exception):
    code: str
    message: str
    status_code: int = 400
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderError(Exception):
    provider: str
    message: str
    retryable: bool
    status_code: int | None = None


class MissingAPIKeyError(ProviderError):
    def __init__(self, provider: str) -> None:
        super().__init__(provider=provider, message="Missing API key.", retryable=True)


def build_error_response(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
        }
    }
