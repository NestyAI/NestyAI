from __future__ import annotations

import sqlite3
from pathlib import Path


def _resolve_db_path(db_path: str) -> Path:
    path = Path(db_path)
    if path.is_absolute():
        return path
    return Path.cwd() / path


def init_db(db_path: str) -> None:
    resolved = _resolve_db_path(db_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(resolved) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_keys (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                key_hash TEXT NOT NULL UNIQUE,
                key_prefix TEXT NOT NULL,
                environment TEXT NOT NULL DEFAULT 'dev',
                is_active INTEGER NOT NULL DEFAULT 1,
                daily_limit INTEGER DEFAULT NULL,
                monthly_limit INTEGER DEFAULT NULL,
                allowed_models TEXT DEFAULT NULL,
                created_at TEXT NOT NULL,
                last_used_at TEXT DEFAULT NULL,
                revoked_at TEXT DEFAULT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS usage_logs (
                id TEXT PRIMARY KEY,
                api_key_id TEXT,
                request_id TEXT NOT NULL,
                model TEXT,
                provider TEXT,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                tools_used TEXT DEFAULT NULL,
                search_used INTEGER DEFAULT 0,
                latency_ms INTEGER DEFAULT 0,
                status TEXT NOT NULL,
                error_code TEXT DEFAULT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def get_connection(db_path: str) -> sqlite3.Connection:
    resolved = _resolve_db_path(db_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(resolved, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

