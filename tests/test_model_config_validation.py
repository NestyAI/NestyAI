from __future__ import annotations

from app.core.model_config_loader import validate_model_config_override


def test_invalid_provider_rejected() -> None:
    valid, error = validate_model_config_override(
        "nesty-flash-1.0",
        {"provider_chain": [{"provider": "unknown", "model": "x"}]},
    )
    assert valid is False
    assert "unsupported provider" in str(error or "")


def test_empty_model_string_rejected() -> None:
    valid, error = validate_model_config_override(
        "nesty-flash-1.0",
        {"provider_chain": [{"provider": "groq", "model": ""}]},
    )
    assert valid is False
    assert "non-empty" in str(error or "")


def test_unknown_field_rejected() -> None:
    valid, error = validate_model_config_override(
        "nesty-flash-1.0",
        {"unsafe_field": True},
    )
    assert valid is False
    assert "not allowed" in str(error or "")


def test_secret_like_value_rejected() -> None:
    valid, error = validate_model_config_override(
        "nesty-flash-1.0",
        {"display_name": "sk-super-secret-token-value-123456789"},
    )
    assert valid is False
    assert "secret-like" in str(error or "")


def test_embedding_model_in_chat_provider_chain_rejected() -> None:
    valid, error = validate_model_config_override(
        "nesty-flash-1.0",
        {"provider_chain": [{"provider": "openrouter", "model": "nvidia/llama-nemotron-embed-vl-1b-v2:free"}]},
    )
    assert valid is False
    assert "embedding model" in str(error or "")


def test_explicit_free_chat_model_ids_accepted() -> None:
    valid, error = validate_model_config_override(
        "nesty-combined-1.0",
        {"provider_chain": [{"provider": "openrouter", "model": "moonshotai/kimi-k2.6:free"}]},
    )
    assert valid is True
    assert error is None


def test_ollama_cloud_provider_is_supported() -> None:
    valid, error = validate_model_config_override(
        "nesty-combined-1.0",
        {"provider_chain": [{"provider": "ollama_cloud", "model": "gemma3:12b"}]},
    )
    assert valid is True
    assert error is None
