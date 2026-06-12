from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.storage.db import get_connection


_DEFAULT_STATE_ID = "default"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_settings():
    from app.deps import get_settings as deps_get_settings

    return deps_get_settings()


def _effective_db_path(db_path: str | None = None) -> str:
    if db_path:
        return db_path
    return get_settings().nesty_db_path


def _parse_state(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {"disabled_providers": []}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"disabled_providers": []}
    if not isinstance(parsed, dict):
        return {"disabled_providers": []}
    disabled = parsed.get("disabled_providers")
    if not isinstance(disabled, list):
        disabled = []
    normalized = sorted({str(item).strip().lower() for item in disabled if str(item).strip()})
    return {"disabled_providers": normalized}


def get_runtime_gateway_state(db_path: str | None = None) -> dict[str, Any]:
    try:
        with get_connection(_effective_db_path(db_path)) as conn:
            row = conn.execute(
                """
                SELECT state_json, updated_at
                FROM runtime_gateway_state
                WHERE id = ?
                LIMIT 1
                """,
                (_DEFAULT_STATE_ID,),
            ).fetchone()
    except sqlite3.OperationalError:
        return {"disabled_providers": [], "updated_at": None}
    if row is None:
        return {"disabled_providers": [], "updated_at": None}
    parsed = _parse_state(row["state_json"])
    parsed["updated_at"] = row["updated_at"]
    return parsed


def is_provider_runtime_disabled(provider_id: str, db_path: str | None = None) -> bool:
    provider = str(provider_id or "").strip().lower()
    if not provider:
        return False
    state = get_runtime_gateway_state(db_path=db_path)
    return provider in set(state.get("disabled_providers") or [])


def set_provider_runtime_disabled(
    provider_id: str,
    *,
    disabled: bool,
    db_path: str | None = None,
) -> dict[str, Any]:
    provider = str(provider_id or "").strip().lower()
    if not provider:
        raise ValueError("provider_id_required")
    state = get_runtime_gateway_state(db_path=db_path)
    disabled_providers = set(state.get("disabled_providers") or [])
    if disabled:
        disabled_providers.add(provider)
    else:
        disabled_providers.discard(provider)
    next_state = {"disabled_providers": sorted(disabled_providers)}
    now = _now_iso()
    with get_connection(_effective_db_path(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO runtime_gateway_state (id, state_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                state_json = excluded.state_json,
                updated_at = excluded.updated_at
            """,
            (_DEFAULT_STATE_ID, json.dumps(next_state, ensure_ascii=True), now),
        )
    next_state["updated_at"] = now
    return next_state


def record_runtime_config_audit(
    *,
    config_area: str,
    action: str,
    changed_fields: list[str],
    actor_type: str,
    console_id: str | None = None,
    validation_result: str = "ok",
    db_path: str | None = None,
) -> None:
    now = _now_iso()
    metadata = {
        "config_area": config_area,
        "changed_fields": list(changed_fields),
        "actor_type": actor_type,
        "console_id": console_id,
        "validation_result": validation_result,
    }
    with get_connection(_effective_db_path(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO runtime_config_audit_logs
            (id, config_area, action, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                f"rcfg_audit_{uuid4().hex[:16]}",
                config_area,
                action,
                json.dumps(metadata, ensure_ascii=True),
                now,
            ),
        )
