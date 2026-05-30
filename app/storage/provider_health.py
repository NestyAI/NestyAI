from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.storage.db import get_connection


_ALLOWED_STATUS = {"ok", "failed", "skipped", "unavailable", "timeout"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _since_iso(since_seconds: int | None) -> str | None:
    if since_seconds is None:
        return None
    try:
        seconds = int(since_seconds)
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    cutoff = datetime.now(timezone.utc).timestamp() - float(seconds)
    return datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()


def get_settings():
    from app.deps import get_settings as deps_get_settings

    return deps_get_settings()


def _effective_db_path(db_path: str | None = None) -> str:
    if db_path:
        return db_path
    return get_settings().nesty_db_path


def _safe_parse_metadata(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _normalize_status(status: str) -> str:
    normalized = str(status or "").strip().lower()
    if normalized in _ALLOWED_STATUS:
        return normalized
    return "failed"


def _sanitize_error_message(message: str | None) -> str | None:
    if not message:
        return None
    cleaned = " ".join(str(message).replace("\r", " ").replace("\n", " ").split()).strip()
    if not cleaned:
        return None
    if len(cleaned) > 240:
        return cleaned[:240].rstrip() + "..."
    return cleaned


def record_provider_health_check(
    provider: str,
    model: str,
    status: str,
    model_alias: str | None = None,
    role: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    latency_ms: int | None = None,
    output_chars: int = 0,
    tokens_per_second: float | None = None,
    metadata: dict[str, Any] | None = None,
    checked_at: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    row_id = f"phc_{uuid4().hex[:16]}"
    status_clean = _normalize_status(status)
    checked = str(checked_at or _now_iso())
    metadata_json = json.dumps(metadata, ensure_ascii=True) if isinstance(metadata, dict) else None
    sanitized_error_message = _sanitize_error_message(error_message)
    with get_connection(_effective_db_path(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO provider_health_checks
            (id, provider, model, model_alias, role, status, error_code, error_message,
             latency_ms, output_chars, tokens_per_second, checked_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row_id,
                str(provider or "").strip(),
                str(model or "").strip(),
                str(model_alias or "").strip() or None,
                str(role or "").strip() or None,
                status_clean,
                str(error_code or "").strip() or None,
                sanitized_error_message,
                int(latency_ms) if latency_ms is not None else None,
                max(0, int(output_chars or 0)),
                float(tokens_per_second) if tokens_per_second is not None else None,
                checked,
                metadata_json,
            ),
        )
        conn.commit()
    return {
        "id": row_id,
        "provider": str(provider or "").strip(),
        "model": str(model or "").strip(),
        "model_alias": str(model_alias or "").strip() or None,
        "role": str(role or "").strip() or None,
        "status": status_clean,
        "error_code": str(error_code or "").strip() or None,
        "error_message": sanitized_error_message,
        "latency_ms": int(latency_ms) if latency_ms is not None else None,
        "output_chars": max(0, int(output_chars or 0)),
        "tokens_per_second": float(tokens_per_second) if tokens_per_second is not None else None,
        "checked_at": checked,
        "metadata": metadata if isinstance(metadata, dict) else None,
    }


def list_provider_health_checks(
    provider: str | None = None,
    model_alias: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    since_seconds: int | None = None,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    sql = """
        SELECT id, provider, model, model_alias, role, status, error_code, error_message,
               latency_ms, output_chars, tokens_per_second, checked_at, metadata
        FROM provider_health_checks
        WHERE 1=1
    """
    params: list[Any] = []
    if provider:
        sql += " AND provider = ?"
        params.append(str(provider).strip())
    if model_alias:
        sql += " AND model_alias = ?"
        params.append(str(model_alias).strip())
    if status:
        sql += " AND status = ?"
        params.append(_normalize_status(status))
    since_iso = _since_iso(since_seconds)
    if since_iso:
        sql += " AND checked_at >= ?"
        params.append(since_iso)
    sql += " ORDER BY checked_at DESC LIMIT ? OFFSET ?"
    params.extend([max(1, int(limit)), max(0, int(offset))])

    with get_connection(_effective_db_path(db_path)) as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [
        {
            "id": row["id"],
            "provider": row["provider"],
            "model": row["model"],
            "model_alias": row["model_alias"],
            "role": row["role"],
            "status": row["status"],
            "error_code": row["error_code"],
            "error_message": row["error_message"],
            "latency_ms": int(row["latency_ms"]) if row["latency_ms"] is not None else None,
            "output_chars": int(row["output_chars"] or 0),
            "tokens_per_second": float(row["tokens_per_second"]) if row["tokens_per_second"] is not None else None,
            "checked_at": row["checked_at"],
            "metadata": _safe_parse_metadata(row["metadata"]),
        }
        for row in rows
    ]


def get_latest_provider_health(
    provider: str | None = None,
    model_alias: str | None = None,
    since_seconds: int | None = None,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    sql = """
        SELECT
            ph.id, ph.provider, ph.model, ph.model_alias, ph.role, ph.status, ph.error_code, ph.error_message,
            ph.latency_ms, ph.output_chars, ph.tokens_per_second, ph.checked_at, ph.metadata
        FROM provider_health_checks ph
        JOIN (
            SELECT provider, model, COALESCE(model_alias, '') AS model_alias_key, COALESCE(role, '') AS role_key, MAX(checked_at) AS max_checked_at
            FROM provider_health_checks
            WHERE 1=1
    """
    params: list[Any] = []
    if provider:
        sql += " AND provider = ?"
        params.append(str(provider).strip())
    if model_alias:
        sql += " AND model_alias = ?"
        params.append(str(model_alias).strip())
    since_iso = _since_iso(since_seconds)
    if since_iso:
        sql += " AND checked_at >= ?"
        params.append(since_iso)
    sql += """
            GROUP BY provider, model, model_alias_key, role_key
        ) latest
          ON ph.provider = latest.provider
         AND ph.model = latest.model
         AND COALESCE(ph.model_alias, '') = latest.model_alias_key
         AND COALESCE(ph.role, '') = latest.role_key
         AND ph.checked_at = latest.max_checked_at
        ORDER BY ph.checked_at DESC
    """
    with get_connection(_effective_db_path(db_path)) as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [
        {
            "id": row["id"],
            "provider": row["provider"],
            "model": row["model"],
            "model_alias": row["model_alias"],
            "role": row["role"],
            "status": row["status"],
            "error_code": row["error_code"],
            "error_message": row["error_message"],
            "latency_ms": int(row["latency_ms"]) if row["latency_ms"] is not None else None,
            "output_chars": int(row["output_chars"] or 0),
            "tokens_per_second": float(row["tokens_per_second"]) if row["tokens_per_second"] is not None else None,
            "checked_at": row["checked_at"],
            "metadata": _safe_parse_metadata(row["metadata"]),
        }
        for row in rows
    ]


def summarize_provider_health(
    provider: str | None = None,
    model_alias: str | None = None,
    since_seconds: int | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    where = " WHERE 1=1"
    params: list[Any] = []
    if provider:
        where += " AND provider = ?"
        params.append(str(provider).strip())
    if model_alias:
        where += " AND model_alias = ?"
        params.append(str(model_alias).strip())
    since_iso = _since_iso(since_seconds)
    if since_iso:
        where += " AND checked_at >= ?"
        params.append(since_iso)

    with get_connection(_effective_db_path(db_path)) as conn:
        total_row = conn.execute(f"SELECT COUNT(*) AS total FROM provider_health_checks{where}", tuple(params)).fetchone()
        status_rows = conn.execute(
            f"""
            SELECT status, COUNT(*) AS count
            FROM provider_health_checks
            {where}
            GROUP BY status
            """,
            tuple(params),
        ).fetchall()
        provider_rows = conn.execute(
            f"""
            SELECT provider,
                   COUNT(*) AS total,
                   AVG(CASE WHEN latency_ms IS NOT NULL THEN latency_ms END) AS avg_latency_ms
            FROM provider_health_checks
            {where}
            GROUP BY provider
            ORDER BY provider ASC
            """,
            tuple(params),
        ).fetchall()
        latency_row = conn.execute(
            f"""
            SELECT AVG(CASE WHEN latency_ms IS NOT NULL THEN latency_ms END) AS avg_latency_ms
            FROM provider_health_checks
            {where}
            """,
            tuple(params),
        ).fetchone()
    status_counts = {str(row["status"]): int(row["count"] or 0) for row in status_rows}
    return {
        "total_checks": int(total_row["total"] or 0) if total_row else 0,
        "ok": int(status_counts.get("ok", 0)),
        "failed": int(status_counts.get("failed", 0)),
        "unavailable": int(status_counts.get("unavailable", 0)),
        "timeout": int(status_counts.get("timeout", 0)),
        "skipped": int(status_counts.get("skipped", 0)),
        "status_counts": status_counts,
        "avg_latency_ms": float(latency_row["avg_latency_ms"]) if latency_row and latency_row["avg_latency_ms"] is not None else None,
        "providers": [
            {
                "provider": row["provider"],
                "total_checks": int(row["total"] or 0),
                "avg_latency_ms": float(row["avg_latency_ms"]) if row["avg_latency_ms"] is not None else None,
            }
            for row in provider_rows
        ],
    }
