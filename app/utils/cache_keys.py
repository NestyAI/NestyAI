from __future__ import annotations

import hashlib
import json
from typing import Any


_SECRET_FIELD_KEYWORDS = ("key", "token", "secret", "password", "authorization", "auth")


def _normalize_for_cache(value: Any) -> Any:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key in sorted(value.keys(), key=lambda item: str(item)):
            key_text = str(key)
            item = value[key]
            if any(secret in key_text.lower() for secret in _SECRET_FIELD_KEYWORDS):
                normalized[key_text] = "<redacted>"
            else:
                normalized[key_text] = _normalize_for_cache(item)
        return normalized
    if isinstance(value, list):
        return [_normalize_for_cache(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_for_cache(item) for item in value]
    if isinstance(value, set):
        return sorted(_normalize_for_cache(item) for item in value)
    return value


def make_tool_cache_key(tool_name: str, params: dict) -> str:
    normalized = _normalize_for_cache(params)
    raw = json.dumps(normalized, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"tool:{tool_name}:{digest}"

