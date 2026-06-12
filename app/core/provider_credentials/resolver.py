from __future__ import annotations

import os
from typing import Any

from app.core.provider_credentials.secrets import read_builtin_provider_secret
from app.core.provider_credentials.store import get_provider_credential
from app.core.provider_credentials.models import SecretStatus


# Maps built-in provider_id -> (Settings attribute name, env var name)
BUILTIN_API_KEY_BINDINGS: dict[str, tuple[str, str]] = {
    "groq": ("groq_api_key", "GROQ_API_KEY"),
    "openrouter": ("openrouter_api_key", "OPENROUTER_API_KEY"),
    "nvidia": ("nvidia_api_key", "NVIDIA_API_KEY"),
    "ollama_cloud": ("ollama_api_key", "OLLAMA_API_KEY"),
    "deepseek": ("deepseek_api_key", "DEEPSEEK_API_KEY"),
    "openai": ("openai_api_key", "OPENAI_API_KEY"),
    "mistral": ("mistral_api_key", "MISTRAL_API_KEY"),
    "z_ai": ("z_ai_api_key", "Z_AI_API_KEY"),
    "google_gemini": ("google_gemini_api_key", "GOOGLE_GEMINI_API_KEY"),
    "anthropic_claude": ("anthropic_claude_api_key", "ANTHROPIC_API_KEY"),
}


def parse_source_priority(raw: str | None) -> list[str]:
    default = ["managed", "secret_file", "env"]
    if not raw:
        return default
    items = [part.strip().lower() for part in str(raw).split(",") if part.strip()]
    normalized: list[str] = []
    for item in items:
        if item == "managed_store":
            item = "managed"
        if item in {"managed", "secret_file", "env"} and item not in normalized:
            normalized.append(item)
    return normalized or default


def credentials_feature_enabled(settings: Any) -> bool:
    return bool(getattr(settings, "nesty_provider_credentials_enabled", False))


def _resolve_env_api_key(settings: Any, provider_id: str) -> tuple[str | None, SecretStatus]:
    binding = BUILTIN_API_KEY_BINDINGS.get(provider_id)
    if binding is None:
        return None, "missing"
    attr_name, env_name = binding
    value = getattr(settings, attr_name, None)
    if value is not None and str(value).strip():
        return str(value).strip(), "env_ref"
    env_value = os.getenv(env_name)
    if env_value is not None and str(env_value).strip():
        return str(env_value).strip(), "env_ref"
    return None, "missing"


def _resolve_secret_file_api_key(settings: Any, provider_id: str) -> tuple[str | None, SecretStatus]:
    value = read_builtin_provider_secret(settings, provider_id)
    if value:
        return value, "stored"
    return None, "missing"


def _resolve_managed_api_key(
    settings: Any,
    provider_id: str,
    *,
    db_path: str | None = None,
) -> tuple[str | None, SecretStatus]:
    record = get_provider_credential(provider_id, db_path=db_path, settings=settings)
    if record is None or not record.enabled:
        return None, "missing"
    if record.source != "managed_store":
        return None, "missing"
    value = read_builtin_provider_secret(settings, provider_id, record.secret_ref)
    if value:
        return value, "managed"
    return None, "missing"


def resolve_builtin_provider_api_key(
    provider_id: str,
    settings: Any,
    *,
    db_path: str | None = None,
) -> tuple[str | None, SecretStatus]:
    """Resolve built-in provider API key.

    When NESTY_PROVIDER_CREDENTIALS_ENABLED=false (default), only env/settings keys
    are used — preserving existing v1.5.x behavior.

    When enabled, resolution follows NESTY_PROVIDER_CREDENTIAL_SOURCE_PRIORITY
    (default: managed, secret_file, env).
    """
    normalized = str(provider_id or "").strip().lower()
    if not normalized:
        return None, "missing"

    if not credentials_feature_enabled(settings):
        return _resolve_env_api_key(settings, normalized)

    priority = parse_source_priority(getattr(settings, "nesty_provider_credential_source_priority", None))
    for source in priority:
        if source == "managed":
            value, status = _resolve_managed_api_key(settings, normalized, db_path=db_path)
            if value:
                return value, status
        elif source == "secret_file":
            value, status = _resolve_secret_file_api_key(settings, normalized)
            if value:
                return value, status
        elif source == "env":
            value, status = _resolve_env_api_key(settings, normalized)
            if value:
                return value, status
    return None, "missing"


def credential_status_for_provider(
    provider_id: str,
    settings: Any,
    *,
    db_path: str | None = None,
) -> dict[str, str]:
    """Safe metadata for API responses — never includes raw secrets."""
    _, status = resolve_builtin_provider_api_key(provider_id, settings, db_path=db_path)
    source = "missing"
    if status == "env_ref":
        source = "env"
    elif status == "stored":
        source = "secret_file"
    elif status == "managed":
        source = "managed_store"
    secret_status: str = "configured" if status in {"env_ref", "stored", "managed"} else "missing"
    return {
        "credential_source": source,
        "secret_status": secret_status,
    }
