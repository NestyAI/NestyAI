from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import ModelProfile, OrchestrationRoleConfig, ProviderTarget

SUPPORTED_ORCHESTRATION_ROLE_IDS: tuple[str, ...] = ("planner", "researcher", "critic", "finalizer")
REQUIRED_ORCHESTRATION_ROLE_IDS: tuple[str, ...] = ("planner", "finalizer")
OPTIONAL_ORCHESTRATION_ROLE_IDS: tuple[str, ...] = ("researcher", "critic")

DEFAULT_ROLE_MAX_TOKENS: dict[str, int] = {
    "planner": 512,
    "critic": 768,
    "researcher": 2048,
    "finalizer": 2048,
}

ROLE_CONFIG_FIELDS: frozenset[str] = frozenset(
    {"enabled", "provider_chain", "temperature", "max_tokens", "timeout_seconds"}
)

TEMPERATURE_MIN = 0.0
TEMPERATURE_MAX = 2.0
MAX_TOKENS_MIN = 128
MAX_TOKENS_MAX = 8192
TIMEOUT_SECONDS_MIN = 1.0
TIMEOUT_SECONDS_MAX = 120.0


@dataclass(frozen=True)
class ResolvedRoleConfig:
    role_id: str
    enabled: bool
    provider_chain: list[ProviderTarget]
    temperature: float
    max_tokens: int
    timeout_seconds: float


def is_supported_orchestration_role(role_id: str) -> bool:
    return role_id in SUPPORTED_ORCHESTRATION_ROLE_IDS


def is_required_orchestration_role(role_id: str) -> bool:
    return role_id in REQUIRED_ORCHESTRATION_ROLE_IDS


def role_is_enabled(role_cfg: Any) -> bool:
    if role_cfg is None:
        return False
    if isinstance(role_cfg, dict):
        enabled = role_cfg.get("enabled", True)
    elif isinstance(role_cfg, OrchestrationRoleConfig):
        enabled = role_cfg.enabled
    else:
        enabled = getattr(role_cfg, "enabled", True)
    return bool(enabled) if enabled is not None else True


def get_default_role_config_template() -> dict[str, dict[str, Any]]:
    template: dict[str, dict[str, Any]] = {}
    for role_id in SUPPORTED_ORCHESTRATION_ROLE_IDS:
        entry: dict[str, Any] = {
            "enabled": True,
            "provider_chain": [],
            "temperature": None,
            "max_tokens": DEFAULT_ROLE_MAX_TOKENS.get(role_id, 1024),
            "timeout_seconds": None,
        }
        template[role_id] = entry
    return template


def build_orchestration_console_view(model_id: str) -> dict[str, Any] | None:
    from app.core.model_config_loader import get_default_model_config, get_effective_model_config
    from app.storage.model_configs import get_model_override

    default_config = get_default_model_config(model_id)
    if default_config is None:
        return None
    effective = get_effective_model_config(model_id) or default_config
    override_row = get_model_override(model_id)
    override_config = override_row.get("config") if override_row else None
    override_roles: dict[str, Any] = {}
    if isinstance(override_config, dict):
        raw_roles = override_config.get("orchestration_roles")
        if isinstance(raw_roles, dict):
            override_roles = sanitize_roles_config(raw_roles)

    default_roles = sanitize_roles_config(default_config.get("orchestration_roles"))
    effective_roles = sanitize_roles_config(effective.get("orchestration_roles"))

    return {
        "model_id": model_id,
        "orchestration_enabled": bool(effective.get("orchestration_enabled", False)),
        "orchestration_mode": str(effective.get("orchestration_mode") or "single"),
        "supported_role_ids": list(SUPPORTED_ORCHESTRATION_ROLE_IDS),
        "required_role_ids": list(REQUIRED_ORCHESTRATION_ROLE_IDS),
        "default_role_config": get_default_role_config_template(),
        "default_roles": default_roles,
        "effective_roles": effective_roles,
        "override_roles": override_roles,
        "orchestration": {
            "mode": str(effective.get("orchestration_mode") or "single"),
            "roles": effective_roles,
        },
    }


PROVIDER_ENV_VAR_BY_ID: dict[str, str] = {
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
    "ollama_cloud": "OLLAMA_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "openai": "OPENAI_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "z_ai": "Z_AI_API_KEY",
    "google_gemini": "GOOGLE_GEMINI_API_KEY",
    "anthropic_claude": "ANTHROPIC_API_KEY",
}


def collect_orchestration_credential_warnings(settings: Any) -> list[str]:
    from app.core.model_config_loader import get_effective_model_config

    warnings: list[str] = []
    s = settings
    model_id = "nesty-pro-1.0"
    effective = get_effective_model_config(model_id)
    if not effective or not effective.get("orchestration_roles"):
        return warnings
    roles = effective.get("orchestration_roles") or {}
    for role_id, role_cfg in roles.items():
        if not isinstance(role_cfg, dict):
            continue
        if role_cfg.get("enabled") is False:
            continue
        chain = role_cfg.get("provider_chain") or []
        if not isinstance(chain, list) or not chain:
            chain = effective.get("provider_chain") or []
        if not chain:
            continue
        primary = chain[0] if isinstance(chain[0], dict) else {}
        provider_id = str(primary.get("provider") or "").strip()
        env_var = PROVIDER_ENV_VAR_BY_ID.get(provider_id)
        if not env_var:
            continue
        attr_map = {
            "GROQ_API_KEY": "groq_api_key",
            "OPENROUTER_API_KEY": "openrouter_api_key",
            "NVIDIA_API_KEY": "nvidia_api_key",
            "OLLAMA_API_KEY": "ollama_api_key",
            "DEEPSEEK_API_KEY": "deepseek_api_key",
            "OPENAI_API_KEY": "openai_api_key",
            "MISTRAL_API_KEY": "mistral_api_key",
            "Z_AI_API_KEY": "z_ai_api_key",
            "GOOGLE_GEMINI_API_KEY": "google_gemini_api_key",
            "ANTHROPIC_API_KEY": "anthropic_claude_api_key",
        }
        value = getattr(s, attr_map.get(env_var, ""), None)
        if not value or not str(value).strip():
            warnings.append(
                f"{env_var} is missing for orchestration role '{role_id}' primary provider '{provider_id}'"
            )
    return warnings


def validate_orchestration_role_credentials(settings: Any | None = None) -> list[dict[str, Any]]:
    from app.deps import get_settings

    s = settings or get_settings()
    results: list[dict[str, Any]] = []
    for warning in collect_orchestration_credential_warnings(s):
        results.append(
            {
                "name": f"orchestration_role_credential_{len(results)}",
                "status": "WARN",
                "message": warning,
            }
        )
    if not results:
        results.append(
            {
                "name": "orchestration_role_credentials",
                "status": "PASS",
                "message": "Orchestration role primary providers have configured credentials or use runtime providers.",
            }
        )
    return results


def sanitize_role_config_dict(role_cfg: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(role_cfg, dict):
        return {}
    return {key: role_cfg[key] for key in ROLE_CONFIG_FIELDS if key in role_cfg}


def sanitize_roles_config(roles: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(roles, dict):
        return {}
    sanitized: dict[str, dict[str, Any]] = {}
    for role_id, role_cfg in roles.items():
        if not is_supported_orchestration_role(str(role_id)):
            continue
        if isinstance(role_cfg, dict):
            sanitized[str(role_id)] = sanitize_role_config_dict(role_cfg)
        elif isinstance(role_cfg, OrchestrationRoleConfig):
            sanitized[str(role_id)] = sanitize_role_config_dict(role_cfg.model_dump())
    return sanitized


def resolve_role_provider_chain(
    role_id: str,
    role_cfg: OrchestrationRoleConfig | dict[str, Any] | None,
    model_profile: ModelProfile,
) -> list[ProviderTarget]:
    chain: list[ProviderTarget] = []
    if isinstance(role_cfg, OrchestrationRoleConfig):
        chain = list(role_cfg.provider_chain or [])
    elif isinstance(role_cfg, dict):
        raw_chain = role_cfg.get("provider_chain")
        if isinstance(raw_chain, list) and raw_chain:
            chain = [ProviderTarget.model_validate(item) for item in raw_chain if isinstance(item, dict)]
    if chain:
        return chain
    return list(model_profile.provider_chain or [])


def resolve_effective_role_config(
    role_id: str,
    role_cfg: OrchestrationRoleConfig | dict[str, Any] | None,
    model_profile: ModelProfile,
    *,
    request_temperature: float,
    request_max_tokens: int,
    global_timeout_seconds: float,
) -> ResolvedRoleConfig:
    cfg_dict: dict[str, Any] = {}
    if isinstance(role_cfg, OrchestrationRoleConfig):
        cfg_dict = role_cfg.model_dump()
    elif isinstance(role_cfg, dict):
        cfg_dict = dict(role_cfg)

    enabled = bool(cfg_dict.get("enabled", True))
    provider_chain = resolve_role_provider_chain(role_id, role_cfg, model_profile)

    role_temperature = cfg_dict.get("temperature")
    if isinstance(role_temperature, (int, float)):
        temperature = float(role_temperature)
    else:
        temperature = float(request_temperature)

    bounded_request_max = max(MAX_TOKENS_MIN, int(request_max_tokens))
    default_cap = DEFAULT_ROLE_MAX_TOKENS.get(role_id, 1024)
    role_max_tokens = cfg_dict.get("max_tokens")
    if isinstance(role_max_tokens, int) and role_max_tokens > 0:
        resolved_max = min(int(role_max_tokens), bounded_request_max)
    else:
        resolved_max = min(default_cap, bounded_request_max)
    resolved_max = max(MAX_TOKENS_MIN, resolved_max)

    role_timeout = cfg_dict.get("timeout_seconds")
    if isinstance(role_timeout, (int, float)) and float(role_timeout) > 0:
        timeout_seconds = float(role_timeout)
    else:
        timeout_seconds = float(global_timeout_seconds)
    timeout_seconds = max(TIMEOUT_SECONDS_MIN, min(TIMEOUT_SECONDS_MAX, timeout_seconds))

    return ResolvedRoleConfig(
        role_id=role_id,
        enabled=enabled,
        provider_chain=provider_chain,
        temperature=max(TEMPERATURE_MIN, min(TEMPERATURE_MAX, float(temperature))),
        max_tokens=resolved_max,
        timeout_seconds=timeout_seconds,
    )


def select_roles_for_run(
    roles_cfg: dict[str, Any],
    complexity_score: int,
    complexity_threshold: int,
    max_internal_calls: int,
) -> list[str]:
    available: list[str] = []
    for role_id in SUPPORTED_ORCHESTRATION_ROLE_IDS:
        if role_id not in roles_cfg:
            continue
        if not role_is_enabled(roles_cfg.get(role_id)):
            continue
        available.append(role_id)

    if "planner" not in available or "finalizer" not in available:
        return []

    full_optional = {"researcher", "critic"}.issubset(set(available))
    high_complexity = complexity_score >= (complexity_threshold + 2)
    if high_complexity and max_internal_calls >= 4 and full_optional:
        return ["planner", "researcher", "critic", "finalizer"]

    return ["planner", "finalizer"][:max_internal_calls]
