from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.storage.db import get_connection


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_settings():
    # Lazy import to avoid circular dependency during app bootstrap/tests.
    from app.deps import get_settings as deps_get_settings

    return deps_get_settings()


def _effective_db_path(db_path: str | None = None) -> str:
    if db_path:
        return db_path
    return get_settings().nesty_db_path


def _parse_json(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _clear_runtime_model_config_caches() -> None:
    try:
        from app.deps import clear_runtime_model_config_caches
    except Exception:
        return
    try:
        clear_runtime_model_config_caches()
    except Exception:
        return


def get_model_override(model_id: str, db_path: str | None = None) -> dict[str, Any] | None:
    with get_connection(_effective_db_path(db_path)) as conn:
        row = conn.execute(
            """
            SELECT id, model_id, config_json, is_active, created_at, updated_at,
                   updated_by_api_key_id, updated_by_label
            FROM model_config_overrides
            WHERE model_id = ? AND is_active = 1
            LIMIT 1
            """,
            (model_id,),
        ).fetchone()
    if row is None:
        return None
    parsed = _parse_json(row["config_json"])
    if parsed is None:
        return None
    return {
        "id": row["id"],
        "model_id": row["model_id"],
        "config": parsed,
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "updated_by_api_key_id": row["updated_by_api_key_id"],
        "updated_by_label": row["updated_by_label"],
    }


def list_model_overrides(db_path: str | None = None) -> list[dict[str, Any]]:
    with get_connection(_effective_db_path(db_path)) as conn:
        rows = conn.execute(
            """
            SELECT id, model_id, config_json, is_active, created_at, updated_at,
                   updated_by_api_key_id, updated_by_label
            FROM model_config_overrides
            WHERE is_active = 1
            ORDER BY model_id ASC
            """
        ).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        parsed = _parse_json(row["config_json"])
        if parsed is None:
            continue
        items.append(
            {
                "id": row["id"],
                "model_id": row["model_id"],
                "config": parsed,
                "is_active": bool(row["is_active"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "updated_by_api_key_id": row["updated_by_api_key_id"],
                "updated_by_label": row["updated_by_label"],
            }
        )
    return items


def record_model_config_audit(
    model_id: str,
    action: str,
    old_config: dict[str, Any] | None = None,
    new_config: dict[str, Any] | None = None,
    changed_by_api_key_id: str | None = None,
    changed_by_label: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    now = _now_iso()
    audit_id = f"mcfg_audit_{uuid4().hex[:16]}"
    old_json = json.dumps(old_config, ensure_ascii=True) if old_config is not None else None
    new_json = json.dumps(new_config, ensure_ascii=True) if new_config is not None else None

    with get_connection(_effective_db_path(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO model_config_audit_logs
            (id, model_id, old_config_json, new_config_json, action, changed_by_api_key_id, changed_by_label, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit_id,
                model_id,
                old_json,
                new_json,
                action,
                changed_by_api_key_id,
                changed_by_label,
                now,
            ),
        )
        conn.commit()
    return {
        "id": audit_id,
        "model_id": model_id,
        "action": action,
        "created_at": now,
    }


def upsert_model_override(
    model_id: str,
    config: dict[str, Any],
    changed_by_api_key_id: str | None = None,
    changed_by_label: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    now = _now_iso()
    override_id = f"mcfg_override_{uuid4().hex[:16]}"
    config_json = json.dumps(config, ensure_ascii=True)

    old_override = get_model_override(model_id=model_id, db_path=db_path)
    old_config = old_override["config"] if old_override else None
    action = "create_override" if old_override is None else "update_override"

    with get_connection(_effective_db_path(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO model_config_overrides
            (id, model_id, config_json, is_active, created_at, updated_at, updated_by_api_key_id, updated_by_label)
            VALUES (?, ?, ?, 1, ?, ?, ?, ?)
            ON CONFLICT(model_id) DO UPDATE SET
                config_json = excluded.config_json,
                is_active = 1,
                updated_at = excluded.updated_at,
                updated_by_api_key_id = excluded.updated_by_api_key_id,
                updated_by_label = excluded.updated_by_label
            """,
            (
                override_id,
                model_id,
                config_json,
                now,
                now,
                changed_by_api_key_id,
                changed_by_label,
            ),
        )
        conn.commit()

    record_model_config_audit(
        model_id=model_id,
        action=action,
        old_config=old_config,
        new_config=config,
        changed_by_api_key_id=changed_by_api_key_id,
        changed_by_label=changed_by_label,
        db_path=db_path,
    )
    _clear_runtime_model_config_caches()
    created = get_model_override(model_id=model_id, db_path=db_path)
    if created is None:
        return {
            "id": override_id,
            "model_id": model_id,
            "config": config,
            "is_active": True,
            "created_at": now,
            "updated_at": now,
            "updated_by_api_key_id": changed_by_api_key_id,
            "updated_by_label": changed_by_label,
        }
    return created


def reset_model_override(
    model_id: str,
    changed_by_api_key_id: str | None = None,
    changed_by_label: str | None = None,
    db_path: str | None = None,
) -> bool:
    existing = get_model_override(model_id=model_id, db_path=db_path)
    if existing is None:
        return False
    now = _now_iso()
    with get_connection(_effective_db_path(db_path)) as conn:
        cursor = conn.execute(
            """
            UPDATE model_config_overrides
            SET is_active = 0, updated_at = ?, updated_by_api_key_id = ?, updated_by_label = ?
            WHERE model_id = ? AND is_active = 1
            """,
            (now, changed_by_api_key_id, changed_by_label, model_id),
        )
        conn.commit()
    if cursor.rowcount <= 0:
        return False
    record_model_config_audit(
        model_id=model_id,
        action="reset_override",
        old_config=existing.get("config"),
        new_config=None,
        changed_by_api_key_id=changed_by_api_key_id,
        changed_by_label=changed_by_label,
        db_path=db_path,
    )
    _clear_runtime_model_config_caches()
    return True


def get_model_config_audit_logs(
    model_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    sql = """
        SELECT id, model_id, old_config_json, new_config_json, action,
               changed_by_api_key_id, changed_by_label, created_at
        FROM model_config_audit_logs
        WHERE 1=1
    """
    params: list[Any] = []
    if model_id:
        sql += " AND model_id = ?"
        params.append(model_id)
    sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([max(1, int(limit)), max(0, int(offset))])

    with get_connection(_effective_db_path(db_path)) as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()

    items: list[dict[str, Any]] = []
    for row in rows:
        items.append(
            {
                "id": row["id"],
                "model_id": row["model_id"],
                "old_config": _parse_json(row["old_config_json"]),
                "new_config": _parse_json(row["new_config_json"]),
                "action": row["action"],
                "changed_by_api_key_id": row["changed_by_api_key_id"],
                "changed_by_label": row["changed_by_label"],
                "created_at": row["created_at"],
            }
        )
    return items
