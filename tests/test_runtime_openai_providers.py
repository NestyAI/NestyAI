from __future__ import annotations

import pytest

from app.config import Settings
from app.core.runtime_providers.secrets import read_provider_secret, write_provider_secret
from app.core.runtime_providers.service import build_create_record, remove_runtime_provider, run_runtime_provider_test
from app.core.runtime_providers.storage import create_runtime_provider, get_runtime_provider
from app.core.runtime_providers.validation import (
    get_supported_chat_provider_ids,
    validate_default_headers,
    validate_provider_id,
    validate_runtime_provider_payload,
)
from app.deps import get_providers
from app.providers.constants import BUILTIN_PROVIDER_IDS
from app.storage.db import init_db


def _settings(tmp_path, **overrides) -> Settings:
    base = {
        "nesty_db_path": str(tmp_path / "nesty.db"),
        "internal_admin_enabled": True,
        "nesty_internal_admin_token": "admin-token",
        "nesty_console_client_auth_required": False,
        "nesty_runtime_openai_providers_enabled": True,
        "nesty_runtime_provider_secret_mode": "file",
        "nesty_runtime_provider_secret_dir": str(tmp_path / "provider_secrets"),
        "nesty_runtime_provider_allow_http": False,
        "nesty_runtime_provider_allow_private_base_url": False,
        "require_api_key": False,
    }
    base.update(overrides)
    return Settings(**base)


def test_runtime_provider_id_validation() -> None:
    assert validate_provider_id("custom_lmstudio")[0] is True
    assert validate_provider_id("groq")[0] is False
    assert validate_provider_id("ab")[0] is False


def test_default_headers_reject_authorization() -> None:
    ok, error = validate_default_headers({"Authorization": "Bearer abc"})
    assert ok is False
    assert error


def test_base_url_rejects_localhost_by_default() -> None:
    settings = Settings(nesty_runtime_provider_allow_private_base_url=False)
    payload = {
        "provider_id": "custom_local",
        "provider_type": "openai_compatible",
        "base_url": "http://127.0.0.1:1234",
        "api_key_mode": "none",
        "default_headers": {},
    }
    ok, error = validate_runtime_provider_payload(payload, settings=settings)
    assert ok is False
    assert error


def test_base_url_allows_private_when_flag_enabled() -> None:
    settings = Settings(
        nesty_runtime_provider_allow_private_base_url=True,
        nesty_runtime_provider_allow_http=True,
    )
    payload = {
        "provider_id": "custom_local",
        "provider_type": "openai_compatible",
        "base_url": "http://127.0.0.1:1234",
        "api_key_mode": "none",
        "default_headers": {},
    }
    ok, _ = validate_runtime_provider_payload(payload, settings=settings)
    assert ok is True


def test_secret_file_mode_writes_and_redacts(tmp_path, monkeypatch) -> None:
    db_path = str(tmp_path / "runtime.db")
    init_db(db_path)
    settings = _settings(tmp_path)
    monkeypatch.setattr("app.deps.get_settings", lambda: settings)
    from app.core.runtime_providers.models import RuntimeOpenAIProviderCreateRequest

    body = RuntimeOpenAIProviderCreateRequest(
        provider_id="custom_secret",
        display_name="Custom Secret",
        base_url="https://api.example.com",
        api_key_mode="secret_file",
        api_key="super-secret-provider-key-value",
    )
    record, error = build_create_record(body, settings)
    assert error is None
    record["provider_id"] = body.provider_id
    create_runtime_provider(record, db_path=db_path)
    stored = read_provider_secret(settings, "custom_secret", record.get("api_key_secret_ref"))
    assert stored == "super-secret-provider-key-value"
    row = get_runtime_provider("custom_secret", db_path=db_path)
    assert row is not None
    assert "super-secret" not in str(row)


def test_dynamic_provider_chain_validation(tmp_path, monkeypatch) -> None:
    db_path = str(tmp_path / "runtime2.db")
    init_db(db_path)
    settings = _settings(tmp_path)
    monkeypatch.setattr("app.deps.get_settings", lambda: settings)
    create_runtime_provider(
        {
            "provider_id": "custom_chain",
            "provider_type": "openai_compatible",
            "display_name": "Chain Provider",
            "enabled": True,
            "base_url": "https://api.example.com",
            "chat_completions_path": "/v1/chat/completions",
            "api_key_mode": "none",
            "default_headers": {},
            "capabilities": {"supports_streaming": True, "supports_chat_completions": True},
            "default_timeout_seconds": 30.0,
        },
        db_path=db_path,
    )
    ids = get_supported_chat_provider_ids(settings=settings, db_path=db_path)
    assert "custom_chain" in ids
    settings_disabled = _settings(tmp_path, nesty_runtime_openai_providers_enabled=False)
    ids_disabled = get_supported_chat_provider_ids(settings=settings_disabled, db_path=db_path)
    assert "custom_chain" not in ids_disabled


@pytest.mark.asyncio
async def test_runtime_provider_test_disabled_flag(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path, nesty_runtime_openai_providers_enabled=False)
    db_path = settings.nesty_db_path
    init_db(db_path)
    monkeypatch.setattr("app.deps.get_settings", lambda: settings)
    create_runtime_provider(
        {
            "provider_id": "custom_disabled_flag",
            "provider_type": "openai_compatible",
            "display_name": "Disabled Flag",
            "enabled": True,
            "base_url": "https://api.example.com",
            "chat_completions_path": "/v1/chat/completions",
            "api_key_mode": "none",
            "default_headers": {},
            "capabilities": {"supports_streaming": True, "supports_chat_completions": True},
            "default_timeout_seconds": 30.0,
        },
        db_path=db_path,
    )
    result = await run_runtime_provider_test("custom_disabled_flag", settings=settings)
    assert result["ok"] is False
    assert result["error_code"] == "runtime_providers_disabled"


def test_delete_removes_secret_file(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    db_path = settings.nesty_db_path
    init_db(db_path)
    monkeypatch.setattr("app.deps.get_settings", lambda: settings)
    ref = write_provider_secret(settings, "custom_delete", "secret-value")
    create_runtime_provider(
        {
            "provider_id": "custom_delete",
            "provider_type": "openai_compatible",
            "display_name": "Delete Me",
            "enabled": True,
            "base_url": "https://api.example.com",
            "chat_completions_path": "/v1/chat/completions",
            "api_key_mode": "secret_file",
            "api_key_secret_ref": ref,
            "default_headers": {},
            "capabilities": {"supports_streaming": True, "supports_chat_completions": True},
            "default_timeout_seconds": 30.0,
        },
        db_path=db_path,
    )
    assert remove_runtime_provider("custom_delete", settings) is True
    assert read_provider_secret(settings, "custom_delete", ref) is None


def test_builtin_providers_remain_available() -> None:
    assert BUILTIN_PROVIDER_IDS == {
        "groq",
        "openrouter",
        "nvidia",
        "ollama_cloud",
        "deepseek",
        "openai",
        "mistral",
        "z_ai",
        "google_gemini",
        "anthropic_claude",
    }


def test_get_providers_cache_cleared_on_mutation(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    db_path = settings.nesty_db_path
    init_db(db_path)
    monkeypatch.setattr("app.deps.get_settings", lambda: settings)
    from app.deps import clear_runtime_model_config_caches

    get_providers.cache_clear()
    before = get_providers()
    create_runtime_provider(
        {
            "provider_id": "custom_cache",
            "provider_type": "openai_compatible",
            "display_name": "Cache",
            "enabled": True,
            "base_url": "https://api.example.com",
            "chat_completions_path": "/v1/chat/completions",
            "api_key_mode": "none",
            "default_headers": {},
            "capabilities": {"supports_streaming": True, "supports_chat_completions": True},
            "default_timeout_seconds": 30.0,
        },
        db_path=db_path,
    )
    clear_runtime_model_config_caches()
    after = get_providers()
    assert "custom_cache" not in before
    assert "custom_cache" in after
    get_providers.cache_clear()
