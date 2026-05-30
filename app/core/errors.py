from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ERROR_CODES = {
    "invalid_model",
    "provider_unavailable",
    "all_providers_failed",
    "missing_api_key",
    "invalid_api_key",
    "streaming_not_implemented",
    "streaming_not_supported",
    "stream_interrupted",
    "stream_provider_failed",
    "request_too_large",
    "unsafe_cors_configuration",
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
    "model_not_allowed",
    "rate_limit_exceeded",
    "daily_quota_exceeded",
    "monthly_quota_exceeded",
    "usage_logging_failed",
    "conversation_not_found",
    "conversation_access_denied",
    "conversation_storage_failed",
    "invalid_conversation_request",
    "conversation_summary_failed",
    "invalid_summary_mode",
    "conversation_export_failed",
    "conversation_clear_failed",
    "fts_unavailable",
    "fts_rebuild_failed",
    "invalid_search_backend",
    "model_behavior_config_invalid",
    "orchestration_failed",
    "invalid_orchestration_mode",
    "orchestration_not_available",
    "internal_admin_disabled",
    "internal_admin_unauthorized",
    "model_config_not_found",
    "model_config_invalid",
    "model_config_update_failed",
    "model_config_test_failed",
    "embedding_provider_unavailable",
    "embedding_generation_failed",
    "embedding_storage_failed",
    "embedding_config_invalid",
    "invalid_semantic_recall_mode",
    "semantic_recall_failed",
    "semantic_recall_unavailable",
    "invalid_memory_control_request",
    "memory_control_update_failed",
    "memory_eval_failed",
    "diagnostics_disabled",
    "provider_diagnostic_failed",
    "provider_health_not_found",
    "invalid_diagnostic_request",
    "provider_health_unavailable",
    "provider_health_strict_blocked",
}


@dataclass
class APIError(Exception):
    code: str
    message: str
    status_code: int = 400
    details: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class ProviderError(Exception):
    provider: str
    message: str
    retryable: bool
    status_code: int | None = None


class MissingAPIKeyError(ProviderError):
    def __init__(self, provider: str) -> None:
        super().__init__(provider=provider, message="Missing API key.", retryable=True)


class StreamingNotSupportedError(ProviderError):
    def __init__(self, provider: str) -> None:
        super().__init__(provider=provider, message="Streaming is not supported by this provider.", retryable=True)


def build_error_response(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
        }
    }
