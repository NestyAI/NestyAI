from __future__ import annotations

from app.deps import get_providers


def test_provider_factory_registers_ollama_cloud(monkeypatch) -> None:
    get_providers.cache_clear()
    monkeypatch.setattr(
        "app.deps.get_settings",
        lambda: type(
            "S",
            (),
            {
                "request_timeout_seconds": 30.0,
                "groq_api_key": "",
                "openrouter_api_key": "",
                "nvidia_api_key": "",
                "nvidia_base_url": "",
                "ollama_api_key": "",
                "ollama_base_url": "https://ollama.com",
                "ollama_request_timeout_seconds": 60.0,
                "deepseek_api_key": "",
                "nesty_db_path": "data/nesty.db",
                "nesty_runtime_openai_providers_enabled": True,
            },
        )(),
    )
    providers = get_providers()
    assert "ollama_cloud" in providers
    assert "deepseek" in providers
    assert providers["ollama_cloud"].provider_name == "ollama_cloud"
    get_providers.cache_clear()
