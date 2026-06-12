from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RuntimeProviderCapabilities(BaseModel):
    supports_streaming: bool = True
    supports_chat_completions: bool = True
    supports_json_mode: bool = False
    supports_tools: bool = False
    supports_reasoning_effort: bool = False


class RuntimeOpenAIProviderCreateRequest(BaseModel):
    provider_id: str = Field(min_length=3, max_length=48)
    display_name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    base_url: str = Field(min_length=8, max_length=512)
    chat_completions_path: str = Field(default="/v1/chat/completions", max_length=256)
    models_path: str | None = Field(default=None, max_length=256)
    api_key_mode: str = Field(default="none")
    api_key_env_name: str | None = Field(default=None, max_length=128)
    api_key: str | None = Field(default=None, max_length=4096)
    default_headers: dict[str, str] = Field(default_factory=dict)
    default_timeout_seconds: float = Field(default=30.0, ge=1.0, le=600.0)
    supports_streaming: bool = True
    supports_json_mode: bool = False
    supports_tools: bool = False
    supports_reasoning_effort: bool = False
    health_check_model: str | None = Field(default=None, max_length=256)


class RuntimeOpenAIProviderUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    enabled: bool | None = None
    base_url: str | None = Field(default=None, max_length=512)
    chat_completions_path: str | None = Field(default=None, max_length=256)
    models_path: str | None = Field(default=None, max_length=256)
    api_key_mode: str | None = None
    api_key_env_name: str | None = Field(default=None, max_length=128)
    api_key: str | None = Field(default=None, max_length=4096)
    default_headers: dict[str, str] | None = None
    default_timeout_seconds: float | None = Field(default=None, ge=1.0, le=600.0)
    supports_streaming: bool | None = None
    supports_json_mode: bool | None = None
    supports_tools: bool | None = None
    supports_reasoning_effort: bool | None = None
    health_check_model: str | None = Field(default=None, max_length=256)


class RuntimeProviderTestRequest(BaseModel):
    model: str | None = Field(default=None, max_length=256)
    message: str = Field(default="Reply with exactly: OK", min_length=1, max_length=200)


def runtime_provider_to_safe_dict(row: dict[str, Any], *, secret_status: str) -> dict[str, Any]:
    capabilities = row.get("capabilities") or {}
    return {
        "provider_id": row.get("provider_id"),
        "provider_type": row.get("provider_type"),
        "source": "runtime",
        "display_name": row.get("display_name"),
        "enabled": bool(row.get("enabled")),
        "base_url": row.get("base_url"),
        "chat_completions_path": row.get("chat_completions_path"),
        "models_path": row.get("models_path"),
        "api_key_mode": row.get("api_key_mode"),
        "api_key_env_name": row.get("api_key_env_name"),
        "api_key_secret_ref": row.get("api_key_secret_ref"),
        "secret_status": secret_status,
        "default_timeout_seconds": row.get("default_timeout_seconds"),
        "supports_streaming": capabilities.get("supports_streaming"),
        "supports_chat_completions": capabilities.get("supports_chat_completions", True),
        "supports_json_mode": capabilities.get("supports_json_mode"),
        "supports_tools": capabilities.get("supports_tools"),
        "supports_reasoning_effort": capabilities.get("supports_reasoning_effort"),
        "health_check_model": row.get("health_check_model"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }
