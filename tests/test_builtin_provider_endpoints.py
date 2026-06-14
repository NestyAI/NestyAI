from __future__ import annotations

import pytest

from app.config import Settings
from app.providers.anthropic import AnthropicProvider
from app.providers.constants import (
    ANTHROPIC_MESSAGES_URL,
    DEEPSEEK_CHAT_COMPLETIONS_URL,
    GEMINI_API_BASE_URL,
    GROQ_CHAT_COMPLETIONS_URL,
    MISTRAL_CHAT_COMPLETIONS_URL,
    OLLAMA_CLOUD_DEFAULT_BASE_URL,
    OPENAI_CHAT_COMPLETIONS_URL,
    OPENROUTER_CHAT_COMPLETIONS_URL,
    Z_AI_DEFAULT_BASE_URL,
    openai_compatible_chat_url,
)
from app.providers.deepseek import DeepSeekProvider
from app.providers.gemini import GeminiProvider
from app.providers.groq import GroqProvider
from app.providers.mistral import MistralProvider
from app.providers.ollama_cloud import OllamaCloudProvider
from app.providers.openai_builtin import OpenAIBuiltinProvider
from app.providers.openrouter import OpenRouterProvider
from app.providers.registry import build_builtin_chat_providers
from app.providers.z_ai import ZAIProvider


@pytest.mark.parametrize(
    ("provider_id", "expected_endpoint"),
    [
        ("openai", OPENAI_CHAT_COMPLETIONS_URL),
        ("mistral", MISTRAL_CHAT_COMPLETIONS_URL),
        ("deepseek", DEEPSEEK_CHAT_COMPLETIONS_URL),
        ("groq", GROQ_CHAT_COMPLETIONS_URL),
        ("openrouter", OPENROUTER_CHAT_COMPLETIONS_URL),
        ("z_ai", openai_compatible_chat_url(Z_AI_DEFAULT_BASE_URL)),
    ],
)
def test_openai_compatible_builtin_default_endpoints(
    provider_id: str,
    expected_endpoint: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("Z_AI_BASE_URL", raising=False)
    settings = Settings(
        openai_api_key="sk-openai",
        mistral_api_key="sk-mistral",
        deepseek_api_key="sk-deepseek",
        groq_api_key="sk-groq",
        openrouter_api_key="sk-or",
        z_ai_api_key="sk-zai",
    )
    providers = build_builtin_chat_providers(settings)
    assert providers[provider_id].endpoint == expected_endpoint


def test_gemini_default_base_url() -> None:
    provider = GeminiProvider(api_key="gemini-key", timeout_seconds=30.0)
    assert provider.base_url == GEMINI_API_BASE_URL
    assert provider._generate_url("gemini-2.0-flash", stream=False) == (
        f"{GEMINI_API_BASE_URL}/models/gemini-2.0-flash:generateContent"
    )


def test_anthropic_default_messages_url() -> None:
    provider = AnthropicProvider(api_key="anthropic-key", timeout_seconds=30.0)
    assert provider.endpoint == ANTHROPIC_MESSAGES_URL


def test_z_ai_optional_base_url_override() -> None:
    provider = ZAIProvider(api_key="sk-zai", timeout_seconds=30.0, base_url="https://custom.example/v4")
    assert provider.endpoint == "https://custom.example/v4/chat/completions"


def test_z_ai_ignores_deprecated_api_z_ai_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("Z_AI_BASE_URL", "https://api.z.ai/v1")
    settings = Settings(z_ai_api_key="sk-zai")
    providers = build_builtin_chat_providers(settings)
    assert providers["z_ai"].endpoint == openai_compatible_chat_url(Z_AI_DEFAULT_BASE_URL)


def test_z_ai_default_without_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("Z_AI_BASE_URL", raising=False)
    settings = Settings(z_ai_api_key="sk-zai")
    providers = build_builtin_chat_providers(settings)
    assert providers["z_ai"].endpoint == openai_compatible_chat_url(Z_AI_DEFAULT_BASE_URL)


def test_ollama_cloud_default_base_url() -> None:
    provider = OllamaCloudProvider(api_key="ollama-key", timeout_seconds=30.0)
    assert provider.base_url == OLLAMA_CLOUD_DEFAULT_BASE_URL
    assert provider.endpoint == f"{OLLAMA_CLOUD_DEFAULT_BASE_URL}/api/chat"


def test_ollama_cloud_default_without_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    settings = Settings(ollama_api_key="ollama-key")
    providers = build_builtin_chat_providers(settings)
    assert providers["ollama_cloud"].base_url == OLLAMA_CLOUD_DEFAULT_BASE_URL


def test_direct_provider_classes_match_constants() -> None:
    assert OpenAIBuiltinProvider(api_key="k", timeout_seconds=1).endpoint == OPENAI_CHAT_COMPLETIONS_URL
    assert MistralProvider(api_key="k", timeout_seconds=1).endpoint == MISTRAL_CHAT_COMPLETIONS_URL
    assert DeepSeekProvider(api_key="k", timeout_seconds=1).endpoint == DEEPSEEK_CHAT_COMPLETIONS_URL
    assert GroqProvider(api_key="k", timeout_seconds=1).endpoint == GROQ_CHAT_COMPLETIONS_URL
    assert OpenRouterProvider(api_key="k", timeout_seconds=1).endpoint == OPENROUTER_CHAT_COMPLETIONS_URL
