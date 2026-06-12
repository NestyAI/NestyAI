from __future__ import annotations

from app.storage.db import init_db


def _admin_headers(token: str = "admin-token") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_console_runtime_requires_internal_admin(client, monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "console_runtime.db")
    init_db(db_path)
    monkeypatch.setattr(
        "app.deps.get_settings",
        lambda: type(
            "S",
            (),
            {
                "internal_admin_enabled": False,
                "nesty_internal_admin_token": "admin-token",
                "nesty_console_client_auth_required": False,
                "nesty_db_path": db_path,
                "require_api_key": False,
                "public_models": True,
                "public_health": True,
                "trusted_hosts": "testserver",
            },
        )(),
    )
    response = client.get("/internal/console/runtime/status", headers=_admin_headers())
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "internal_admin_disabled"


def test_console_runtime_rejects_public_api_key(client, monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "console_runtime2.db")
    init_db(db_path)
    monkeypatch.setattr(
        "app.deps.get_settings",
        lambda: type(
            "S",
            (),
            {
                "internal_admin_enabled": True,
                "nesty_internal_admin_token": "admin-token",
                "nesty_console_client_auth_required": False,
                "nesty_db_path": db_path,
                "require_api_key": False,
                "public_models": True,
                "public_health": True,
                "trusted_hosts": "testserver",
            },
        )(),
    )
    response = client.get(
        "/internal/console/runtime/status",
        headers={"Authorization": "Bearer nsk_public_key_should_not_work"},
    )
    assert response.status_code == 401


def test_console_runtime_update_model_config(client, monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "console_runtime3.db")
    init_db(db_path)
    monkeypatch.setattr(
        "app.deps.get_settings",
        lambda: type(
            "S",
            (),
            {
                "internal_admin_enabled": True,
                "nesty_internal_admin_token": "admin-token",
                "nesty_console_client_auth_required": False,
                "nesty_db_path": db_path,
                "require_api_key": False,
                "public_models": True,
                "public_health": True,
                "trusted_hosts": "testserver",
            },
        )(),
    )
    response = client.post(
        "/internal/console/runtime/model-configs/nesty-flash-1.0",
        headers=_admin_headers(),
        json={"override": {"display_name": "Flash Runtime"}, "changed_by_label": "test"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert "display_name" in body["changed_fields"]
    assert "admin-token" not in str(body)
    assert "NESTY_INTERNAL_ADMIN_TOKEN" not in str(body)


def test_console_runtime_validate_rejects_secret_like_override(client, monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "console_runtime4.db")
    init_db(db_path)
    monkeypatch.setattr(
        "app.deps.get_settings",
        lambda: type(
            "S",
            (),
            {
                "internal_admin_enabled": True,
                "nesty_internal_admin_token": "admin-token",
                "nesty_console_client_auth_required": False,
                "nesty_db_path": db_path,
                "require_api_key": False,
                "public_models": True,
                "public_health": True,
                "trusted_hosts": "testserver",
            },
        )(),
    )
    response = client.post(
        "/internal/console/runtime/validate",
        headers=_admin_headers(),
        json={
            "model_id": "nesty-flash-1.0",
            "override": {"provider_chain": [{"provider": "groq", "model": "sk-secret-model"}]},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["validation_warnings"]
    assert "sk-secret-model" not in str(body.get("validation_warnings"))
