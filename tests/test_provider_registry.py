from __future__ import annotations

from app.providers.registry import PROVIDER_CAPABILITIES, SUPPORTED_CHAT_PROVIDERS, list_provider_capabilities
from app.security.secret_redaction import redact_secret_text, sanitize_config_response


def test_provider_capabilities_are_safe_and_include_deepseek() -> None:
    assert "deepseek" in SUPPORTED_CHAT_PROVIDERS
    caps = list_provider_capabilities()
    provider_ids = {item["provider_id"] for item in caps}
    assert provider_ids == set(SUPPORTED_CHAT_PROVIDERS)
    for item in caps:
        assert "api_key_env_name" in item
        assert "sk-" not in str(item)
        assert "secret" not in str(item.get("display_name", "")).lower()


def test_provider_capabilities_metadata_fields() -> None:
    groq = PROVIDER_CAPABILITIES["groq"]
    assert groq.supports_streaming is True
    assert groq.api_key_env_name == "GROQ_API_KEY"
    deepseek = PROVIDER_CAPABILITIES["deepseek"]
    assert deepseek.supports_chat_completions is True
    assert deepseek.health_check_model == "deepseek-chat"


def test_redact_secret_text_masks_tokens() -> None:
    raw = "Bearer nia_testtoken123 and nsk_userkey123 and sk-provider-key-1234567890"
    cleaned = redact_secret_text(raw)
    assert "nia_testtoken123" not in cleaned
    assert "nsk_userkey123" not in cleaned
    assert "sk-provider-key-1234567890" not in cleaned


def test_sanitize_config_response_strips_secret_keys() -> None:
    payload = sanitize_config_response(
        {
            "provider_chain": [{"provider": "groq", "model": "x"}],
            "api_key": "secret-value",
            "authorization": "Bearer abc",
        }
    )
    assert payload["api_key"] == "[REDACTED]"
    assert payload["authorization"] == "[REDACTED]"
