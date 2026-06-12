from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from app.storage.db import get_connection


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_settings():
    from app.deps import get_settings as deps_get_settings

    return deps_get_settings()


def _effective_db_path(db_path: str | None = None) -> str:
    if db_path:
        return db_path
    return get_settings().nesty_db_path


def _parse_json(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _row_to_dict(row) -> dict[str, Any]:
    capabilities = _parse_json(row["capabilities_json"])
    return {
        "provider_id": row["provider_id"],
        "provider_type": row["provider_type"],
        "display_name": row["display_name"],
        "enabled": bool(row["enabled"]),
        "base_url": row["base_url"],
        "chat_completions_path": row["chat_completions_path"],
        "models_path": row["models_path"],
        "api_key_mode": row["api_key_mode"],
        "api_key_env_name": row["api_key_env_name"],
        "api_key_secret_ref": row["api_key_secret_ref"],
        "default_headers": _parse_json(row["default_headers_json"]),
        "capabilities": capabilities,
        "default_timeout_seconds": float(row["default_timeout_seconds"]),
        "health_check_model": row["health_check_model"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_runtime_providers(*, include_disabled: bool = True, db_path: str | None = None) -> list[dict[str, Any]]:
    query = """
        SELECT provider_id, provider_type, display_name, enabled, base_url, chat_completions_path,
               models_path, api_key_mode, api_key_env_name, api_key_secret_ref, default_headers_json,
               capabilities_json, default_timeout_seconds, health_check_model, created_at, updated_at
        FROM runtime_provider_definitions
    """
    if not include_disabled:
        query += " WHERE enabled = 1"
    query += " ORDER BY provider_id ASC"
    try:
        with get_connection(_effective_db_path(db_path)) as conn:
            rows = conn.execute(query).fetchall()
    except sqlite3.OperationalError:
        return []
    return [_row_to_dict(row) for row in rows]


def list_enabled_runtime_provider_ids(db_path: str | None = None) -> list[str]:
    try:
        with get_connection(_effective_db_path(db_path)) as conn:
            rows = conn.execute(
                "SELECT provider_id FROM runtime_provider_definitions WHERE enabled = 1 ORDER BY provider_id ASC"
            ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [str(row["provider_id"]) for row in rows]


def get_runtime_provider(provider_id: str, db_path: str | None = None) -> dict[str, Any] | None:
    normalized = str(provider_id or "").strip().lower()
    try:
        with get_connection(_effective_db_path(db_path)) as conn:
            row = conn.execute(
                """
                SELECT provider_id, provider_type, display_name, enabled, base_url, chat_completions_path,
                       models_path, api_key_mode, api_key_env_name, api_key_secret_ref, default_headers_json,
                       capabilities_json, default_timeout_seconds, health_check_model, created_at, updated_at
                FROM runtime_provider_definitions
                WHERE provider_id = ?
                LIMIT 1
                """,
                (normalized,),
            ).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None:
        return None
    return _row_to_dict(row)


def create_runtime_provider(record: dict[str, Any], db_path: str | None = None) -> dict[str, Any]:
    now = _now_iso()
    capabilities = record.get("capabilities") or {}
    with get_connection(_effective_db_path(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO runtime_provider_definitions (
                provider_id, provider_type, display_name, enabled, base_url, chat_completions_path,
                models_path, api_key_mode, api_key_env_name, api_key_secret_ref, default_headers_json,
                capabilities_json, default_timeout_seconds, health_check_model, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["provider_id"],
                record.get("provider_type", "openai_compatible"),
                record["display_name"],
                1 if record.get("enabled", True) else 0,
                record["base_url"],
                record.get("chat_completions_path", "/v1/chat/completions"),
                record.get("models_path"),
                record.get("api_key_mode", "none"),
                record.get("api_key_env_name"),
                record.get("api_key_secret_ref"),
                json.dumps(record.get("default_headers") or {}, ensure_ascii=True),
                json.dumps(capabilities, ensure_ascii=True),
                float(record.get("default_timeout_seconds", 30.0)),
                record.get("health_check_model"),
                now,
                now,
            ),
        )
    created = get_runtime_provider(record["provider_id"], db_path=db_path)
    assert created is not None
    return created


def update_runtime_provider(provider_id: str, updates: dict[str, Any], db_path: str | None = None) -> dict[str, Any]:
    existing = get_runtime_provider(provider_id, db_path=db_path)
    if existing is None:
        raise KeyError("runtime_provider_not_found")
    merged = dict(existing)
    merged.update(updates)
    now = _now_iso()
    capabilities = merged.get("capabilities") or {}
    with get_connection(_effective_db_path(db_path)) as conn:
        conn.execute(
            """
            UPDATE runtime_provider_definitions
            SET display_name = ?, enabled = ?, base_url = ?, chat_completions_path = ?, models_path = ?,
                api_key_mode = ?, api_key_env_name = ?, api_key_secret_ref = ?, default_headers_json = ?,
                capabilities_json = ?, default_timeout_seconds = ?, health_check_model = ?, updated_at = ?
            WHERE provider_id = ?
            """,
            (
                merged["display_name"],
                1 if merged.get("enabled", True) else 0,
                merged["base_url"],
                merged.get("chat_completions_path", "/v1/chat/completions"),
                merged.get("models_path"),
                merged.get("api_key_mode", "none"),
                merged.get("api_key_env_name"),
                merged.get("api_key_secret_ref"),
                json.dumps(merged.get("default_headers") or {}, ensure_ascii=True),
                json.dumps(capabilities, ensure_ascii=True),
                float(merged.get("default_timeout_seconds", 30.0)),
                merged.get("health_check_model"),
                now,
                provider_id,
            ),
        )
    updated = get_runtime_provider(provider_id, db_path=db_path)
    assert updated is not None
    return updated


def set_runtime_provider_enabled(provider_id: str, *, enabled: bool, db_path: str | None = None) -> dict[str, Any]:
    existing = get_runtime_provider(provider_id, db_path=db_path)
    if existing is None:
        raise KeyError("runtime_provider_not_found")
    return update_runtime_provider(provider_id, {"enabled": enabled}, db_path=db_path)


def delete_runtime_provider(provider_id: str, db_path: str | None = None) -> bool:
    with get_connection(_effective_db_path(db_path)) as conn:
        cursor = conn.execute(
            "DELETE FROM runtime_provider_definitions WHERE provider_id = ?",
            (provider_id,),
        )
    return cursor.rowcount > 0
