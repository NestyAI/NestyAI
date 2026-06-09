from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.security.api_key import get_key_prefix, hash_api_key
from app.storage.db import get_connection


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_allowed_models(raw: Any) -> list[str] | None:
    if not raw:
        return None
    if not isinstance(raw, str):
        try:
            raw = str(raw)
        except Exception:
            return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except json.JSONDecodeError:
        pass
    return [item.strip() for item in raw.split(",") if item.strip()]


def create_api_key_record(
    db_path: str,
    name: str,
    raw_key: str,
    environment: str = "dev",
    daily_limit: int | None = None,
    monthly_limit: int | None = None,
    allowed_models: list[str] | None = None,
    hash_secret: str | None = None,
) -> dict[str, Any]:
    key_id = f"key_{uuid4().hex[:16]}"
    key_hash = hash_api_key(raw_key, hash_secret=hash_secret)
    key_prefix = get_key_prefix(raw_key)
    created_at = _now_iso()
    allowed_models_json = json.dumps(allowed_models) if allowed_models else None

    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO api_keys
            (id, name, key_hash, key_prefix, environment, is_active, daily_limit, monthly_limit, allowed_models, created_at)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
            """,
            (
                key_id,
                name,
                key_hash,
                key_prefix,
                environment,
                daily_limit,
                monthly_limit,
                allowed_models_json,
                created_at,
            ),
        )
        conn.commit()

    return {
        "id": key_id,
        "name": name,
        "environment": environment,
        "key_prefix": key_prefix,
        "daily_limit": daily_limit,
        "monthly_limit": monthly_limit,
        "allowed_models": allowed_models,
        "created_at": created_at,
    }


def list_api_keys(db_path: str) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, name, key_prefix, environment, is_active, daily_limit, monthly_limit,
                   allowed_models, created_at, last_used_at, revoked_at
            FROM api_keys
            ORDER BY created_at DESC
            """
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        result.append(
            {
                "id": row["id"],
                "name": row["name"],
                "key_prefix": row["key_prefix"],
                "environment": row["environment"],
                "is_active": bool(row["is_active"]),
                "daily_limit": row["daily_limit"],
                "monthly_limit": row["monthly_limit"],
                "allowed_models": _parse_allowed_models(row["allowed_models"]),
                "created_at": row["created_at"],
                "last_used_at": row["last_used_at"],
                "revoked_at": row["revoked_at"],
            }
        )
    return result


def get_api_key_by_hash(db_path: str, key_hash: str) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT id, name, key_hash, key_prefix, environment, is_active, daily_limit, monthly_limit,
                   allowed_models, created_at, last_used_at, revoked_at
            FROM api_keys
            WHERE key_hash = ?
            LIMIT 1
            """,
            (key_hash,),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "key_hash": row["key_hash"],
        "key_prefix": row["key_prefix"],
        "environment": row["environment"],
        "is_active": bool(row["is_active"]),
        "daily_limit": row["daily_limit"],
        "monthly_limit": row["monthly_limit"],
        "allowed_models": _parse_allowed_models(row["allowed_models"]),
        "created_at": row["created_at"],
        "last_used_at": row["last_used_at"],
        "revoked_at": row["revoked_at"],
    }


def mark_api_key_used(db_path: str, key_id: str) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE api_keys SET last_used_at = ? WHERE id = ?",
            (_now_iso(), key_id),
        )
        conn.commit()


def revoke_api_key(db_path: str, key_id: str) -> bool:
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE api_keys
            SET is_active = 0, revoked_at = ?
            WHERE id = ? AND is_active = 1
            """,
            (_now_iso(), key_id),
        )
        conn.commit()
    return cursor.rowcount > 0


def revoke_active_api_keys_by_marker(
    db_path: str,
    *,
    name: str,
    environment: str,
    key_prefix_startswith: str | None = None,
) -> int:
    params: list[Any] = [_now_iso(), name, environment]
    where_prefix = ""
    if key_prefix_startswith:
        where_prefix = " AND key_prefix LIKE ?"
        params.append(f"{key_prefix_startswith}%")

    with get_connection(db_path) as conn:
        cursor = conn.execute(
            f"""
            UPDATE api_keys
            SET is_active = 0, revoked_at = ?
            WHERE is_active = 1 AND name = ? AND environment = ?{where_prefix}
            """,
            tuple(params),
        )
        conn.commit()
    return max(0, int(cursor.rowcount))


def get_api_key_by_id(db_path: str, key_id: str) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT id, name, key_hash, key_prefix, environment, is_active, daily_limit, monthly_limit,
                   allowed_models, created_at, last_used_at, revoked_at
            FROM api_keys
            WHERE id = ?
            LIMIT 1
            """,
            (key_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "key_hash": row["key_hash"],
        "key_prefix": row["key_prefix"],
        "environment": row["environment"],
        "is_active": bool(row["is_active"]),
        "daily_limit": row["daily_limit"],
        "monthly_limit": row["monthly_limit"],
        "allowed_models": _parse_allowed_models(row["allowed_models"]),
        "created_at": row["created_at"],
        "last_used_at": row["last_used_at"],
        "revoked_at": row["revoked_at"],
    }


def list_api_keys_filtered(
    db_path: str,
    *,
    environment: str | None = None,
    revoked: bool | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    try:
        limit_val = int(limit)
        if limit_val <= 0 or limit_val > 1000:
            limit_val = 50
    except (TypeError, ValueError):
        limit_val = 50

    try:
        offset_val = int(offset)
        if offset_val < 0:
            offset_val = 0
    except (TypeError, ValueError):
        offset_val = 0

    query = """
        SELECT id, name, key_hash, key_prefix, environment, is_active, daily_limit, monthly_limit,
               allowed_models, created_at, last_used_at, revoked_at
        FROM api_keys
        WHERE 1=1
    """
    params: list[Any] = []
    if environment is not None:
        query += " AND environment = ?"
        params.append(environment)
    if revoked is not None:
        query += " AND is_active = ?"
        params.append(0 if revoked else 1)
    if q is not None:
        query += " AND (name LIKE ? OR key_prefix LIKE ?)"
        q_val = f"%{q}%"
        params.extend([q_val, q_val])

    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit_val, offset_val])

    with get_connection(db_path) as conn:
        rows = conn.execute(query, tuple(params)).fetchall()

    result: list[dict[str, Any]] = []
    for row in rows:
        result.append(
            {
                "id": row["id"],
                "name": row["name"],
                "key_hash": row["key_hash"],
                "key_prefix": row["key_prefix"],
                "environment": row["environment"],
                "is_active": bool(row["is_active"]),
                "daily_limit": row["daily_limit"],
                "monthly_limit": row["monthly_limit"],
                "allowed_models": _parse_allowed_models(row["allowed_models"]),
                "created_at": row["created_at"],
                "last_used_at": row["last_used_at"],
                "revoked_at": row["revoked_at"],
            }
        )
    return result


def update_api_key_record(
    db_path: str,
    key_id: str,
    updates: dict[str, Any],
) -> dict[str, Any] | None:
    valid_fields = ["name", "environment", "daily_limit", "monthly_limit", "allowed_models"]
    fields_to_update = {}
    for field in valid_fields:
        if field in updates:
            val = updates[field]
            if field == "allowed_models":
                fields_to_update[field] = json.dumps(val) if val else None
            else:
                fields_to_update[field] = val

    if fields_to_update:
        set_clauses = []
        params = []
        for field, val in fields_to_update.items():
            set_clauses.append(f"{field} = ?")
            params.append(val)
        params.append(key_id)

        with get_connection(db_path) as conn:
            conn.execute(
                f"UPDATE api_keys SET {', '.join(set_clauses)} WHERE id = ?",
                tuple(params),
            )
            conn.commit()

    return get_api_key_by_id(db_path, key_id)
