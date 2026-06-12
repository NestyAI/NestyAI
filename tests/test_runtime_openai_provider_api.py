
def _admin_headers(token: str = "admin-token") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _runtime_settings(db_path: str, secret_dir: str, **overrides):
    base = {
        "internal_admin_enabled": True,
        "nesty_internal_admin_token": "admin-token",
        "nesty_console_client_auth_required": False,
        "nesty_db_path": db_path,
        "nesty_runtime_openai_providers_enabled": True,
        "nesty_runtime_provider_secret_mode": "file",
        "nesty_runtime_provider_secret_dir": secret_dir,
        "require_api_key": False,
        "public_models": True,
        "public_health": True,
        "trusted_hosts": "testserver",
    }
    base.update(overrides)
    return type("S", (), base)()


def test_runtime_provider_api_crud(client, monkeypatch, tmp_path) -> None:
    from app.storage.db import init_db

    db_path = str(tmp_path / "api_runtime.db")
    secret_dir = str(tmp_path / "provider_secrets")
    init_db(db_path)
    settings_obj = _runtime_settings(db_path, secret_dir)
    monkeypatch.setattr("app.deps.get_settings", lambda: settings_obj)
    monkeypatch.setattr("app.api.internal_console_runtime_providers.get_settings", lambda: settings_obj)

    create = client.post(
        "/internal/console/runtime/providers/openai-compatible",
        headers=_admin_headers(),
        json={
            "provider_id": "custom_api",
            "display_name": "Custom API",
            "base_url": "https://api.example.com",
            "api_key_mode": "secret_file",
            "api_key": "file-secret-value-1234567890",
        },
    )
    assert create.status_code == 200
    body = create.json()
    assert body["ok"] is True
    assert body["provider_id"] == "custom_api"
    assert "file-secret-value" not in str(body)

    listed = client.get("/internal/console/runtime/providers", headers=_admin_headers())
    assert listed.status_code == 200
    provider_ids = {item["provider_id"] for item in listed.json()["providers"]}
    assert "custom_api" in provider_ids

    detail = client.get("/internal/console/runtime/providers/custom_api", headers=_admin_headers())
    assert detail.status_code == 200
    assert detail.json()["secret_status"] in {"stored", "env_ref", "none", "missing"}

    disable = client.post("/internal/console/runtime/providers/custom_api/disable", headers=_admin_headers())
    assert disable.status_code == 200
    assert disable.json()["semantics"] == "persistent_enabled_false"

    delete = client.delete("/internal/console/runtime/providers/custom_api", headers=_admin_headers())
    assert delete.status_code == 200


def test_builtin_disable_uses_routing_semantics(client, monkeypatch, tmp_path) -> None:
    from app.storage.db import init_db

    db_path = str(tmp_path / "api_builtin.db")
    init_db(db_path)
    settings_obj = _runtime_settings(db_path, str(tmp_path / "secrets"))
    monkeypatch.setattr("app.deps.get_settings", lambda: settings_obj)
    monkeypatch.setattr("app.api.internal_console_runtime_providers.get_settings", lambda: settings_obj)

    response = client.post("/internal/console/runtime/providers/groq/disable", headers=_admin_headers())
    assert response.status_code == 200
    assert response.json()["semantics"] == "routing_only"


def test_public_api_key_rejected_on_runtime_provider_api(client, monkeypatch, tmp_path) -> None:
    from app.storage.db import init_db

    db_path = str(tmp_path / "api_public.db")
    init_db(db_path)
    settings_obj = _runtime_settings(db_path, str(tmp_path / "secrets"))
    monkeypatch.setattr("app.deps.get_settings", lambda: settings_obj)
    monkeypatch.setattr("app.api.internal_console_runtime_providers.get_settings", lambda: settings_obj)

    response = client.get(
        "/internal/console/runtime/providers",
        headers={"Authorization": "Bearer nsk_public_key_should_not_work"},
    )
    assert response.status_code == 401
