from __future__ import annotations

from functools import lru_cache

from app.config import ModelsConfig, Settings, load_guard_rules, load_models_config
from app.core.model_config_loader import list_effective_model_configs
from app.core.orchestrator import ChatOrchestrator
from app.core.router import ProviderRouter
from app.guards.context_guard import ContextGuard
from app.guards.input_guard import InputGuard
from app.guards.output_guard import OutputGuard
from app.providers.base import BaseProvider
from app.providers.registry import build_all_chat_providers
from app.tools.registry import tool_registry
from app.utils.logging import get_logger


_RUNTIME_SETTINGS_OVERRIDE: Settings | None = None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    if _RUNTIME_SETTINGS_OVERRIDE is not None:
        return _RUNTIME_SETTINGS_OVERRIDE
    return Settings.from_env()


def set_runtime_settings(settings: Settings | None) -> None:
    global _RUNTIME_SETTINGS_OVERRIDE
    _RUNTIME_SETTINGS_OVERRIDE = settings
    cache_clear = getattr(get_settings, "cache_clear", None)
    if callable(cache_clear):
        cache_clear()


def get_models_config() -> ModelsConfig:
    try:
        rows = list_effective_model_configs()
        raw_models = {str(item["model_id"]): dict(item["effective_config"]) for item in rows}
        return ModelsConfig.model_validate({"models": raw_models})
    except Exception:
        return load_models_config()


@lru_cache(maxsize=1)
def get_guard_rules() -> dict:
    return load_guard_rules()


@lru_cache(maxsize=1)
def get_providers() -> dict[str, BaseProvider]:
    settings = get_settings()
    return build_all_chat_providers(settings)


@lru_cache(maxsize=1)
def get_provider_router() -> ProviderRouter:
    logger = get_logger("nesty.router")
    settings = get_settings()
    return ProviderRouter(
        models_config=get_models_config(),
        providers=get_providers(),
        logger=logger,
        settings=settings,
    )


@lru_cache(maxsize=1)
def get_orchestrator() -> ChatOrchestrator:
    settings = get_settings()
    rules = get_guard_rules()
    tool_registry.apply_cache_config(rules.get("tool_cache", {}))
    logger = get_logger("nesty.orchestrator")
    return ChatOrchestrator(
        router=get_provider_router(),
        input_guard=InputGuard(rules=rules),
        output_guard=OutputGuard(rules=rules),
        context_guard=ContextGuard(rules=rules),
        models_config=get_models_config(),
        tool_registry=tool_registry,
        guard_rules=rules,
        settings=settings,
        enable_input_guard=settings.enable_input_guard,
        enable_output_guard=settings.enable_output_guard,
        logger=logger,
    )


def clear_runtime_model_config_caches() -> None:
    """Drop cached dependency objects that embed resolved model configs.

    Model config overrides are read from SQLite at runtime. When an override is
    patched or reset, any cached router/orchestrator objects must be rebuilt so
    diagnostics and health checks observe the fresh effective config immediately.
    """

    get_providers.cache_clear()
    get_provider_router.cache_clear()
    get_orchestrator.cache_clear()
