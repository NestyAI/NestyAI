from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.core.provider_credentials.resolver import credential_status_for_provider, resolve_builtin_provider_api_key
from app.core.runtime_providers.loader import build_runtime_openai_providers
from app.core.runtime_providers.secrets import resolve_runtime_provider_api_key
from app.core.runtime_providers.storage import list_runtime_providers
from app.providers.constants import BUILTIN_PROVIDER_IDS
from app.providers.base import BaseProvider
from app.providers.anthropic import AnthropicProvider
from app.providers.gemini import GeminiProvider
from app.providers.groq import GroqProvider
from app.providers.nvidia import NvidiaProvider
from app.providers.ollama_cloud import OllamaCloudProvider
from app.providers.openrouter import OpenRouterProvider
from app.providers.mistral import MistralProvider
from app.providers.openai_builtin import OpenAIBuiltinProvider
from app.providers.deepseek import DeepSeekProvider
from app.providers.z_ai import ZAIProvider


def _resolve_builtin_api_key(settings: Settings, provider_id: str) -> str | None:
    api_key, _ = resolve_builtin_provider_api_key(provider_id, settings)
    return api_key


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
    "openai": ProviderCapabilities(
        provider_id="openai",
        display_name="OpenAI",
        supports_streaming=True,
        supports_chat_completions=True,
        supports_tools=True,
        supports_json_mode=True,
        supports_reasoning_effort=False,
        default_timeout_seconds=30.0,
        health_check_model="gpt-4o-mini",
        api_base_env_name=None,
        api_key_env_name="OPENAI_API_KEY",
    ),
    "mistral": ProviderCapabilities(
        provider_id="mistral",
        display_name="Mistral",
        supports_streaming=True,
        supports_chat_completions=True,
        supports_tools=True,
        supports_json_mode=True,
        supports_reasoning_effort=False,
        default_timeout_seconds=30.0,
        health_check_model="mistral-small-latest",
        api_base_env_name=None,
        api_key_env_name="MISTRAL_API_KEY",
    ),
    "z_ai": ProviderCapabilities(
        provider_id="z_ai",
        display_name="Zhipu AI",
        supports_streaming=True,
        supports_chat_completions=True,
        supports_tools=True,
        supports_json_mode=True,
        supports_reasoning_effort=False,
        default_timeout_seconds=30.0,
        health_check_model="glm-4-flash",
        api_base_env_name="Z_AI_BASE_URL",
        api_key_env_name="Z_AI_API_KEY",
    ),
    "google_gemini": ProviderCapabilities(
        provider_id="google_gemini",
        display_name="Google Gemini",
        supports_streaming=True,
        supports_chat_completions=True,
        supports_tools=False,
        supports_json_mode=False,
        supports_reasoning_effort=False,
        default_timeout_seconds=30.0,
        health_check_model="gemini-2.0-flash",
        api_base_env_name=None,
        api_key_env_name="GOOGLE_GEMINI_API_KEY",
    ),
    "anthropic_claude": ProviderCapabilities(
        provider_id="anthropic_claude",
        display_name="Anthropic Claude",
        supports_streaming=True,
        supports_chat_completions=True,
        supports_tools=False,
        supports_json_mode=False,
        supports_reasoning_effort=False,
        default_timeout_seconds=30.0,
        health_check_model="claude-3-5-haiku-latest",
        api_base_env_name=None,
        api_key_env_name="ANTHROPIC_API_KEY",
    ),
}

SUPPORTED_CHAT_PROVIDERS: frozenset[str] = BUILTIN_PROVIDER_IDS


def list_provider_capabilities(settings: Settings | None = None) -> list[dict[str, Any]]:
    runtime_settings = settings
    if runtime_settings is None:
        from app.deps import get_settings

        runtime_settings = get_settings()
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
                **credential_status_for_provider(caps.provider_id, runtime_settings),
            }
        )
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
        "groq": GroqProvider(api_key=_resolve_builtin_api_key(settings, "groq"), timeout_seconds=timeout),
        "openrouter": OpenRouterProvider(
            api_key=_resolve_builtin_api_key(settings, "openrouter"),
            timeout_seconds=timeout,
        ),
        "nvidia": NvidiaProvider(
            api_key=_resolve_builtin_api_key(settings, "nvidia"),
            timeout_seconds=timeout,
            base_url=settings.nvidia_base_url,
        ),
        "ollama_cloud": OllamaCloudProvider(
            api_key=_resolve_builtin_api_key(settings, "ollama_cloud"),
            timeout_seconds=ollama_timeout,
            base_url=settings.ollama_base_url,
        ),
        "deepseek": DeepSeekProvider(
            api_key=_resolve_builtin_api_key(settings, "deepseek"),
            timeout_seconds=timeout,
        ),
        "openai": OpenAIBuiltinProvider(
            api_key=_resolve_builtin_api_key(settings, "openai"),
            timeout_seconds=timeout,
        ),
        "mistral": MistralProvider(
            api_key=_resolve_builtin_api_key(settings, "mistral"),
            timeout_seconds=timeout,
        ),
        "z_ai": ZAIProvider(
            api_key=_resolve_builtin_api_key(settings, "z_ai"),
            timeout_seconds=timeout,
            base_url=os.getenv("Z_AI_BASE_URL") or None,
        ),
        "google_gemini": GeminiProvider(
            api_key=_resolve_builtin_api_key(settings, "google_gemini"),
            timeout_seconds=timeout,
        ),
        "anthropic_claude": AnthropicProvider(
            api_key=_resolve_builtin_api_key(settings, "anthropic_claude"),
            timeout_seconds=timeout,
        ),
    }


def build_chat_providers(settings: Settings, timeout_seconds: float | None = None) -> dict[str, BaseProvider]:
    return build_all_chat_providers(settings, timeout_seconds=timeout_seconds)


def build_all_chat_providers(settings: Settings, timeout_seconds: float | None = None) -> dict[str, BaseProvider]:
    providers = build_builtin_chat_providers(settings, timeout_seconds=timeout_seconds)
    providers.update(build_runtime_openai_providers(settings))
    return providers
