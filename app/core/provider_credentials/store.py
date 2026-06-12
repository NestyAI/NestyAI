from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from app.core.provider_credentials.models import CredentialSource, ProviderCredentialRecord
from app.storage.db import get_connection


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _effective_db_path(db_path: str | None, settings: Any) -> str:
    if db_path:
        return db_path
    return str(getattr(settings, "nesty_db_path", "data/nesty.db"))


def _row_to_record(row) -> ProviderCredentialRecord:
    return ProviderCredentialRecord(
        provider_id=str(row["provider_id"]),
        credential_name=str(row["credential_name"]),
        source=str(row["source"]),  # type: ignore[arg-type]
        secret_ref=row["secret_ref"],
        enabled=bool(row["enabled"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        last_rotated_at=row["last_rotated_at"],
    )


def get_provider_credential(
    provider_id: str,
    *,
    credential_name: str = "api_key",
    db_path: str | None = None,
    settings: Any | None = None,
) -> ProviderCredentialRecord | None:
    if settings is None:
        from app.deps import get_settings

        settings = get_settings()
    normalized_provider = str(provider_id or "").strip().lower()
    normalized_name = str(credential_name or "api_key").strip().lower() or "api_key"
    try:
        with get_connection(_effective_db_path(db_path, settings)) as conn:
            row = conn.execute(
                """
                SELECT provider_id, credential_name, source, secret_ref, enabled,
                       created_at, updated_at, last_rotated_at
                FROM provider_credentials
                WHERE provider_id = ? AND credential_name = ?
                LIMIT 1
                """,
                (normalized_provider, normalized_name),
            ).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None:
        return None
    return _row_to_record(row)


def list_provider_credentials(
    provider_id: str | None = None,
    *,
    db_path: str | None = None,
    settings: Any | None = None,
) -> list[ProviderCredentialRecord]:
    if settings is None:
        from app.deps import get_settings

        settings = get_settings()
    query = """
        SELECT provider_id, credential_name, source, secret_ref, enabled,
               created_at, updated_at, last_rotated_at
        FROM provider_credentials
    """
    params: tuple[str, ...] = ()
    if provider_id:
        query += " WHERE provider_id = ?"
        params = (str(provider_id).strip().lower(),)
    query += " ORDER BY provider_id ASC, credential_name ASC"
    try:
        with get_connection(_effective_db_path(db_path, settings)) as conn:
            rows = conn.execute(query, params).fetchall()
    except sqlite3.OperationalError:
        return []
    return [_row_to_record(row) for row in rows]


def upsert_provider_credential(
    *,
    provider_id: str,
    source: CredentialSource,
    secret_ref: str | None,
    credential_name: str = "api_key",
    enabled: bool = True,
    rotated: bool = False,
    db_path: str | None = None,
    settings: Any | None = None,
) -> ProviderCredentialRecord:
    if settings is None:
        from app.deps import get_settings

        settings = get_settings()
    normalized_provider = str(provider_id or "").strip().lower()
    normalized_name = str(credential_name or "api_key").strip().lower() or "api_key"
    now = _now_iso()
    existing = get_provider_credential(
        normalized_provider,
        credential_name=normalized_name,
        db_path=db_path,
        settings=settings,
    )
    last_rotated_at = now if rotated else (existing.last_rotated_at if existing else None)
    with get_connection(_effective_db_path(db_path, settings)) as conn:
        if existing is None:
            conn.execute(
                """
                INSERT INTO provider_credentials (
                    provider_id, credential_name, source, secret_ref, enabled,
                    created_at, updated_at, last_rotated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_provider,
                    normalized_name,
                    source,
                    secret_ref,
                    1 if enabled else 0,
                    now,
                    now,
                    last_rotated_at,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE provider_credentials
                SET source = ?, secret_ref = ?, enabled = ?, updated_at = ?, last_rotated_at = ?
                WHERE provider_id = ? AND credential_name = ?
                """,
                (
                    source,
                    secret_ref,
                    1 if enabled else 0,
                    now,
                    last_rotated_at,
                    normalized_provider,
                    normalized_name,
                ),
            )
    record = get_provider_credential(
        normalized_provider,
        credential_name=normalized_name,
        db_path=db_path,
        settings=settings,
    )
    assert record is not None
    return record


def delete_provider_credential(
    provider_id: str,
    *,
    credential_name: str = "api_key",
    db_path: str | None = None,
    settings: Any | None = None,
) -> bool:
    if settings is None:
        from app.deps import get_settings

        settings = get_settings()
    normalized_provider = str(provider_id or "").strip().lower()
    normalized_name = str(credential_name or "api_key").strip().lower() or "api_key"
    with get_connection(_effective_db_path(db_path, settings)) as conn:
        cursor = conn.execute(
            """
            DELETE FROM provider_credentials
            WHERE provider_id = ? AND credential_name = ?
            """,
            (normalized_provider, normalized_name),
        )
    return cursor.rowcount > 0
