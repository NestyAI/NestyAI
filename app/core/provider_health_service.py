from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.storage.db import get_connection


def get_settings():
    from app.deps import get_settings as deps_get_settings

    return deps_get_settings()


def _effective_db_path(db_path: str | None = None) -> str:
    if db_path:
        return db_path
    return get_settings().nesty_db_path


def _parse_csv_values(raw: str | None) -> set[str]:
    if not raw:
        return set()
    return {item.strip().lower() for item in str(raw).split(",") if item.strip()}


def _parse_iso_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw))
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _base_response(reason: str) -> dict[str, Any]:
    return {
        "healthy": True,
        "skip": False,
        "reason": reason,
        "latest_status": None,
        "bad_count": 0,
        "checked_at": None,
    }


def get_recent_health_status(
    provider: str,
    model: str,
    model_alias: str | None = None,
    role: str | None = None,
) -> dict:
    provider_name = str(provider or "").strip()
    model_name = str(model or "").strip()
    if not provider_name or not model_name:
        return {
            "provider": provider_name,
            "model": model_name,
            "latest": None,
            "rows": [],
            "error": "invalid_target",
        }

    query = """
        SELECT provider, model, model_alias, role, status, checked_at
        FROM provider_health_checks
        WHERE provider = ? AND model = ?
    """
    params: list[Any] = [provider_name, model_name]
    if str(model_alias or "").strip():
        query += " AND model_alias = ?"
        params.append(str(model_alias).strip())
    if str(role or "").strip():
        query += " AND role = ?"
        params.append(str(role).strip())
    query += " ORDER BY checked_at DESC LIMIT 100"

    try:
        with get_connection(_effective_db_path()) as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
    except Exception:
        return {
            "provider": provider_name,
            "model": model_name,
            "latest": None,
            "rows": [],
            "error": "lookup_failed",
        }

    data = [
        {
            "provider": row["provider"],
            "model": row["model"],
            "model_alias": row["model_alias"],
            "role": row["role"],
            "status": row["status"],
            "checked_at": row["checked_at"],
        }
        for row in rows
    ]
    return {
        "provider": provider_name,
        "model": model_name,
        "latest": data[0] if data else None,
        "rows": data,
        "error": None,
    }


def is_provider_target_healthy(
    provider: str,
    model: str,
    model_alias: str | None,
    role: str | None,
    config,
) -> dict:
    if not bool(getattr(config, "provider_health_aware_routing", False)):
        return _base_response("health_awareness_disabled")

    strict_mode = bool(getattr(config, "provider_health_strict_mode", False))
    ttl_seconds = max(1, int(getattr(config, "provider_health_ttl_seconds", 900)))
    failure_threshold = max(1, int(getattr(config, "provider_health_failure_threshold", 2)))
    allow_stale_after_seconds = max(ttl_seconds, int(getattr(config, "provider_health_allow_stale_after_seconds", 3600)))
    skip_statuses = _parse_csv_values(getattr(config, "provider_health_skip_statuses", "failed,unavailable,timeout"))

    recent = get_recent_health_status(
        provider=provider,
        model=model,
        model_alias=model_alias,
        role=role,
    )
    latest = recent.get("latest")
    if recent.get("error"):
        # Lookup failures should not block chat by default.
        if strict_mode:
            payload = _base_response("strict_no_health")
            payload["healthy"] = False
            payload["skip"] = True
            return payload
        return _base_response("no_recent_health")

    if not latest:
        if strict_mode:
            payload = _base_response("strict_no_health")
            payload["healthy"] = False
            payload["skip"] = True
            return payload
        return _base_response("no_recent_health")

    now = _now_utc()
    latest_checked = _parse_iso_datetime(latest.get("checked_at"))
    latest_status = str(latest.get("status") or "").strip().lower() or None
    payload = _base_response("healthy_recent")
    payload["latest_status"] = latest_status
    payload["checked_at"] = latest.get("checked_at")

    if latest_checked is None:
        if strict_mode:
            payload.update({"healthy": False, "skip": True, "reason": "strict_no_health"})
            return payload
        payload["reason"] = "no_recent_health"
        return payload

    age_seconds = (now - latest_checked).total_seconds()
    if age_seconds > allow_stale_after_seconds:
        if strict_mode:
            payload.update({"healthy": False, "skip": True, "reason": "strict_no_health"})
            return payload
        payload["reason"] = "no_recent_health"
        return payload

    if age_seconds > ttl_seconds:
        if strict_mode:
            payload.update({"healthy": False, "skip": True, "reason": "strict_no_health"})
            return payload
        payload["reason"] = "no_recent_health"
        return payload

    window_start = now - timedelta(seconds=ttl_seconds)
    bad_count = 0
    for row in recent.get("rows") or []:
        status = str(row.get("status") or "").strip().lower()
        checked = _parse_iso_datetime(row.get("checked_at"))
        if checked is None or checked < window_start:
            continue
        if status in skip_statuses:
            bad_count += 1
    payload["bad_count"] = bad_count

    if latest_status in skip_statuses and bad_count >= failure_threshold:
        payload.update({"healthy": False, "skip": True, "reason": "recent_failures"})
        return payload

    payload.update({"healthy": True, "skip": False, "reason": "healthy_recent"})
    return payload


def should_skip_provider_target(
    provider: str,
    model: str,
    model_alias: str | None,
    role: str | None,
    config,
) -> dict:
    return is_provider_target_healthy(
        provider=provider,
        model=model,
        model_alias=model_alias,
        role=role,
        config=config,
    )


def summarize_health_for_targets(targets: list[dict], config) -> dict:
    items: list[dict[str, Any]] = []
    skipped_targets: list[dict[str, str]] = []
    for target in targets:
        provider = str(target.get("provider") or "").strip()
        model = str(target.get("model") or "").strip()
        model_alias = str(target.get("model_alias") or "").strip() or None
        role = str(target.get("role") or "").strip() or None
        decision = should_skip_provider_target(
            provider=provider,
            model=model,
            model_alias=model_alias,
            role=role,
            config=config,
        )
        items.append(
            {
                "provider": provider,
                "model": model,
                "model_alias": model_alias,
                "role": role,
                **decision,
            }
        )
        if bool(decision.get("skip")):
            skipped_targets.append(
                {
                    "provider": provider,
                    "model": model,
                    "reason": str(decision.get("reason") or "recent_failures"),
                }
            )
    aware = bool(getattr(config, "provider_health_aware_routing", False))
    strict = bool(getattr(config, "provider_health_strict_mode", False))
    return {
        "aware_routing": aware,
        "strict_mode": strict,
        "total_targets": len(targets),
        "skipped_count": len(skipped_targets),
        "skipped_targets": skipped_targets,
        "targets": items,
        "fallback_to_unhealthy_allowed": aware and not strict,
    }
