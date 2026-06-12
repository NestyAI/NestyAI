from __future__ import annotations

from app.config import Settings
from app.deps import set_runtime_settings
from app.storage.db import init_db


def _admin_headers(token: str = "admin-token") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _enable_settings(tmp_path, **overrides) -> Settings:
    base = {
        "internal_admin_enabled": True,
        "nesty_internal_admin_token": "admin-token",
        "nesty_console_client_auth_required": False,
        "nesty_db_path": str(tmp_path / "builtin_creds.db"),
        "nesty_provider_secret_dir": str(tmp_path / "provider_secrets"),
        "nesty_provider_credentials_enabled": True,
        "require_api_key": False,
        "public_models": True,
        "public_health": True,
        "trusted_hosts": "testserver",
        "openai_api_key": "env-openai-key",
    }
    base.update(overrides)
    return Settings(**base)


def _patch_settings(monkeypatch, settings: Settings) -> None:
    set_runtime_settings(settings)
    monkeypatch.setattr("app.deps.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.internal_console_builtin_credentials.get_settings", lambda: settings)


def test_list_builtin_providers(client, monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "builtin_creds.db")
    init_db(db_path)
    settings = _enable_settings(tmp_path)
    _patch_settings(monkeypatch, settings)

    response = client.get("/internal/console/runtime/builtin-providers", headers=_admin_headers())
    assert response.status_code == 200
    body = response.json()
    provider_ids = {item["provider_id"] for item in body["providers"]}
    assert "openai" in provider_ids
    assert "google_gemini" in provider_ids
    assert "sk-" not in response.text


def test_put_managed_api_key_requires_feature_enabled(client, monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "builtin_creds.db")
    init_db(db_path)
    settings = _enable_settings(tmp_path, nesty_provider_credentials_enabled=False)
    _patch_settings(monkeypatch, settings)

    response = client.put(
        "/internal/console/runtime/builtin-providers/openai/credentials/api-key",
        headers=_admin_headers(),
        json={"api_key": "sk-managed"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "provider_credentials_disabled"


def test_put_and_delete_managed_api_key(client, monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "builtin_creds.db")
    init_db(db_path)
    settings = _enable_settings(tmp_path, openai_api_key=None)
    _patch_settings(monkeypatch, settings)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    put_response = client.put(
        "/internal/console/runtime/builtin-providers/openai/credentials/api-key",
        headers=_admin_headers(),
        json={"api_key": "sk-managed-openai"},
    )
    assert put_response.status_code == 200
    put_body = put_response.json()
    assert put_body["credential"]["secret_status"] == "configured"
    assert put_body["credential"]["source"] == "managed_store"
    assert "sk-managed" not in put_response.text

    get_response = client.get(
        "/internal/console/runtime/builtin-providers/openai/credentials",
        headers=_admin_headers(),
    )
    assert get_response.status_code == 200
    credentials = get_response.json()["credentials"]
    assert credentials[0]["source"] == "managed_store"
    assert "sk-managed" not in get_response.text

    delete_response = client.delete(
        "/internal/console/runtime/builtin-providers/openai/credentials/api-key",
        headers=_admin_headers(),
    )
    assert delete_response.status_code == 200


def test_builtin_provider_test_endpoint(client, monkeypatch, tmp_path, httpx_mock) -> None:
    db_path = str(tmp_path / "builtin_creds.db")
    init_db(db_path)
    settings = _enable_settings(tmp_path, openai_api_key="sk-test")
    _patch_settings(monkeypatch, settings)
    httpx_mock.add_response(
        url="https://api.openai.com/v1/chat/completions",
        json={
            "choices": [{"message": {"content": "OK"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    )

    response = client.post(
        "/internal/console/runtime/builtin-providers/openai/credentials/api-key/test",
        headers=_admin_headers(),
        json={"message": "Reply with exactly: OK"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["test_result"]["ok"] is True
    assert "sk-test" not in response.text
