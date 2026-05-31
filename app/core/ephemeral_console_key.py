from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from typing import Any

from app.deps import get_settings
from app.security.api_key import get_key_prefix
from app.storage.api_keys import create_api_key_record, revoke_active_api_keys_by_marker
from app.utils.logging import get_logger


logger = get_logger("nesty.ephemeral_console_key")

_DEFAULT_NAME = "nesty-console-ephemeral"
_DEFAULT_ENV = "prod"
_DEFAULT_DAILY_LIMIT = 10000
_DEFAULT_MODELS = "nesty-flash-1.0,nesty-combined-1.0,nesty-pro-1.0"
_DEFAULT_PREFIX = "nsk_console"


@dataclass
class EphemeralConsoleKeyConfig:
    enabled: bool
    name: str
    environment: str
    daily_limit: int
    monthly_limit: int | None
    allowed_models: list[str] | None
    key_prefix: str
    db_path: str
    hash_secret: str | None


def is_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_models(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    models = [item.strip() for item in str(raw).split(",") if item.strip()]
    return models or None


def _parse_daily_limit(raw: str | None) -> int:
    if raw is None or not str(raw).strip():
        return _DEFAULT_DAILY_LIMIT
    try:
        parsed = int(str(raw).strip())
    except Exception:
        return _DEFAULT_DAILY_LIMIT
    return parsed if parsed > 0 else _DEFAULT_DAILY_LIMIT


def _parse_monthly_limit(raw: str | None) -> int | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        parsed = int(text)
    except Exception:
        return None
    if parsed <= 0:
        return None
    return parsed


def get_ephemeral_console_key_config_from_env(settings: Any | None = None) -> EphemeralConsoleKeyConfig:
    runtime_settings = settings or get_settings()

    enabled = is_truthy(os.getenv("NESTY_EPHEMERAL_CONSOLE_KEY_ENABLED", "false"))
    name = str(os.getenv("NESTY_EPHEMERAL_CONSOLE_KEY_NAME", _DEFAULT_NAME)).strip() or _DEFAULT_NAME
    environment = str(os.getenv("NESTY_EPHEMERAL_CONSOLE_KEY_ENV", _DEFAULT_ENV)).strip() or _DEFAULT_ENV
    daily_limit = _parse_daily_limit(os.getenv("NESTY_EPHEMERAL_CONSOLE_KEY_DAILY_LIMIT", str(_DEFAULT_DAILY_LIMIT)))
    monthly_limit = _parse_monthly_limit(os.getenv("NESTY_EPHEMERAL_CONSOLE_KEY_MONTHLY_LIMIT", ""))
    allowed_models = _parse_models(os.getenv("NESTY_EPHEMERAL_CONSOLE_KEY_MODELS", _DEFAULT_MODELS))
    key_prefix = str(os.getenv("NESTY_EPHEMERAL_CONSOLE_KEY_PREFIX", _DEFAULT_PREFIX)).strip() or _DEFAULT_PREFIX

    return EphemeralConsoleKeyConfig(
        enabled=enabled,
        name=name,
        environment=environment,
        daily_limit=daily_limit,
        monthly_limit=monthly_limit,
        allowed_models=allowed_models,
        key_prefix=key_prefix,
        db_path=runtime_settings.nesty_db_path,
        hash_secret=runtime_settings.nesty_api_key_hash_secret,
    )


def generate_ephemeral_console_api_key(config: EphemeralConsoleKeyConfig) -> str:
    token = secrets.token_urlsafe(32)
    prefix = config.key_prefix.rstrip("_")
    return f"{prefix}_{token}"


def rotate_ephemeral_console_api_key_from_env(settings: Any | None = None) -> dict[str, Any]:
    config = get_ephemeral_console_key_config_from_env(settings=settings)
    if not config.enabled:
        return {"enabled": False, "rotated": False}

    result: dict[str, Any] = {
        "enabled": True,
        "rotated": False,
        "revoked_count": 0,
        "created_id": None,
        "allowed_models": config.allowed_models,
        "daily_limit": config.daily_limit,
        "monthly_limit": config.monthly_limit,
        "prefix": config.key_prefix,
        "error": None,
    }

    key_prefix_marker = get_key_prefix(f"{config.key_prefix.rstrip('_')}_")

    try:
        revoked_count = revoke_active_api_keys_by_marker(
            db_path=config.db_path,
            name=config.name,
            environment=config.environment,
            key_prefix_startswith=key_prefix_marker,
        )
        result["revoked_count"] = revoked_count
    except Exception as exc:
        logger.error("ephemeral_console_key_revoke_failed: %s", exc)
        result["error"] = "revoke_failed"
        return result

    raw_key = generate_ephemeral_console_api_key(config)
    try:
        record = create_api_key_record(
            db_path=config.db_path,
            name=config.name,
            raw_key=raw_key,
            environment=config.environment,
            daily_limit=config.daily_limit,
            monthly_limit=config.monthly_limit,
            allowed_models=config.allowed_models,
            hash_secret=config.hash_secret,
        )
    except Exception as exc:
        logger.error("ephemeral_console_key_create_failed: %s", exc)
        result["error"] = "create_failed"
        return result

    result["rotated"] = True
    result["created_id"] = record["id"]
    print("=" * 88, flush=True)
    print(
        "EPHEMERAL NESTY CONSOLE API KEY - copy this into Nesty Console. "
        "It will rotate on the next Gateway restart.",
        flush=True,
    )
    print(raw_key, flush=True)
    print("=" * 88, flush=True)

    logger.info(
        "ephemeral_console_key_rotated | revoked_count=%s name=%s env=%s models=%s daily_limit=%s monthly_limit=%s",
        result["revoked_count"],
        config.name,
        config.environment,
        ",".join(config.allowed_models or []),
        config.daily_limit,
        config.monthly_limit if config.monthly_limit is not None else "none",
    )
    return result
