from __future__ import annotations

from app.config import Settings
from app.providers.constants import BUILTIN_PROVIDER_IDS
from app.providers.registry import PROVIDER_CAPABILITIES, build_builtin_chat_providers


def test_new_openai_compatible_builtin_ids_registered() -> None:
    for provider_id in ("openai", "mistral", "z_ai"):
        assert provider_id in BUILTIN_PROVIDER_IDS
        assert provider_id in PROVIDER_CAPABILITIES


def test_build_builtin_chat_providers_includes_new_providers() -> None:
    settings = Settings(
        openai_api_key="sk-openai",
        mistral_api_key="sk-mistral",
        z_ai_api_key="sk-zai",
    )
    providers = build_builtin_chat_providers(settings)
    assert "openai" in providers
    assert "mistral" in providers
    assert "z_ai" in providers
    assert providers["openai"].provider_name == "openai"
    assert providers["mistral"].provider_name == "mistral"
    assert providers["z_ai"].provider_name == "z_ai"


def test_z_ai_uses_configurable_base_url() -> None:
    settings = Settings(z_ai_api_key="sk-zai", z_ai_base_url="https://custom.z.ai/v1")
    providers = build_builtin_chat_providers(settings)
    assert providers["z_ai"].endpoint == "https://custom.z.ai/v1/chat/completions"


def test_openai_compatible_providers_support_streaming() -> None:
    for provider_id in ("openai", "mistral", "z_ai", "deepseek", "groq"):
        caps = PROVIDER_CAPABILITIES[provider_id]
        assert caps.supports_streaming is True
