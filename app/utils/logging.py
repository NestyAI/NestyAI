from __future__ import annotations

import json
import logging
from typing import Any

from app.guards.patterns import GUARD_PATTERNS


_IS_CONFIGURED = False
_LOG_SECRET_REPLACEMENT = "[REDACTED_LOG]"
_AUTH_PATTERN = "authorization"


def configure_logging() -> None:
    global _IS_CONFIGURED
    if _IS_CONFIGURED:
        return
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # Prevent third-party search engine logs from leaking user query text.
    logging.getLogger("ddgs").setLevel(logging.WARNING)
    logging.getLogger("ddgs.ddgs").setLevel(logging.WARNING)
    _IS_CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)


def sanitize_log_value(value: str) -> str:
    sanitized = value
    for pattern in GUARD_PATTERNS:
        if pattern.category != "secret":
            continue
        sanitized = pattern.regex.sub(_LOG_SECRET_REPLACEMENT, sanitized)
    return sanitized


def _sanitize_field_value(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if _AUTH_PATTERN in str(key).strip().lower():
                cleaned[key] = _LOG_SECRET_REPLACEMENT
            else:
                cleaned[key] = _sanitize_field_value(item)
        return cleaned
    if isinstance(value, list):
        return [_sanitize_field_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_field_value(item) for item in value)
    if isinstance(value, str):
        return sanitize_log_value(value)
    return value


def log_safe(logger: logging.Logger, event: str, **fields: Any) -> None:
    sanitized_fields = {key: _sanitize_field_value(value) for key, value in fields.items()}
    logger.info("%s | %s", event, json.dumps(sanitized_fields, ensure_ascii=True, default=str))
