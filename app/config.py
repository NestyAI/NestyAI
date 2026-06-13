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
    ollama_api_key: str | None = None
    ollama_base_url: str = "https://ollama.com"
    ollama_request_timeout_seconds: float = 60.0
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
    cors_enabled: bool = False
    cors_allow_origins: str = ""
    cors_allow_methods: str = "GET,POST,OPTIONS"
    cors_allow_headers: str = "Authorization,Content-Type,X-Nesty-API-Key"
    cors_allow_credentials: bool = False
    trusted_hosts: str = ""
    max_request_body_bytes: int = 1048576
    security_headers_enabled: bool = True
    enable_hsts: bool = False
    conversation_history_enabled: bool = True
    conversation_history_max_messages: int = 20
    conversation_history_max_chars: int = 12000
    conversation_summary_enabled: bool = True
    conversation_summary_trigger_messages: int = 30
    conversation_summary_keep_recent_messages: int = 12
    conversation_summary_max_chars: int = 4000
    conversation_summary_model: str = "nesty-flash-1.0"
    nesty_pro_orchestration_enabled: bool = True
    nesty_pro_orchestration_max_internal_calls: int = 4
    nesty_pro_orchestration_debug: bool = False
    nesty_pro_orchestration_complexity_min_score: int = 2
    nesty_pro_orchestration_simple_max_chars: int = 220
    nesty_pro_orchestration_max_context_chars: int = 12000
    nesty_pro_orchestration_role_timeout_seconds: float = 30.0
    nesty_pro_orchestration_include_role_latency: bool = True
    internal_admin_enabled: bool = False
    nesty_internal_admin_token: str | None = None
    nesty_internal_admin_token_mode: str = "env"
    internal_admin_token_file: str = ".nesty/internal_admin_token"
    nesty_print_bootstrap_admin_token: bool = False
    nesty_internal_admin_token_rotate_on_start: bool = False
    internal_admin_token_source: str | None = None
    internal_admin_token_file_resolved: str | None = None
    nesty_console_client_auth_required: bool = False
    nesty_console_client_id: str = "default-console"
    nesty_console_client_secret: str | None = None
    nesty_console_client_secret_mode: str = "env"
    nesty_console_client_secret_file: str = ".nesty/console_client_secret"
    nesty_print_bootstrap_console_secret: bool = False
    console_client_secret_source: str | None = None
    console_client_secret_file_resolved: str | None = None
    deepseek_api_key: str | None = None
    openai_api_key: str | None = None
    mistral_api_key: str | None = None
    z_ai_api_key: str | None = None
    z_ai_base_url: str = "https://api.z.ai/v1"
    google_gemini_api_key: str | None = None
    anthropic_claude_api_key: str | None = None
    nesty_provider_credentials_enabled: bool = False
    nesty_provider_credential_source_priority: str = "managed,secret_file,env"
    nesty_provider_secret_dir: str = ".nesty/provider_secrets"
    nesty_provider_credential_store: str = "sqlite"
    nesty_upstash_redis_rest_url: str | None = None
    nesty_upstash_redis_rest_token: str | None = None
    nesty_runtime_openai_providers_enabled: bool = True
    nesty_runtime_provider_secret_mode: str = "file"
    nesty_runtime_provider_secret_dir: str = ".nesty/provider_secrets"
    nesty_runtime_provider_allow_http: bool = False
    nesty_runtime_provider_allow_private_base_url: bool = False
    nesty_safety_policy_mode: str = "enforce"
    embeddings_enabled: bool = False
    embeddings_provider: str = "openrouter"
    embeddings_model: str = "nvidia/llama-nemotron-embed-vl-1b-v2:free"
    embeddings_dimensions: int | None = None
    embeddings_timeout_seconds: float = 30.0
    embeddings_max_input_chars: int = 8000
    embeddings_store_message_embeddings: bool = False
    embeddings_backfill_batch_size: int = 50
    semantic_recall_enabled: bool = False
    semantic_recall_top_k: int = 5
    semantic_recall_min_score: float = 0.72
    semantic_recall_max_context_chars: int = 4000
    semantic_recall_scope: str = "conversation"
    semantic_recall_include_roles: list[str] = Field(default_factory=lambda: ["user", "assistant"])
    semantic_recall_exclude_current_conversation_recent: bool = True
    semantic_recall_candidate_limit: int = 500
    semantic_recall_pinned_boost: float = 0.08
    semantic_recall_dedup_similarity: float = 0.96
    semantic_recall_max_per_conversation: int = 3
    semantic_recall_exclude_memory_excluded: bool = True
    diagnostics_enabled: bool = True
    diagnostics_default_timeout_seconds: float = 20.0
    diagnostics_test_max_tokens: int = 16
    diagnostics_save_results: bool = True
    diagnostics_output_preview_chars: int = 80
    provider_health_aware_routing: bool = False
    provider_health_strict_mode: bool = False
    provider_health_ttl_seconds: int = 900
    provider_health_failure_threshold: int = 2
    provider_health_skip_statuses: str = "failed,unavailable,timeout"
    provider_health_allow_stale_after_seconds: int = 3600
    provider_reliability_scoring_enabled: bool = True
    provider_reliability_window_checks: int = 20
    provider_reliability_min_checks: int = 3
    provider_reliability_recency_weight: float = 0.65
    provider_reliability_latency_weight: float = 0.20
    provider_reliability_stability_weight: float = 0.15
    provider_reliability_ok_score: float = 1.0
    provider_reliability_failed_score: float = 0.0
    provider_reliability_unavailable_score: float = 0.0
    provider_reliability_timeout_score: float = 0.0
    provider_reliability_skipped_score: float = 0.4

    @classmethod
    def from_env(cls) -> "Settings":
        ollama_base_url_raw = str(os.getenv("OLLAMA_BASE_URL", "https://ollama.com") or "").strip()
        ollama_base_url = (ollama_base_url_raw or "https://ollama.com").rstrip("/")
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
            ollama_api_key=os.getenv("OLLAMA_API_KEY"),
            ollama_base_url=ollama_base_url,
            ollama_request_timeout_seconds=float(os.getenv("OLLAMA_REQUEST_TIMEOUT_SECONDS", "60")),
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
            cors_enabled=_to_bool(os.getenv("CORS_ENABLED"), False),
            cors_allow_origins=os.getenv("CORS_ALLOW_ORIGINS", ""),
            cors_allow_methods=os.getenv("CORS_ALLOW_METHODS", "GET,POST,OPTIONS"),
            cors_allow_headers=os.getenv("CORS_ALLOW_HEADERS", "Authorization,Content-Type,X-Nesty-API-Key"),
            cors_allow_credentials=_to_bool(os.getenv("CORS_ALLOW_CREDENTIALS"), False),
            trusted_hosts=os.getenv("TRUSTED_HOSTS", ""),
            max_request_body_bytes=int(os.getenv("MAX_REQUEST_BODY_BYTES", "1048576")),
            security_headers_enabled=_to_bool(os.getenv("SECURITY_HEADERS_ENABLED"), True),
            enable_hsts=_to_bool(os.getenv("ENABLE_HSTS"), False),
            conversation_history_enabled=_to_bool(os.getenv("CONVERSATION_HISTORY_ENABLED"), True),
            conversation_history_max_messages=int(os.getenv("CONVERSATION_HISTORY_MAX_MESSAGES", "20")),
            conversation_history_max_chars=int(os.getenv("CONVERSATION_HISTORY_MAX_CHARS", "12000")),
            conversation_summary_enabled=_to_bool(os.getenv("CONVERSATION_SUMMARY_ENABLED"), True),
            conversation_summary_trigger_messages=int(os.getenv("CONVERSATION_SUMMARY_TRIGGER_MESSAGES", "30")),
            conversation_summary_keep_recent_messages=int(
                os.getenv("CONVERSATION_SUMMARY_KEEP_RECENT_MESSAGES", "12")
            ),
            conversation_summary_max_chars=int(os.getenv("CONVERSATION_SUMMARY_MAX_CHARS", "4000")),
            conversation_summary_model=os.getenv("CONVERSATION_SUMMARY_MODEL", "nesty-flash-1.0"),
            nesty_pro_orchestration_enabled=_to_bool(os.getenv("NESTY_PRO_ORCHESTRATION_ENABLED"), True),
            nesty_pro_orchestration_max_internal_calls=int(
                os.getenv("NESTY_PRO_ORCHESTRATION_MAX_INTERNAL_CALLS", "4")
            ),
            nesty_pro_orchestration_debug=_to_bool(os.getenv("NESTY_PRO_ORCHESTRATION_DEBUG"), False),
            nesty_pro_orchestration_complexity_min_score=int(
                os.getenv("NESTY_PRO_ORCHESTRATION_COMPLEXITY_MIN_SCORE", "2")
            ),
            nesty_pro_orchestration_simple_max_chars=int(
                os.getenv("NESTY_PRO_ORCHESTRATION_SIMPLE_MAX_CHARS", "220")
            ),
            nesty_pro_orchestration_max_context_chars=int(
                os.getenv("NESTY_PRO_ORCHESTRATION_MAX_CONTEXT_CHARS", "12000")
            ),
            nesty_pro_orchestration_role_timeout_seconds=float(
                os.getenv("NESTY_PRO_ORCHESTRATION_ROLE_TIMEOUT_SECONDS", "30")
            ),
            nesty_pro_orchestration_include_role_latency=_to_bool(
                os.getenv("NESTY_PRO_ORCHESTRATION_INCLUDE_ROLE_LATENCY"), True
            ),
            internal_admin_enabled=_to_bool(os.getenv("INTERNAL_ADMIN_ENABLED"), False),
            nesty_internal_admin_token=os.getenv("NESTY_INTERNAL_ADMIN_TOKEN"),
            nesty_internal_admin_token_mode=os.getenv("NESTY_INTERNAL_ADMIN_TOKEN_MODE", "env"),
            internal_admin_token_file=os.getenv("INTERNAL_ADMIN_TOKEN_FILE", ".nesty/internal_admin_token"),
            nesty_print_bootstrap_admin_token=_to_bool(os.getenv("NESTY_PRINT_BOOTSTRAP_ADMIN_TOKEN"), False),
            nesty_internal_admin_token_rotate_on_start=_to_bool(
                os.getenv("NESTY_INTERNAL_ADMIN_TOKEN_ROTATE_ON_START"), False
            ),
            nesty_console_client_auth_required=_to_bool(os.getenv("NESTY_CONSOLE_CLIENT_AUTH_REQUIRED"), False),
            nesty_console_client_id=os.getenv("NESTY_CONSOLE_CLIENT_ID", "default-console"),
            nesty_console_client_secret=os.getenv("NESTY_CONSOLE_CLIENT_SECRET"),
            nesty_console_client_secret_mode=os.getenv("NESTY_CONSOLE_CLIENT_SECRET_MODE", "env"),
            nesty_console_client_secret_file=os.getenv("NESTY_CONSOLE_CLIENT_SECRET_FILE", ".nesty/console_client_secret"),
            nesty_print_bootstrap_console_secret=_to_bool(os.getenv("NESTY_PRINT_BOOTSTRAP_CONSOLE_SECRET"), False),
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY"),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            mistral_api_key=os.getenv("MISTRAL_API_KEY"),
            z_ai_api_key=os.getenv("Z_AI_API_KEY"),
            z_ai_base_url=str(os.getenv("Z_AI_BASE_URL", "https://api.z.ai/v1") or "https://api.z.ai/v1").rstrip("/"),
            google_gemini_api_key=os.getenv("GOOGLE_GEMINI_API_KEY"),
            anthropic_claude_api_key=os.getenv("ANTHROPIC_API_KEY"),
            nesty_provider_credentials_enabled=_to_bool(os.getenv("NESTY_PROVIDER_CREDENTIALS_ENABLED"), False),
            nesty_provider_credential_source_priority=os.getenv(
                "NESTY_PROVIDER_CREDENTIAL_SOURCE_PRIORITY", "managed,secret_file,env"
            ),
            nesty_provider_secret_dir=os.getenv("NESTY_PROVIDER_SECRET_DIR", ".nesty/provider_secrets"),
            nesty_provider_credential_store=os.getenv("NESTY_PROVIDER_CREDENTIAL_STORE", "sqlite"),
            nesty_upstash_redis_rest_url=os.getenv("NESTY_UPSTASH_REDIS_REST_URL"),
            nesty_upstash_redis_rest_token=os.getenv("NESTY_UPSTASH_REDIS_REST_TOKEN"),
            nesty_runtime_openai_providers_enabled=_to_bool(os.getenv("NESTY_RUNTIME_OPENAI_PROVIDERS_ENABLED"), True),
            nesty_runtime_provider_secret_mode=os.getenv("NESTY_RUNTIME_PROVIDER_SECRET_MODE", "file"),
            nesty_runtime_provider_secret_dir=os.getenv("NESTY_RUNTIME_PROVIDER_SECRET_DIR", ".nesty/provider_secrets"),
            nesty_runtime_provider_allow_http=_to_bool(os.getenv("NESTY_RUNTIME_PROVIDER_ALLOW_HTTP"), False),
            nesty_runtime_provider_allow_private_base_url=_to_bool(
                os.getenv("NESTY_RUNTIME_PROVIDER_ALLOW_PRIVATE_BASE_URL"), False
            ),
            nesty_safety_policy_mode=str(os.getenv("NESTY_SAFETY_POLICY_MODE", "enforce") or "enforce").strip().lower(),
            embeddings_enabled=_to_bool(os.getenv("EMBEDDINGS_ENABLED"), False),
            embeddings_provider=os.getenv("EMBEDDINGS_PROVIDER", "openrouter"),
            embeddings_model=os.getenv("EMBEDDINGS_MODEL", "nvidia/llama-nemotron-embed-vl-1b-v2:free"),
            embeddings_dimensions=(
                int(os.getenv("EMBEDDINGS_DIMENSIONS", "").strip())
                if str(os.getenv("EMBEDDINGS_DIMENSIONS", "")).strip()
                else None
            ),
            embeddings_timeout_seconds=float(os.getenv("EMBEDDINGS_TIMEOUT_SECONDS", "30")),
            embeddings_max_input_chars=int(os.getenv("EMBEDDINGS_MAX_INPUT_CHARS", "8000")),
            embeddings_store_message_embeddings=_to_bool(os.getenv("EMBEDDINGS_STORE_MESSAGE_EMBEDDINGS"), False),
            embeddings_backfill_batch_size=int(os.getenv("EMBEDDINGS_BACKFILL_BATCH_SIZE", "50")),
            semantic_recall_enabled=_to_bool(os.getenv("SEMANTIC_RECALL_ENABLED"), False),
            semantic_recall_top_k=int(os.getenv("SEMANTIC_RECALL_TOP_K", "5")),
            semantic_recall_min_score=float(os.getenv("SEMANTIC_RECALL_MIN_SCORE", "0.72")),
            semantic_recall_max_context_chars=int(os.getenv("SEMANTIC_RECALL_MAX_CONTEXT_CHARS", "4000")),
            semantic_recall_scope=os.getenv("SEMANTIC_RECALL_SCOPE", "conversation"),
            semantic_recall_include_roles=[
                item.strip()
                for item in str(os.getenv("SEMANTIC_RECALL_INCLUDE_ROLES", "user,assistant")).split(",")
                if item.strip()
            ],
            semantic_recall_exclude_current_conversation_recent=_to_bool(
                os.getenv("SEMANTIC_RECALL_EXCLUDE_CURRENT_CONVERSATION_RECENT"), True
            ),
            semantic_recall_candidate_limit=int(os.getenv("SEMANTIC_RECALL_CANDIDATE_LIMIT", "500")),
            semantic_recall_pinned_boost=float(os.getenv("SEMANTIC_RECALL_PINNED_BOOST", "0.08")),
            semantic_recall_dedup_similarity=float(os.getenv("SEMANTIC_RECALL_DEDUP_SIMILARITY", "0.96")),
            semantic_recall_max_per_conversation=int(os.getenv("SEMANTIC_RECALL_MAX_PER_CONVERSATION", "3")),
            semantic_recall_exclude_memory_excluded=_to_bool(
                os.getenv("SEMANTIC_RECALL_EXCLUDE_MEMORY_EXCLUDED"), True
            ),
            diagnostics_enabled=_to_bool(os.getenv("DIAGNOSTICS_ENABLED"), True),
            diagnostics_default_timeout_seconds=float(os.getenv("DIAGNOSTICS_DEFAULT_TIMEOUT_SECONDS", "20")),
            diagnostics_test_max_tokens=int(os.getenv("DIAGNOSTICS_TEST_MAX_TOKENS", "16")),
            diagnostics_save_results=_to_bool(os.getenv("DIAGNOSTICS_SAVE_RESULTS"), True),
            diagnostics_output_preview_chars=int(os.getenv("DIAGNOSTICS_OUTPUT_PREVIEW_CHARS", "80")),
            provider_health_aware_routing=_to_bool(os.getenv("PROVIDER_HEALTH_AWARE_ROUTING"), False),
            provider_health_strict_mode=_to_bool(os.getenv("PROVIDER_HEALTH_STRICT_MODE"), False),
            provider_health_ttl_seconds=int(os.getenv("PROVIDER_HEALTH_TTL_SECONDS", "900")),
            provider_health_failure_threshold=int(os.getenv("PROVIDER_HEALTH_FAILURE_THRESHOLD", "2")),
            provider_health_skip_statuses=os.getenv("PROVIDER_HEALTH_SKIP_STATUSES", "failed,unavailable,timeout"),
            provider_health_allow_stale_after_seconds=int(
                os.getenv("PROVIDER_HEALTH_ALLOW_STALE_AFTER_SECONDS", "3600")
            ),
            provider_reliability_scoring_enabled=_to_bool(os.getenv("PROVIDER_RELIABILITY_SCORING_ENABLED"), True),
            provider_reliability_window_checks=int(os.getenv("PROVIDER_RELIABILITY_WINDOW_CHECKS", "20")),
            provider_reliability_min_checks=int(os.getenv("PROVIDER_RELIABILITY_MIN_CHECKS", "3")),
            provider_reliability_recency_weight=float(os.getenv("PROVIDER_RELIABILITY_RECENCY_WEIGHT", "0.65")),
            provider_reliability_latency_weight=float(os.getenv("PROVIDER_RELIABILITY_LATENCY_WEIGHT", "0.20")),
            provider_reliability_stability_weight=float(os.getenv("PROVIDER_RELIABILITY_STABILITY_WEIGHT", "0.15")),
            provider_reliability_ok_score=float(os.getenv("PROVIDER_RELIABILITY_OK_SCORE", "1.0")),
            provider_reliability_failed_score=float(os.getenv("PROVIDER_RELIABILITY_FAILED_SCORE", "0.0")),
            provider_reliability_unavailable_score=float(os.getenv("PROVIDER_RELIABILITY_UNAVAILABLE_SCORE", "0.0")),
            provider_reliability_timeout_score=float(os.getenv("PROVIDER_RELIABILITY_TIMEOUT_SCORE", "0.0")),
            provider_reliability_skipped_score=float(os.getenv("PROVIDER_RELIABILITY_SKIPPED_SCORE", "0.4")),
        )


class ProviderTarget(BaseModel):
    provider: str
    model: str


class OrchestrationRoleConfig(BaseModel):
    enabled: bool = True
    provider_chain: list[ProviderTarget] = Field(default_factory=list)
    temperature: float | None = None
    max_tokens: int | None = None
    timeout_seconds: float | None = None


class ModelProfile(BaseModel):
    display_name: str
    description: str
    strategy: str
    search_mode: str
    behavior_profile: str = "balanced"
    response_style: str = "balanced"
    reasoning_depth: str = "medium"
    search_aggressiveness: str = "auto"
    tool_aggressiveness: str = "auto"
    default_temperature: float = 0.7
    default_max_tokens: int = 1024
    orchestration_enabled: bool = False
    orchestration_mode: str = "single"
    max_tool_calls: int = 0
    tools_mode: str = "auto"
    allowed_tools: list[str] = Field(default_factory=list)
    max_search_results: int = 0
    max_context_chars: int = 2000
    provider_chain: list[ProviderTarget] = Field(default_factory=list)
    orchestration_roles: dict[str, OrchestrationRoleConfig] = Field(default_factory=dict)


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
