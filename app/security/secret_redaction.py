from __future__ import annotations

import re
from typing import Any, Mapping

from app.core.model_config_loader import SECRET_HINT_PATTERNS


_REDACTED = "[REDACTED]"

_SECRET_VALUE_PATTERNS = [
    re.compile(r"(?i)\bbearer\s+[a-z0-9_\-\.=]+"),
    re.compile(r"(?i)\bnia_[a-z0-9_\-\.=]{8,}"),
    re.compile(r"(?i)\bncc_[a-z0-9_\-\.=]{8,}"),
    re.compile(r"(?i)\bnsk_[a-z0-9_\-\.=]{8,}"),
    re.compile(r"(?i)\bsk-[a-z0-9_\-\.=]{8,}"),
]


_SAFE_METADATA_KEYS = {
    "secret_status",
    "api_key_mode",
    "api_key_env_name",
    "api_key_secret_ref",
}


def _looks_like_secret_key(key: str) -> bool:
    lowered = key.strip().lower()
    if lowered in _SAFE_METADATA_KEYS:
        return False
    if lowered in {"authorization", "x-nesty-console-secret", "x-nesty-api-key"}:
        return True
    return any(hint in lowered for hint in SECRET_HINT_PATTERNS)


def redact_secret_text(value: str) -> str:
    cleaned = str(value or "")
    for pattern in _SECRET_VALUE_PATTERNS:
        cleaned = pattern.sub(_REDACTED, cleaned)
    return cleaned


def sanitize_mapping(data: Mapping[str, Any] | None) -> dict[str, Any]:
    if not data:
        return {}
    cleaned: dict[str, Any] = {}
    for key, value in data.items():
        key_text = str(key)
        if _looks_like_secret_key(key_text):
            cleaned[key_text] = _REDACTED
            continue
        cleaned[key_text] = sanitize_value(value)
    return cleaned


def sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return sanitize_mapping(value)
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_value(item) for item in value)
    if isinstance(value, str):
        return redact_secret_text(value)
    return value


def redact_request_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    if not headers:
        return {}
    cleaned: dict[str, str] = {}
    for key, value in headers.items():
        if _looks_like_secret_key(str(key)):
            cleaned[str(key)] = _REDACTED
        else:
            cleaned[str(key)] = redact_secret_text(str(value))
    return cleaned


def sanitize_config_response(data: Mapping[str, Any] | None) -> dict[str, Any]:
    return sanitize_mapping(data)
