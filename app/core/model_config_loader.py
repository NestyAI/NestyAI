from __future__ import annotations

from typing import Any

from app.config import ModelsConfig, load_models_config
from app.storage.model_configs import get_model_override, list_model_overrides
from app.utils.logging import get_logger, log_safe


from app.core.runtime_providers.validation import get_supported_chat_provider_ids
ALLOWED_OVERRIDE_FIELDS = {
    "display_name",
    "behavior_profile",
    "response_style",
    "reasoning_depth",
    "search_aggressiveness",
    "tool_aggressiveness",
    "default_temperature",
    "default_max_tokens",
    "max_tool_calls",
    "max_search_results",
    "provider_chain",
    "orchestration_enabled",
    "orchestration_mode",
    "orchestration_roles",
}
SECRET_HINT_PATTERNS = [
    "api_key",
    "apikey",
    "secret",
    "token",
    "-----begin",
    "bearer ",
    "sk-",
]
logger = get_logger("nesty.model_config_loader")


def load_default_model_configs() -> dict[str, dict[str, Any]]:
    config: ModelsConfig = load_models_config()
    return {model_id: profile.model_dump() for model_id, profile in config.models.items()}


def get_default_model_config(model_id: str) -> dict[str, Any] | None:
    defaults = load_default_model_configs()
    model = defaults.get(model_id)
    if model is None:
        return None
    return dict(model)


def merge_model_config(default_config: dict[str, Any], override_config: dict[str, Any]) -> dict[str, Any]:
    merged = dict(default_config)
    for key, value in override_config.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_model_config(dict(merged[key]), value)
        elif isinstance(value, list):
            merged[key] = list(value)
        else:
            merged[key] = value
    return merged


def validate_model_config_override(model_id: str, override_config: dict[str, Any]) -> tuple[bool, str | None]:
    default = get_default_model_config(model_id)
    if default is None:
        return False, "model_config_not_found"
    if not isinstance(override_config, dict) or not override_config:
        return False, "model_config_invalid"

    for key in override_config:
        if key not in ALLOWED_OVERRIDE_FIELDS:
            return False, f"model_config_invalid: field '{key}' is not allowed"

    if "provider_chain" in override_config:
        ok, error = _validate_provider_chain(override_config.get("provider_chain"))
        if not ok:
            return False, error

    if "orchestration_roles" in override_config:
        roles = override_config.get("orchestration_roles")
        if not isinstance(roles, dict):
            return False, "model_config_invalid: orchestration_roles must be an object"
        for role_name, role_cfg in roles.items():
            if not isinstance(role_cfg, dict):
                return False, f"model_config_invalid: orchestration role '{role_name}' must be an object"
            if "provider_chain" in role_cfg:
                ok, error = _validate_provider_chain(role_cfg.get("provider_chain"))
                if not ok:
                    return False, error

    for number_field in ["default_temperature", "default_max_tokens", "max_tool_calls", "max_search_results"]:
        if number_field not in override_config:
            continue
        value = override_config[number_field]
        if not isinstance(value, (int, float)):
            return False, f"model_config_invalid: field '{number_field}' must be numeric"
        if number_field == "default_temperature" and not (0.0 <= float(value) <= 2.0):
            return False, "model_config_invalid: default_temperature out of range"
        if number_field != "default_temperature" and int(value) < 0:
            return False, f"model_config_invalid: field '{number_field}' must be >= 0"

    if _contains_secret_like_value(override_config):
        return False, "model_config_invalid: secret-like value is not allowed"
    return True, None


def get_effective_model_config(model_id: str) -> dict[str, Any] | None:
    default = get_default_model_config(model_id)
    if default is None:
        return None
    try:
        override = get_model_override(model_id)
    except Exception:
        log_safe(logger, "model_override_read_failed", model_id=model_id)
        return dict(default)
    if not override:
        return dict(default)
    override_config = override.get("config")
    if not isinstance(override_config, dict):
        return dict(default)
    valid, _error = validate_model_config_override(model_id, override_config)
    if not valid:
        return dict(default)
    return merge_model_config(default, override_config)


def list_effective_model_configs() -> list[dict[str, Any]]:
    defaults = load_default_model_configs()
    try:
        active_overrides = {item["model_id"]: item for item in list_model_overrides()}
    except Exception:
        log_safe(logger, "model_override_list_failed")
        active_overrides = {}
    items: list[dict[str, Any]] = []
    for model_id, default_config in defaults.items():
        override_row = active_overrides.get(model_id)
        override_config = override_row.get("config") if override_row else None
        source = "default"
        effective = dict(default_config)
        if isinstance(override_config, dict):
            valid, _error = validate_model_config_override(model_id, override_config)
            if valid:
                effective = merge_model_config(default_config, override_config)
                source = "override"
            else:
                override_config = None
        items.append(
            {
                "model_id": model_id,
                "default_config": dict(default_config),
                "override_config": override_config,
                "effective_config": effective,
                "config_source": source,
            }
        )
    return items


def _validate_provider_chain(provider_chain: Any) -> tuple[bool, str | None]:
    if not isinstance(provider_chain, list) or not provider_chain:
        return False, "model_config_invalid: provider_chain must be a non-empty array"
    for item in provider_chain:
        if not isinstance(item, dict):
            return False, "model_config_invalid: provider_chain entries must be objects"
        provider = str(item.get("provider") or "").strip()
        model = str(item.get("model") or "").strip()
        if provider not in get_supported_chat_provider_ids():
            return False, f"model_config_invalid: unsupported provider '{provider}'"
        if not model:
            return False, "model_config_invalid: provider_chain model must be non-empty"
        # Chat provider chains must not use embedding-oriented model IDs.
        if "embed" in model.lower():
            return False, "model_config_invalid: embedding model IDs are not allowed in chat provider chains"
    return True, None


def _contains_secret_like_value(payload: Any) -> bool:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if str(key).strip().lower() in {"id", "model_id"}:
                return True
            if _contains_secret_like_value(value):
                return True
        return False
    if isinstance(payload, list):
        return any(_contains_secret_like_value(item) for item in payload)
    if isinstance(payload, str):
        lowered = payload.strip().lower()
        if len(lowered) >= 24 and any(pattern in lowered for pattern in SECRET_HINT_PATTERNS):
            return True
        if lowered.startswith("sk-"):
            return True
    return False
