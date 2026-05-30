from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

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


def _safe_parse_json_object(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _safe_parse_embedding(raw: str | None) -> list[float] | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, list):
        return None
    vector: list[float] = []
    for item in parsed:
        try:
            vector.append(float(item))
        except (TypeError, ValueError):
            return None
    return vector


def _row_to_payload(row) -> dict[str, Any] | None:
    embedding = _safe_parse_embedding(row["embedding_json"])
    if embedding is None:
        return None
    return {
        "id": row["id"],
        "owner_type": row["owner_type"],
        "owner_id": row["owner_id"],
        "api_key_id": row["api_key_id"],
        "provider": row["provider"],
        "model": row["model"],
        "dimensions": int(row["dimensions"]) if row["dimensions"] is not None else len(embedding),
        "content_hash": row["content_hash"],
        "embedding": embedding,
        "metadata": _safe_parse_json_object(row["metadata"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def create_embedding_record(
    owner_type: str,
    owner_id: str,
    api_key_id: str | None,
    provider: str,
    model: str,
    embedding: list[float],
    content_hash: str,
    metadata: dict | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    now = _now_iso()
    record_id = f"emb_{uuid4().hex[:16]}"
    embedding_json = json.dumps([float(item) for item in embedding], ensure_ascii=True)
    metadata_json = json.dumps(metadata, ensure_ascii=True) if metadata is not None else None
    dimensions = len(embedding)

    with get_connection(_effective_db_path(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO embedding_records
            (id, owner_type, owner_id, api_key_id, provider, model, dimensions, content_hash, embedding_json, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record_id,
                owner_type,
                owner_id,
                api_key_id,
                provider,
                model,
                dimensions,
                content_hash,
                embedding_json,
                metadata_json,
                now,
                now,
            ),
        )
        conn.commit()
    return {
        "id": record_id,
        "owner_type": owner_type,
        "owner_id": owner_id,
        "api_key_id": api_key_id,
        "provider": provider,
        "model": model,
        "dimensions": dimensions,
        "content_hash": content_hash,
        "embedding": [float(item) for item in embedding],
        "metadata": metadata,
        "created_at": now,
        "updated_at": now,
    }


def get_embedding_for_owner(
    owner_type: str,
    owner_id: str,
    provider: str | None = None,
    model: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any] | None:
    sql = """
        SELECT id, owner_type, owner_id, api_key_id, provider, model, dimensions,
               content_hash, embedding_json, metadata, created_at, updated_at
        FROM embedding_records
        WHERE owner_type = ? AND owner_id = ?
    """
    params: list[Any] = [owner_type, owner_id]
    if provider:
        sql += " AND provider = ?"
        params.append(provider)
    if model:
        sql += " AND model = ?"
        params.append(model)
    sql += " ORDER BY updated_at DESC LIMIT 1"

    with get_connection(_effective_db_path(db_path)) as conn:
        row = conn.execute(sql, tuple(params)).fetchone()
    if row is None:
        return None
    return _row_to_payload(row)


def list_embeddings_for_owner(
    owner_type: str,
    owner_id: str,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    with get_connection(_effective_db_path(db_path)) as conn:
        rows = conn.execute(
            """
            SELECT id, owner_type, owner_id, api_key_id, provider, model, dimensions,
                   content_hash, embedding_json, metadata, created_at, updated_at
            FROM embedding_records
            WHERE owner_type = ? AND owner_id = ?
            ORDER BY updated_at DESC
            """,
            (owner_type, owner_id),
        ).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        parsed = _row_to_payload(row)
        if parsed is not None:
            items.append(parsed)
    return items


def delete_embeddings_for_owner(owner_type: str, owner_id: str, db_path: str | None = None) -> int:
    with get_connection(_effective_db_path(db_path)) as conn:
        cursor = conn.execute(
            "DELETE FROM embedding_records WHERE owner_type = ? AND owner_id = ?",
            (owner_type, owner_id),
        )
        conn.commit()
    return int(cursor.rowcount or 0)


def count_embedding_records(db_path: str | None = None) -> int:
    with get_connection(_effective_db_path(db_path)) as conn:
        row = conn.execute("SELECT COUNT(*) AS total FROM embedding_records").fetchone()
    return int(row["total"]) if row else 0


def upsert_embedding_record(
    owner_type: str,
    owner_id: str,
    api_key_id: str | None,
    provider: str,
    model: str,
    embedding: list[float],
    content_hash: str,
    metadata: dict | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    existing = get_embedding_for_owner(
        owner_type=owner_type,
        owner_id=owner_id,
        provider=provider,
        model=model,
        db_path=db_path,
    )
    if existing is None:
        return create_embedding_record(
            owner_type=owner_type,
            owner_id=owner_id,
            api_key_id=api_key_id,
            provider=provider,
            model=model,
            embedding=embedding,
            content_hash=content_hash,
            metadata=metadata,
            db_path=db_path,
        )

    now = _now_iso()
    embedding_json = json.dumps([float(item) for item in embedding], ensure_ascii=True)
    metadata_json = json.dumps(metadata, ensure_ascii=True) if metadata is not None else None
    with get_connection(_effective_db_path(db_path)) as conn:
        conn.execute(
            """
            UPDATE embedding_records
            SET api_key_id = ?, dimensions = ?, content_hash = ?, embedding_json = ?, metadata = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                api_key_id,
                len(embedding),
                content_hash,
                embedding_json,
                metadata_json,
                now,
                existing["id"],
            ),
        )
        conn.commit()

    updated = get_embedding_for_owner(
        owner_type=owner_type,
        owner_id=owner_id,
        provider=provider,
        model=model,
        db_path=db_path,
    )
    if updated is None:
        return {
            "id": existing["id"],
            "owner_type": owner_type,
            "owner_id": owner_id,
            "api_key_id": api_key_id,
            "provider": provider,
            "model": model,
            "dimensions": len(embedding),
            "content_hash": content_hash,
            "embedding": [float(item) for item in embedding],
            "metadata": metadata,
            "created_at": existing["created_at"],
            "updated_at": now,
        }
    return updated


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    if len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def search_similar_embeddings(
    query_embedding: list[float],
    api_key_id: str | None,
    owner_type: str = "conversation_message",
    conversation_id: str | None = None,
    scope: str = "conversation",
    top_k: int = 5,
    min_score: float = 0.72,
    include_roles: list[str] | None = None,
    exclude_owner_ids: list[str] | None = None,
    candidate_limit: int = 500,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    query_dim = len(query_embedding)
    if query_dim <= 0:
        return []
    scope_mode = str(scope or "conversation").strip().lower()
    if scope_mode not in {"conversation", "api_key", "all_accessible"}:
        scope_mode = "conversation"
    top_k = max(1, int(top_k))
    candidate_limit = max(top_k, int(candidate_limit))
    include_roles_clean = [str(role).strip().lower() for role in (include_roles or []) if str(role).strip()]
    exclude_ids = [str(item).strip() for item in (exclude_owner_ids or []) if str(item).strip()]

    sql = """
        SELECT
            e.id,
            e.owner_type,
            e.owner_id,
            e.api_key_id,
            e.provider,
            e.model,
            e.dimensions,
            e.embedding_json,
            e.metadata,
            m.conversation_id,
            m.role,
            m.content,
            m.created_at
        FROM embedding_records e
        JOIN conversation_messages m ON m.id = e.owner_id
        JOIN conversations c ON c.id = m.conversation_id
        WHERE e.owner_type = ?
          AND c.archived_at IS NULL
    """
    params: list[Any] = [owner_type]

    # Ownership boundary: never cross API key ownership.
    if api_key_id is None:
        sql += " AND c.api_key_id IS NULL"
    else:
        sql += " AND c.api_key_id = ?"
        params.append(api_key_id)

    if scope_mode == "conversation":
        if not conversation_id:
            return []
        sql += " AND m.conversation_id = ?"
        params.append(conversation_id)
    elif scope_mode in {"api_key", "all_accessible"}:
        # Ownership filter above already enforces accessible boundaries for current caller.
        pass

    if include_roles_clean:
        placeholders = ",".join("?" for _ in include_roles_clean)
        sql += f" AND LOWER(m.role) IN ({placeholders})"
        params.extend(include_roles_clean)

    if exclude_ids:
        placeholders = ",".join("?" for _ in exclude_ids)
        sql += f" AND e.owner_id NOT IN ({placeholders})"
        params.extend(exclude_ids)

    sql += " ORDER BY e.updated_at DESC LIMIT ?"
    params.append(candidate_limit)

    with get_connection(_effective_db_path(db_path)) as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()

    matches: list[dict[str, Any]] = []
    for row in rows:
        embedding = _safe_parse_embedding(row["embedding_json"])
        if not embedding:
            continue
        dimensions = int(row["dimensions"]) if row["dimensions"] is not None else len(embedding)
        if dimensions != query_dim or len(embedding) != query_dim:
            continue
        score = cosine_similarity(query_embedding, embedding)
        if score < float(min_score):
            continue
        matches.append(
            {
                "id": row["id"],
                "owner_type": row["owner_type"],
                "owner_id": row["owner_id"],
                "api_key_id": row["api_key_id"],
                "provider": row["provider"],
                "model": row["model"],
                "dimensions": dimensions,
                "score": score,
                "metadata": _safe_parse_json_object(row["metadata"]),
                "conversation_id": row["conversation_id"],
                "role": row["role"],
                "content": row["content"],
                "created_at": row["created_at"],
            }
        )

    matches.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    return matches[:top_k]
