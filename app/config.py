from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


load_dotenv()


def _to_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_project_root() -> Path:
    return Path(__file__).resolve().parents[1]


class Settings(BaseModel):
    app_name: str = "NestyAI"
    app_version: str = "0.1.0"
    app_env: str = "development"
    request_timeout_seconds: float = 30.0
    enable_input_guard: bool = True
    enable_output_guard: bool = True
    groq_api_key: str | None = None
    openrouter_api_key: str | None = None
    nvidia_api_key: str | None = None
    nvidia_base_url: str | None = None
    weather_provider_api_key: str | None = None
    exchange_rate_api_key: str | None = None
    nesty_db_path: str = "data/nesty.db"
    nesty_api_key_hash_secret: str | None = None
    require_api_key: bool = False
    public_health: bool = True
    public_models: bool = True
    rate_limit_enabled: bool = True
    rate_limit_requests_per_minute: int = 60
    safe_debug_auth: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            app_name=os.getenv("APP_NAME", "NestyAI"),
            app_version=os.getenv("APP_VERSION", "0.1.0"),
            app_env=os.getenv("APP_ENV", "development"),
            request_timeout_seconds=float(os.getenv("REQUEST_TIMEOUT_SECONDS", "30")),
            enable_input_guard=_to_bool(os.getenv("ENABLE_INPUT_GUARD"), True),
            enable_output_guard=_to_bool(os.getenv("ENABLE_OUTPUT_GUARD"), True),
            groq_api_key=os.getenv("GROQ_API_KEY"),
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY"),
            nvidia_api_key=os.getenv("NVIDIA_API_KEY"),
            nvidia_base_url=os.getenv("NVIDIA_BASE_URL"),
            weather_provider_api_key=os.getenv("WEATHER_PROVIDER_API_KEY"),
            exchange_rate_api_key=os.getenv("EXCHANGE_RATE_API_KEY"),
            nesty_db_path=os.getenv("NESTY_DB_PATH", "data/nesty.db"),
            nesty_api_key_hash_secret=os.getenv("NESTY_API_KEY_HASH_SECRET"),
            require_api_key=_to_bool(os.getenv("REQUIRE_API_KEY"), False),
            public_health=_to_bool(os.getenv("PUBLIC_HEALTH"), True),
            public_models=_to_bool(os.getenv("PUBLIC_MODELS"), True),
            rate_limit_enabled=_to_bool(os.getenv("RATE_LIMIT_ENABLED"), True),
            rate_limit_requests_per_minute=int(os.getenv("RATE_LIMIT_REQUESTS_PER_MINUTE", "60")),
            safe_debug_auth=_to_bool(os.getenv("SAFE_DEBUG_AUTH"), False),
        )


class ProviderTarget(BaseModel):
    provider: str
    model: str


class ModelProfile(BaseModel):
    display_name: str
    description: str
    strategy: str
    search_mode: str
    max_tool_calls: int = 0
    tools_mode: str = "auto"
    allowed_tools: list[str] = Field(default_factory=list)
    max_search_results: int = 0
    max_context_chars: int = 2000
    provider_chain: list[ProviderTarget] = Field(default_factory=list)


class ModelsConfig(BaseModel):
    models: dict[str, ModelProfile] = Field(default_factory=dict)


def load_models_config(path: Path | None = None) -> ModelsConfig:
    config_path = path or (get_project_root() / "config" / "models.yaml")
    with config_path.open("r", encoding="utf-8") as file:
        raw = yaml.safe_load(file) or {}
    return ModelsConfig.model_validate(raw)


def load_guard_rules(path: Path | None = None) -> dict[str, Any]:
    config_path = path or (get_project_root() / "config" / "guard_rules.yaml")
    with config_path.open("r", encoding="utf-8") as file:
        raw = yaml.safe_load(file) or {}
    return raw
