from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.core.runtime_providers.loader import build_runtime_openai_providers
from app.core.runtime_providers.secrets import resolve_runtime_provider_api_key
from app.core.runtime_providers.storage import list_runtime_providers
from app.providers.constants import BUILTIN_PROVIDER_IDS
from app.providers.base import BaseProvider
from app.providers.groq import GroqProvider
from app.providers.nvidia import NvidiaProvider
from app.providers.ollama_cloud import OllamaCloudProvider
from app.providers.openrouter import OpenRouterProvider
from app.providers.openai_compatible import OpenAICompatibleChatProvider


@dataclass(frozen=True)
class ProviderCapabilities:
    provider_id: str
    display_name: str
    supports_streaming: bool
    supports_chat_completions: bool
    supports_tools: bool
    supports_json_mode: bool
    supports_reasoning_effort: bool
    default_timeout_seconds: float
    health_check_model: str | None
    api_base_env_name: str | None
    api_key_env_name: str | None


PROVIDER_CAPABILITIES: dict[str, ProviderCapabilities] = {
    "groq": ProviderCapabilities(
        provider_id="groq",
        display_name="Groq",
        supports_streaming=True,
        supports_chat_completions=True,
        supports_tools=True,
        supports_json_mode=True,
        supports_reasoning_effort=False,
        default_timeout_seconds=30.0,
        health_check_model="llama-3.1-8b-instant",
        api_base_env_name=None,
        api_key_env_name="GROQ_API_KEY",
    ),
    "openrouter": ProviderCapabilities(
        provider_id="openrouter",
        display_name="OpenRouter",
        supports_streaming=True,
        supports_chat_completions=True,
        supports_tools=True,
        supports_json_mode=True,
        supports_reasoning_effort=False,
        default_timeout_seconds=30.0,
        health_check_model="openrouter/auto",
        api_base_env_name=None,
        api_key_env_name="OPENROUTER_API_KEY",
    ),
    "nvidia": ProviderCapabilities(
        provider_id="nvidia",
        display_name="NVIDIA NIM",
        supports_streaming=False,
        supports_chat_completions=True,
        supports_tools=True,
        supports_json_mode=False,
        supports_reasoning_effort=False,
        default_timeout_seconds=30.0,
        health_check_model="meta/llama-3.1-8b-instruct",
        api_base_env_name="NVIDIA_BASE_URL",
        api_key_env_name="NVIDIA_API_KEY",
    ),
    "ollama_cloud": ProviderCapabilities(
        provider_id="ollama_cloud",
        display_name="Ollama Cloud",
        supports_streaming=True,
        supports_chat_completions=True,
        supports_tools=False,
        supports_json_mode=False,
        supports_reasoning_effort=False,
        default_timeout_seconds=60.0,
        health_check_model="llama3.2",
        api_base_env_name="OLLAMA_BASE_URL",
        api_key_env_name="OLLAMA_API_KEY",
    ),
    "deepseek": ProviderCapabilities(
        provider_id="deepseek",
        display_name="DeepSeek",
        supports_streaming=True,
        supports_chat_completions=True,
        supports_tools=True,
        supports_json_mode=True,
        supports_reasoning_effort=False,
        default_timeout_seconds=30.0,
        health_check_model="deepseek-chat",
        api_base_env_name=None,
        api_key_env_name="DEEPSEEK_API_KEY",
    ),
}

SUPPORTED_CHAT_PROVIDERS: frozenset[str] = BUILTIN_PROVIDER_IDS


def list_provider_capabilities(settings: Settings | None = None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for provider_id in sorted(PROVIDER_CAPABILITIES):
        caps = PROVIDER_CAPABILITIES[provider_id]
        items.append(
            {
                "provider_id": caps.provider_id,
                "source": "builtin",
                "display_name": caps.display_name,
                "supports_streaming": caps.supports_streaming,
                "supports_chat_completions": caps.supports_chat_completions,
                "supports_tools": caps.supports_tools,
                "supports_json_mode": caps.supports_json_mode,
                "supports_reasoning_effort": caps.supports_reasoning_effort,
                "default_timeout_seconds": caps.default_timeout_seconds,
                "health_check_model": caps.health_check_model,
                "api_base_env_name": caps.api_base_env_name,
                "api_key_env_name": caps.api_key_env_name,
            }
        )
    runtime_settings = settings
    if runtime_settings is None:
        from app.deps import get_settings

        runtime_settings = get_settings()
    if bool(getattr(runtime_settings, "nesty_runtime_openai_providers_enabled", True)):
        from app.core.runtime_providers.models import runtime_provider_to_safe_dict
        from app.core.runtime_providers.service import secret_status_for_row

        for row in list_runtime_providers(include_disabled=True):
            items.append(
                runtime_provider_to_safe_dict(row, secret_status=secret_status_for_row(runtime_settings, row))
            )
    return items


def build_builtin_chat_providers(settings: Settings, timeout_seconds: float | None = None) -> dict[str, BaseProvider]:
    timeout = float(timeout_seconds if timeout_seconds is not None else settings.request_timeout_seconds)
    ollama_timeout = float(settings.ollama_request_timeout_seconds or timeout)
    return {
        "groq": GroqProvider(api_key=settings.groq_api_key, timeout_seconds=timeout),
        "openrouter": OpenRouterProvider(api_key=settings.openrouter_api_key, timeout_seconds=timeout),
        "nvidia": NvidiaProvider(
            api_key=settings.nvidia_api_key,
            timeout_seconds=timeout,
            base_url=settings.nvidia_base_url,
        ),
        "ollama_cloud": OllamaCloudProvider(
            api_key=settings.ollama_api_key,
            timeout_seconds=ollama_timeout,
            base_url=settings.ollama_base_url,
        ),
        "deepseek": OpenAICompatibleChatProvider(
            provider_name="deepseek",
            api_key=settings.deepseek_api_key,
            timeout_seconds=timeout,
            endpoint="https://api.deepseek.com/v1/chat/completions",
            require_api_key=True,
        ),
    }


def build_chat_providers(settings: Settings, timeout_seconds: float | None = None) -> dict[str, BaseProvider]:
    return build_all_chat_providers(settings, timeout_seconds=timeout_seconds)


def build_all_chat_providers(settings: Settings, timeout_seconds: float | None = None) -> dict[str, BaseProvider]:
    providers = build_builtin_chat_providers(settings, timeout_seconds=timeout_seconds)
    providers.update(build_runtime_openai_providers(settings))
    return providers
