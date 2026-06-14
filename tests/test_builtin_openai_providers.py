from __future__ import annotations

import pytest

from app.config import Settings
from app.providers.constants import BUILTIN_PROVIDER_IDS
from app.providers.registry import PROVIDER_CAPABILITIES, build_builtin_chat_providers
from app.providers.z_ai import ZAIProvider


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
    provider = ZAIProvider(api_key="sk-zai", timeout_seconds=30.0, base_url="https://custom.z.ai/v1")
    assert provider.endpoint == "https://custom.z.ai/v1/chat/completions"


def test_z_ai_default_base_url_is_zhipu_open_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("Z_AI_BASE_URL", raising=False)
    settings = Settings(z_ai_api_key="sk-zai")
    providers = build_builtin_chat_providers(settings)
    assert providers["z_ai"].endpoint == "https://open.bigmodel.cn/api/paas/v4/chat/completions"


def test_openai_compatible_providers_support_streaming() -> None:
    for provider_id in ("openai", "mistral", "z_ai", "deepseek", "groq"):
        caps = PROVIDER_CAPABILITIES[provider_id]
        assert caps.supports_streaming is True
