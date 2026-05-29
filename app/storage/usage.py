from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4

from app.storage.db import get_connection


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _day_bounds_utc(target_day: date) -> tuple[str, str]:
    start = datetime.combine(target_day, time.min, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start.isoformat(), end.isoformat()


def _month_bounds_utc(target_day: date) -> tuple[str, str]:
    start = datetime(target_day.year, target_day.month, 1, tzinfo=timezone.utc)
    if target_day.month == 12:
        end = datetime(target_day.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(target_day.year, target_day.month + 1, 1, tzinfo=timezone.utc)
    return start.isoformat(), end.isoformat()


def insert_usage_log(
    db_path: str,
    request_id: str,
    status: str,
    api_key_id: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    tools_used: list[str] | None = None,
    search_used: bool = False,
    latency_ms: int = 0,
    error_code: str | None = None,
) -> str:
    usage_id = f"use_{uuid4().hex[:16]}"
    created_at = _now_iso()
    tools_json = json.dumps(tools_used or [])

    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO usage_logs
            (id, api_key_id, request_id, model, provider, prompt_tokens, completion_tokens, total_tokens,
             tools_used, search_used, latency_ms, status, error_code, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                usage_id,
                api_key_id,
                request_id,
                model,
                provider,
                int(prompt_tokens),
                int(completion_tokens),
                int(total_tokens),
                tools_json,
                1 if search_used else 0,
                int(latency_ms),
                status,
                error_code,
                created_at,
            ),
        )
        conn.commit()
    return usage_id


def _count_for_range(db_path: str, api_key_id: str, start_iso: str, end_iso: str) -> int:
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS request_count
            FROM usage_logs
            WHERE api_key_id = ?
              AND created_at >= ?
              AND created_at < ?
            """,
            (api_key_id, start_iso, end_iso),
        ).fetchone()
    return int(row["request_count"]) if row else 0


def count_daily_requests(db_path: str, api_key_id: str, target_day: date | None = None) -> int:
    day = target_day or datetime.now(timezone.utc).date()
    start_iso, end_iso = _day_bounds_utc(day)
    return _count_for_range(db_path, api_key_id, start_iso, end_iso)


def count_monthly_requests(db_path: str, api_key_id: str, target_day: date | None = None) -> int:
    day = target_day or datetime.now(timezone.utc).date()
    start_iso, end_iso = _month_bounds_utc(day)
    return _count_for_range(db_path, api_key_id, start_iso, end_iso)


def get_usage_summary(db_path: str, days: int = 7) -> list[dict[str, str | int]]:
    days = max(1, int(days))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    since_iso = since.isoformat()
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                COALESCE(api_key_id, 'anonymous') AS api_key_id,
                COALESCE(model, '') AS model,
                COALESCE(provider, '') AS provider,
                status,
                COUNT(*) AS request_count
            FROM usage_logs
            WHERE created_at >= ?
            GROUP BY api_key_id, model, provider, status
            ORDER BY request_count DESC, api_key_id ASC
            """,
            (since_iso,),
        ).fetchall()

    return [
        {
            "api_key_id": str(row["api_key_id"]),
            "model": str(row["model"]),
            "provider": str(row["provider"]),
            "status": str(row["status"]),
            "request_count": int(row["request_count"]),
        }
        for row in rows
    ]
