from __future__ import annotations

import re
from typing import Any

from app.core.runtime_providers.url_safety import validate_base_url_host
from app.providers.constants import BUILTIN_PROVIDER_IDS

_SECRET_HINT_PATTERNS = [
    "api_key",
    "apikey",
    "secret",
    "token",
    "password",
    "-----begin",
    "bearer ",
    "sk-",
]


_PROVIDER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,47}$")
_ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_SECRET_VALUE_PATTERNS = [
    re.compile(r"(?i)^bearer\s+"),
    re.compile(r"(?i)^sk-"),
    re.compile(r"(?i)^nsk_"),
    re.compile(r"(?i)^nia_"),
    re.compile(r"(?i)^ncc_"),
]

_FORBIDDEN_HEADER_NAMES = {
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
}


def _settings_flags(settings: Any) -> tuple[bool, bool, bool]:
    runtime_enabled = bool(getattr(settings, "nesty_runtime_openai_providers_enabled", True))
    allow_http = bool(getattr(settings, "nesty_runtime_provider_allow_http", False))
    allow_private = bool(getattr(settings, "nesty_runtime_provider_allow_private_base_url", False))
    return runtime_enabled, allow_http, allow_private


def validate_provider_id(provider_id: str) -> tuple[bool, str | None]:
    normalized = str(provider_id or "").strip().lower()
    if not _PROVIDER_ID_RE.fullmatch(normalized):
        return False, "runtime_provider_invalid: provider_id must be 3-48 chars, lowercase letters, numbers, _ or -"
    if normalized in BUILTIN_PROVIDER_IDS:
        return False, "runtime_provider_conflict: provider_id conflicts with a built-in provider"
    if "." in normalized or "/" in normalized or "\\" in normalized:
        return False, "runtime_provider_invalid: provider_id contains unsafe characters"
    return True, None


def validate_default_headers(headers: dict[str, str] | None) -> tuple[bool, str | None]:
    if not headers:
        return True, None
    for raw_key, raw_value in headers.items():
        key = str(raw_key or "").strip()
        value = str(raw_value or "")
        lowered = key.lower()
        if lowered in _FORBIDDEN_HEADER_NAMES:
            return False, f"runtime_provider_invalid: header '{key}' is not allowed"
        if any(hint in lowered for hint in ("token", "secret", "password", "api-key", "apikey")):
            if _value_looks_secret(value):
                return False, f"runtime_provider_invalid: header '{key}' appears to contain a secret"
        if _value_looks_secret(value):
            return False, f"runtime_provider_invalid: header '{key}' value appears secret-like"
    return True, None


def _value_looks_secret(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    for pattern in _SECRET_VALUE_PATTERNS:
        if pattern.search(text):
            return True
    lowered = text.lower()
    if len(lowered) >= 24 and any(hint in lowered for hint in _SECRET_HINT_PATTERNS):
        return True
    return False


def normalize_base_url_and_path(base_url: str, chat_completions_path: str) -> tuple[str, str, str | None]:
    raw_base = str(base_url or "").strip()
    raw_path = str(chat_completions_path or "/v1/chat/completions").strip() or "/v1/chat/completions"
    if not raw_path.startswith("/"):
        raw_path = f"/{raw_path}"
    lowered = raw_base.lower()
    if "/chat/completions" in lowered:
        return raw_base, raw_path, "runtime_provider_invalid: put host origin in base_url and path in chat_completions_path"
    normalized_base = raw_base.rstrip("/")
    return normalized_base, raw_path, None


def validate_runtime_provider_payload(
    payload: dict[str, Any],
    *,
    settings: Any,
    resolve_dns: bool = False,
) -> tuple[bool, str | None]:
    _, allow_http, allow_private = _settings_flags(settings)
    provider_id = str(payload.get("provider_id") or "").strip().lower()
    valid_id, id_error = validate_provider_id(provider_id)
    if not valid_id:
        return False, id_error
    if str(payload.get("provider_type") or "openai_compatible") != "openai_compatible":
        return False, "runtime_provider_invalid: only openai_compatible providers are supported"
    base_url, path, split_error = normalize_base_url_and_path(
        str(payload.get("base_url") or ""),
        str(payload.get("chat_completions_path") or "/v1/chat/completions"),
    )
    if split_error:
        return False, split_error
    ok_url, url_error = validate_base_url_host(
        base_url,
        allow_http=allow_http,
        allow_private=allow_private,
        resolve_dns=resolve_dns,
    )
    if not ok_url:
        return False, url_error
    valid_headers, header_error = validate_default_headers(payload.get("default_headers") or {})
    if not valid_headers:
        return False, header_error
    api_key_mode = str(payload.get("api_key_mode") or "none").strip().lower()
    if api_key_mode not in {"env", "secret_file", "none"}:
        return False, "runtime_provider_invalid: api_key_mode must be env, secret_file, or none"
    if api_key_mode == "env":
        env_name = str(payload.get("api_key_env_name") or "").strip()
        if not env_name or not _ENV_NAME_RE.fullmatch(env_name):
            return False, "runtime_provider_invalid: api_key_env_name must be a valid env var name"
    if api_key_mode == "secret_file":
        secret_mode = str(getattr(settings, "nesty_runtime_provider_secret_mode", "file") or "file").lower()
        if secret_mode != "file":
            return False, "runtime_provider_invalid: secret_file api_key_mode is not enabled"
    return True, None


def get_supported_chat_provider_ids(*, settings: Any | None = None, db_path: str | None = None) -> frozenset[str]:
    from app.core.runtime_providers.storage import list_enabled_runtime_provider_ids

    if settings is None:
        from app.deps import get_settings

        settings = get_settings()
    ids = set(BUILTIN_PROVIDER_IDS)
    if bool(getattr(settings, "nesty_runtime_openai_providers_enabled", True)):
        ids.update(list_enabled_runtime_provider_ids(db_path=db_path))
    return frozenset(ids)
