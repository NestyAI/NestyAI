from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.provider_health_service import should_skip_provider_target
from app.storage.db import init_db
from app.storage.provider_health import record_provider_health_check


def _cfg(
    *,
    aware: bool = True,
    strict: bool = False,
    ttl_seconds: int = 900,
    failure_threshold: int = 2,
    skip_statuses: str = "failed,unavailable,timeout",
    allow_stale_after_seconds: int = 3600,
):
    return type(
        "S",
        (),
        {
            "provider_health_aware_routing": aware,
            "provider_health_strict_mode": strict,
            "provider_health_ttl_seconds": ttl_seconds,
            "provider_health_failure_threshold": failure_threshold,
            "provider_health_skip_statuses": skip_statuses,
            "provider_health_allow_stale_after_seconds": allow_stale_after_seconds,
        },
    )()


def _iso(seconds_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


def test_health_awareness_disabled_never_skips(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "provider_health_service_disabled.db")
    init_db(db_path)
    monkeypatch.setattr("app.core.provider_health_service.get_settings", lambda: type("S", (), {"nesty_db_path": db_path})())
    decision = should_skip_provider_target(
        provider="openrouter",
        model="m1",
        model_alias="nesty-combined-1.0",
        role="main",
        config=_cfg(aware=False),
    )
    assert decision["skip"] is False
    assert decision["reason"] == "health_awareness_disabled"


def test_no_recent_health_allowed_in_non_strict(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "provider_health_service_non_strict.db")
    init_db(db_path)
    monkeypatch.setattr("app.core.provider_health_service.get_settings", lambda: type("S", (), {"nesty_db_path": db_path})())
    decision = should_skip_provider_target(
        provider="openrouter",
        model="m1",
        model_alias="nesty-combined-1.0",
        role="main",
        config=_cfg(aware=True, strict=False),
    )
    assert decision["skip"] is False
    assert decision["reason"] == "no_recent_health"


def test_no_recent_health_skipped_in_strict(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "provider_health_service_strict.db")
    init_db(db_path)
    monkeypatch.setattr("app.core.provider_health_service.get_settings", lambda: type("S", (), {"nesty_db_path": db_path})())
    decision = should_skip_provider_target(
        provider="openrouter",
        model="m1",
        model_alias="nesty-combined-1.0",
        role="main",
        config=_cfg(aware=True, strict=True),
    )
    assert decision["skip"] is True
    assert decision["reason"] == "strict_no_health"


def test_recent_ok_status_allows_provider(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "provider_health_service_ok.db")
    init_db(db_path)
    monkeypatch.setattr("app.core.provider_health_service.get_settings", lambda: type("S", (), {"nesty_db_path": db_path})())
    _ = record_provider_health_check(
        provider="openrouter",
        model="m1",
        model_alias="nesty-combined-1.0",
        role="main",
        status="ok",
        checked_at=_iso(5),
        db_path=db_path,
    )
    decision = should_skip_provider_target(
        provider="openrouter",
        model="m1",
        model_alias="nesty-combined-1.0",
        role="main",
        config=_cfg(aware=True, strict=False, ttl_seconds=900),
    )
    assert decision["skip"] is False
    assert decision["reason"] == "healthy_recent"
    assert decision["latest_status"] == "ok"


def test_recent_failures_over_threshold_skips(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "provider_health_service_failures.db")
    init_db(db_path)
    monkeypatch.setattr("app.core.provider_health_service.get_settings", lambda: type("S", (), {"nesty_db_path": db_path})())
    _ = record_provider_health_check(
        provider="openrouter",
        model="m1",
        model_alias="nesty-combined-1.0",
        role="main",
        status="failed",
        checked_at=_iso(5),
        db_path=db_path,
    )
    _ = record_provider_health_check(
        provider="openrouter",
        model="m1",
        model_alias="nesty-combined-1.0",
        role="main",
        status="timeout",
        checked_at=_iso(20),
        db_path=db_path,
    )
    decision = should_skip_provider_target(
        provider="openrouter",
        model="m1",
        model_alias="nesty-combined-1.0",
        role="main",
        config=_cfg(aware=True, strict=False, ttl_seconds=900, failure_threshold=2),
    )
    assert decision["skip"] is True
    assert decision["reason"] == "recent_failures"
    assert decision["bad_count"] >= 2


def test_stale_failure_outside_ttl_does_not_skip_non_strict(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "provider_health_service_stale.db")
    init_db(db_path)
    monkeypatch.setattr("app.core.provider_health_service.get_settings", lambda: type("S", (), {"nesty_db_path": db_path})())
    _ = record_provider_health_check(
        provider="openrouter",
        model="m1",
        model_alias="nesty-combined-1.0",
        role="main",
        status="failed",
        checked_at=_iso(1200),
        db_path=db_path,
    )
    decision = should_skip_provider_target(
        provider="openrouter",
        model="m1",
        model_alias="nesty-combined-1.0",
        role="main",
        config=_cfg(aware=True, strict=False, ttl_seconds=900, allow_stale_after_seconds=3600),
    )
    assert decision["skip"] is False
    assert decision["reason"] == "no_recent_health"
