from __future__ import annotations

from app.config import Settings, load_models_config


def _models_in_chain(chain) -> list[str]:
    return [item.model if hasattr(item, "model") else str(item["model"]) for item in chain]


def _providers_in_chain(chain) -> list[str]:
    return [item.provider if hasattr(item, "provider") else str(item["provider"]) for item in chain]


def test_flash_defaults_prioritize_groq_with_openrouter_and_nvidia_fallbacks() -> None:
    cfg = load_models_config().models["nesty-flash-1.0"]
    providers = _providers_in_chain(cfg.provider_chain)
    assert providers[0] == "groq"
    assert "openrouter" in providers
    assert "nvidia" in providers
    assert "ollama_cloud" in providers
    assert _models_in_chain(cfg.provider_chain) == [
        "llama-3.1-8b-instant",
        "google/gemma-4-26b-a4b-it:free",
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        "minimaxai/minimax-m2.7",
        "gemma3:12b",
    ]


def test_combined_defaults_prioritize_openrouter_before_groq() -> None:
    cfg = load_models_config().models["nesty-combined-1.0"]
    providers = _providers_in_chain(cfg.provider_chain)
    assert providers[0] == "openrouter"
    assert "groq" in providers
    assert providers.index("groq") > providers.index("openrouter")
    assert "nvidia" in providers
    assert "ollama_cloud" in providers
    assert _models_in_chain(cfg.provider_chain) == [
        "openrouter/owl-alpha",
        "poolside/laguna-m.1:free",
        "openai/gpt-oss-120b:free",
        "llama-3.3-70b-versatile",
        "stepfun-ai/step-3.7-flash",
        "nemotron-3-nano:30b",
    ]


def test_pro_main_chain_includes_openrouter_groq_and_nvidia() -> None:
    cfg = load_models_config().models["nesty-pro-1.0"]
    providers = _providers_in_chain(cfg.provider_chain)
    assert "openrouter" in providers
    assert "groq" in providers
    assert "nvidia" in providers
    assert "ollama_cloud" in providers
    assert _models_in_chain(cfg.provider_chain) == [
        "llama-3.3-70b-versatile",
        "moonshotai/kimi-k2.6:free",
        "openai/gpt-oss-120b:free",
        "mistralai/mistral-large-3-675b-instruct-2512",
        "minimax-m3",
    ]


def test_pro_orchestration_role_chains_match_defaults() -> None:
    cfg = load_models_config().models["nesty-pro-1.0"]
    roles = cfg.orchestration_roles

    planner_providers = _providers_in_chain(roles["planner"].provider_chain)
    researcher_providers = _providers_in_chain(roles["researcher"].provider_chain)
    critic_providers = _providers_in_chain(roles["critic"].provider_chain)
    finalizer_providers = _providers_in_chain(roles["finalizer"].provider_chain)

    assert planner_providers[0] == "groq"
    assert "openrouter" in researcher_providers
    assert "groq" in researcher_providers
    assert critic_providers[0] == "groq"
    assert "openrouter" in finalizer_providers
    assert "groq" in finalizer_providers
    assert "nvidia" in planner_providers
    assert "ollama_cloud" in planner_providers
    assert "ollama_cloud" in researcher_providers
    assert "ollama_cloud" in critic_providers
    assert "ollama_cloud" in finalizer_providers


def test_coding_and_embedding_candidates_not_in_default_chat_provider_chains() -> None:
    cfg = load_models_config()
    banned = {
        "qwen/qwen3-coder:free",
        "nvidia/llama-nemotron-embed-vl-1b-v2:free",
    }
    models = []

    for profile in cfg.models.values():
        models.extend(_models_in_chain(profile.provider_chain))
        for role in profile.orchestration_roles.values():
            models.extend(_models_in_chain(role.provider_chain))

    assert all(model not in banned for model in models)


def test_embedding_default_model_remains_openrouter_nemotron_embed() -> None:
    settings = Settings()
    assert settings.embeddings_provider == "openrouter"
    assert settings.embeddings_model == "nvidia/llama-nemotron-embed-vl-1b-v2:free"
