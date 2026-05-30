from __future__ import annotations

from app.storage.db import init_db
from app.storage.provider_health import record_provider_health_check


def test_provider_health_summary_endpoint_requires_internal_admin(client, monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "provider_health_summary_requires_admin.db")
    init_db(db_path)
    monkeypatch.setattr(
        "app.security.internal_auth.get_settings",
        lambda: type("S", (), {"internal_admin_enabled": True, "nesty_internal_admin_token": "abc"})(),
    )
    monkeypatch.setattr(
        "app.api.internal_diagnostics.get_settings",
        lambda: type("S", (), {"diagnostics_enabled": True})(),
    )
    response = client.get("/internal/diagnostics/provider-health/summary")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "internal_admin_unauthorized"


def test_provider_health_summary_endpoint_returns_counts(client, monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "provider_health_summary_counts.db")
    init_db(db_path)
    monkeypatch.setattr(
        "app.security.internal_auth.get_settings",
        lambda: type("S", (), {"internal_admin_enabled": True, "nesty_internal_admin_token": "abc"})(),
    )
    monkeypatch.setattr(
        "app.api.internal_diagnostics.get_settings",
        lambda: type("S", (), {"diagnostics_enabled": True})(),
    )
    monkeypatch.setattr("app.storage.provider_health.get_settings", lambda: type("S", (), {"nesty_db_path": db_path})())

    _ = record_provider_health_check(
        provider="openrouter",
        model="m1",
        model_alias="nesty-combined-1.0",
        role="main",
        status="ok",
        db_path=db_path,
    )
    _ = record_provider_health_check(
        provider="openrouter",
        model="m1",
        model_alias="nesty-combined-1.0",
        role="main",
        status="failed",
        db_path=db_path,
    )
    _ = record_provider_health_check(
        provider="groq",
        model="m2",
        model_alias="nesty-flash-1.0",
        role="main",
        status="timeout",
        db_path=db_path,
    )

    response = client.get(
        "/internal/diagnostics/provider-health/summary",
        headers={"Authorization": "Bearer abc"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["total_checks"] == 3
    assert payload["summary"]["ok"] == 1
    assert payload["summary"]["failed"] == 1
    assert payload["summary"]["timeout"] == 1
    assert isinstance(payload["latest_by_target"], list)
