from __future__ import annotations

from app.deps import get_orchestrator, get_provider_router
from app.storage.db import init_db
from app.storage.model_configs import reset_model_override, upsert_model_override


def _runtime_settings(db_path: str):
    return type(
        "S",
        (),
        {
            "nesty_db_path": db_path,
            "request_timeout_seconds": 30.0,
            "enable_input_guard": True,
            "enable_output_guard": True,
            "groq_api_key": "",
            "openrouter_api_key": "",
            "nvidia_api_key": "",
            "nvidia_base_url": "",
            "ollama_api_key": "",
            "ollama_base_url": "https://ollama.com",
            "ollama_request_timeout_seconds": 30.0,
            "deepseek_api_key": "",
            "nesty_runtime_openai_providers_enabled": False,
            "trusted_hosts": "testserver",
        },
    )()


def test_runtime_model_override_refreshes_cached_router_and_orchestrator(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "runtime_model_config_refresh.db")
    init_db(db_path)
    settings = _runtime_settings(db_path)

    monkeypatch.setattr("app.deps.get_settings", lambda: settings)
    monkeypatch.setattr("app.storage.model_configs.get_settings", lambda: settings)

    get_provider_router.cache_clear()
    get_orchestrator.cache_clear()

    first_router = get_provider_router()
    first_orchestrator = get_orchestrator()
    first_profile = first_router.models_config.models["nesty-flash-1.0"]

    upsert_model_override(
        model_id="nesty-flash-1.0",
        config={"provider_chain": [{"provider": "openrouter", "model": "runtime-test-model"}]},
        db_path=db_path,
    )

    second_router = get_provider_router()
    second_orchestrator = get_orchestrator()
    second_profile = second_router.models_config.models["nesty-flash-1.0"]

    assert second_router is not first_router
    assert second_orchestrator is not first_orchestrator
    assert second_orchestrator.router is second_router
    assert second_profile.provider_chain[0].model == "runtime-test-model"

    reset_model_override("nesty-flash-1.0", db_path=db_path)

    third_router = get_provider_router()
    third_orchestrator = get_orchestrator()
    third_profile = third_router.models_config.models["nesty-flash-1.0"]

    assert third_router is not second_router
    assert third_orchestrator is not second_orchestrator
    assert third_orchestrator.router is third_router
    assert third_profile.provider_chain[0].provider == first_profile.provider_chain[0].provider
    assert third_profile.provider_chain[0].model == first_profile.provider_chain[0].model
