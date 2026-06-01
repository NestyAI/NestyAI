from __future__ import annotations

from app.storage.db import init_db
from app.storage.provider_health import record_provider_health_check


def test_internal_diagnostics_hidden_when_admin_disabled(client, monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "internal_diag_hidden.db")
    init_db(db_path)
    monkeypatch.setattr(
        "app.security.internal_auth.get_settings",
        lambda: type("S", (), {"internal_admin_enabled": False, "nesty_internal_admin_token": "abc"})(),
    )
    response = client.get("/internal/diagnostics/provider-health")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "internal_admin_disabled"


def test_internal_diagnostics_requires_token(client, monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "internal_diag_auth.db")
    init_db(db_path)
    monkeypatch.setattr(
        "app.security.internal_auth.get_settings",
        lambda: type("S", (), {"internal_admin_enabled": True, "nesty_internal_admin_token": "abc"})(),
    )
    monkeypatch.setattr(
        "app.api.internal_diagnostics.get_settings",
        lambda: type("S", (), {"diagnostics_enabled": True})(),
    )
    response = client.get("/internal/diagnostics/provider-health")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "internal_admin_unauthorized"


def test_internal_diagnostics_disabled_returns_404(client, monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "internal_diag_disabled.db")
    init_db(db_path)
    monkeypatch.setattr(
        "app.security.internal_auth.get_settings",
        lambda: type("S", (), {"internal_admin_enabled": True, "nesty_internal_admin_token": "abc"})(),
    )
    monkeypatch.setattr(
        "app.api.internal_diagnostics.get_settings",
        lambda: type("S", (), {"diagnostics_enabled": False})(),
    )
    response = client.get("/internal/diagnostics/provider-health", headers={"Authorization": "Bearer abc"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "diagnostics_disabled"


def test_internal_provider_health_check_uses_model_alias(client, monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "internal_diag_check_alias.db")
    init_db(db_path)
    monkeypatch.setattr(
        "app.security.internal_auth.get_settings",
        lambda: type("S", (), {"internal_admin_enabled": True, "nesty_internal_admin_token": "abc"})(),
    )
    monkeypatch.setattr(
        "app.api.internal_diagnostics.get_settings",
        lambda: type("S", (), {"diagnostics_enabled": True})(),
    )
    captured: dict = {}

    async def _mock_diagnose_model_alias(model_alias: str, include_roles: bool = True, message: str | None = None, dry_run: bool = False):
        captured["model_alias"] = model_alias
        captured["include_roles"] = include_roles
        return {"model_alias": model_alias, "results": [], "summary": {"total": 0, "ok": 0, "failed": 0}}

    monkeypatch.setattr("app.api.internal_diagnostics.diagnose_model_alias", _mock_diagnose_model_alias)
    response = client.post(
        "/internal/diagnostics/provider-health/check",
        headers={"Authorization": "Bearer abc"},
        json={"model_alias": "nesty-combined-1.0", "include_roles": True},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert captured["model_alias"] == "nesty-combined-1.0"


def test_internal_provider_model_check_endpoint(client, monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "internal_diag_model_check.db")
    init_db(db_path)
    monkeypatch.setattr(
        "app.security.internal_auth.get_settings",
        lambda: type("S", (), {"internal_admin_enabled": True, "nesty_internal_admin_token": "abc"})(),
    )
    monkeypatch.setattr(
        "app.api.internal_diagnostics.get_settings",
        lambda: type("S", (), {"diagnostics_enabled": True})(),
    )

    async def _mock_diagnose_provider_model(provider: str, model: str, message: str | None = None, **kwargs):
        return {
            "provider": provider,
            "model": model,
            "status": "ok",
            "latency_ms": 100,
            "tokens_per_second": 10.0,
            "error_code": None,
        }

    monkeypatch.setattr("app.api.internal_diagnostics.diagnose_provider_model", _mock_diagnose_provider_model)
    response = client.post(
        "/internal/diagnostics/provider-model/check",
        headers={"Authorization": "Bearer abc"},
        json={"provider": "openrouter", "model": "deepseek/deepseek-v4-flash:free"},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["result"]["status"] == "ok"


def test_internal_provider_health_check_all_aliases(client, monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "internal_diag_check_all.db")
    init_db(db_path)
    monkeypatch.setattr(
        "app.security.internal_auth.get_settings",
        lambda: type("S", (), {"internal_admin_enabled": True, "nesty_internal_admin_token": "abc"})(),
    )
    monkeypatch.setattr(
        "app.api.internal_diagnostics.get_settings",
        lambda: type("S", (), {"diagnostics_enabled": True})(),
    )
    captured: dict = {}

    async def _mock_diagnose_all(message=None, include_roles=True, dry_run=False):
        captured["called"] = True
        return {"items": [], "summary": {"total": 0, "ok": 0, "failed": 0}}

    monkeypatch.setattr("app.api.internal_diagnostics.diagnose_all_model_aliases", _mock_diagnose_all)
    response = client.post(
        "/internal/diagnostics/provider-health/check",
        headers={"Authorization": "Bearer abc"},
        json={"include_roles": True},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert captured.get("called") is True


def test_internal_provider_health_cleanup_endpoint(client, monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "internal_diag_cleanup.db")
    init_db(db_path)
    monkeypatch.setattr(
        "app.security.internal_auth.get_settings",
        lambda: type("S", (), {"internal_admin_enabled": True, "nesty_internal_admin_token": "abc"})(),
    )
    monkeypatch.setattr(
        "app.api.internal_diagnostics.get_settings",
        lambda: type("S", (), {"diagnostics_enabled": True})(),
    )
    monkeypatch.setattr(
        "app.storage.provider_health.get_settings",
        lambda: type("S", (), {"nesty_db_path": db_path})(),
    )

    record_provider_health_check(
        provider="openrouter",
        model="m1",
        model_alias="nesty-combined-1.0",
        role="main",
        status="failed",
        db_path=db_path,
    )

    response = client.delete(
        "/internal/diagnostics/provider-health",
        headers={"Authorization": "Bearer abc"},
        params={"provider": "openrouter"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["deleted"] == 1
    assert payload["filters"]["provider"] == "openrouter"
