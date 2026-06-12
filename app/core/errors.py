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
    "console_client_unauthorized",
    "console_client_misconfigured",
    "provider_not_supported",
    "runtime_provider_not_found",
    "runtime_provider_invalid",
    "runtime_provider_conflict",
    "runtime_providers_disabled",
    "runtime_provider_test_failed",
    "api_key_not_found",
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
    "internal_server_error",
    "provider_auth_failed",
    "provider_model_unavailable",
    "provider_timeout",
    "provider_error",
    "unsupported_parameter",
    "invalid_message",
    "api_key_revoked",
    "safety_violation",
    "prompt_injection_detected",
    "secret_exfiltration_blocked",
    "malicious_cyber_request",
    "unsafe_output_blocked",
}


_AUTHENTICATION_ERROR_CODES = {
    "missing_api_key",
    "invalid_api_key",
}

_PERMISSION_ERROR_CODES = {
    "model_not_allowed",
    "conversation_access_denied",
    "internal_admin_unauthorized",
    "api_key_revoked",
}

_RATE_LIMIT_ERROR_CODES = {
    "rate_limit_exceeded",
    "daily_quota_exceeded",
    "monthly_quota_exceeded",
}

_PROVIDER_ERROR_CODES = {
    "provider_unavailable",
    "all_providers_failed",
    "provider_auth_failed",
    "provider_model_unavailable",
    "provider_timeout",
    "provider_error",
    "streaming_not_implemented",
    "streaming_not_supported",
    "stream_interrupted",
    "stream_provider_failed",
    "provider_health_strict_blocked",
    "embedding_provider_unavailable",
}

_INVALID_REQUEST_ERROR_CODES = {
    "invalid_request",
    "invalid_model",
    "invalid_search_mode",
    "invalid_tools_mode",
    "invalid_orchestration_mode",
    "invalid_semantic_recall_mode",
    "invalid_summary_mode",
    "invalid_conversation_request",
    "invalid_memory_control_request",
    "invalid_diagnostic_request",
    "invalid_search_backend",
    "request_too_large",
    "unsupported_parameter",
    "invalid_message",
    "model_config_invalid",
    "embedding_config_invalid",
    "model_behavior_config_invalid",
}


_POLICY_ERROR_CODES = {
    "safety_violation",
    "prompt_injection_detected",
    "secret_exfiltration_blocked",
    "malicious_cyber_request",
    "unsafe_output_blocked",
}


def resolve_error_type(code: str, status_code: int = 400) -> str:
    if code in _AUTHENTICATION_ERROR_CODES:
        return "authentication_error"
    if code in _PERMISSION_ERROR_CODES:
        return "permission_error"
    if code in _RATE_LIMIT_ERROR_CODES:
        return "rate_limit_error"
    if code in _PROVIDER_ERROR_CODES:
        return "provider_error"
    if code in _POLICY_ERROR_CODES:
        return "policy_error"
    if code in _INVALID_REQUEST_ERROR_CODES:
        return "invalid_request_error"
    if code == "internal_server_error" or status_code >= 500:
        return "api_error"
    if status_code == 404:
        return "invalid_request_error"
    return "api_error"


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


def build_error_response(
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    *,
    param: str | None = None,
    status_code: int = 400,
) -> dict[str, Any]:
    return {
        "error": {
            "message": message,
            "type": resolve_error_type(code, status_code=status_code),
            "param": param,
            "code": code,
            "details": details or {},
        }
    }


def validation_error_param(errors: list[dict[str, Any]]) -> str | None:
    if not errors:
        return None
    loc = errors[0].get("loc")
    if not isinstance(loc, (list, tuple)) or not loc:
        return None
    tail = loc[-1]
    return str(tail) if tail is not None else None
