from __future__ import annotations

from app.config import Settings
from app.core.bootstrap.internal_admin_token import admin_token_status, rotate_file_backed_admin_token
from app.deps import set_runtime_settings
from app.storage.db import init_db


def _admin_headers(token: str = "admin-token") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _patch_settings(monkeypatch, settings: Settings) -> None:
    set_runtime_settings(settings)
    monkeypatch.setattr("app.deps.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.internal_console_security.get_settings", lambda: settings)


def test_admin_token_status_never_exposes_token(client, monkeypatch, tmp_path) -> None:
    init_db(str(tmp_path / "admin.db"))
    settings = Settings(
        internal_admin_enabled=True,
        nesty_internal_admin_token="super-secret-admin-token-value",
        nesty_internal_admin_token_mode="env",
        nesty_console_client_auth_required=False,
        nesty_db_path=str(tmp_path / "admin.db"),
        require_api_key=False,
        public_models=True,
        public_health=True,
        trusted_hosts="testserver",
    )
    _patch_settings(monkeypatch, settings)

    response = client.get(
        "/internal/console/security/admin-token/status",
        headers=_admin_headers("super-secret-admin-token-value"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["admin_auth_metadata"]["mode"] == "env"
    assert body["admin_auth_metadata"]["configured"] is True
    assert "super-secret" not in response.text


def test_rotate_admin_token_rejects_env_mode(client, monkeypatch, tmp_path) -> None:
    init_db(str(tmp_path / "admin2.db"))
    settings = Settings(
        internal_admin_enabled=True,
        nesty_internal_admin_token="admin-token",
        nesty_internal_admin_token_mode="env",
        nesty_console_client_auth_required=False,
        nesty_db_path=str(tmp_path / "admin2.db"),
        require_api_key=False,
        public_models=True,
        public_health=True,
        trusted_hosts="testserver",
    )
    _patch_settings(monkeypatch, settings)

    response = client.post("/internal/console/security/admin-token/rotate", headers=_admin_headers())
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "admin_token_rotation_unsupported_env"


def test_rotate_admin_token_file_mode(client, monkeypatch, tmp_path) -> None:
    init_db(str(tmp_path / "admin3.db"))
    token_file = tmp_path / "admin.token"
    token_file.write_text("nia_old_token_value_1234567890", encoding="utf-8")
    settings = Settings(
        internal_admin_enabled=True,
        nesty_internal_admin_token="nia_old_token_value_1234567890",
        nesty_internal_admin_token_mode="file",
        internal_admin_token_file=str(token_file),
        internal_admin_token_source="file",
        internal_admin_token_file_resolved=str(token_file),
        nesty_console_client_auth_required=False,
        nesty_db_path=str(tmp_path / "admin3.db"),
        require_api_key=False,
        public_models=True,
        public_health=True,
        trusted_hosts="testserver",
    )
    _patch_settings(monkeypatch, settings)

    response = client.post(
        "/internal/console/security/admin-token/rotate",
        headers=_admin_headers("nia_old_token_value_1234567890"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["rotated"] is True
    assert body["admin_auth_metadata"]["rotation_supported"] is True
    assert "nia_old_token" not in response.text
    new_token = token_file.read_text(encoding="utf-8").strip()
    assert new_token.startswith("nia_")
    assert new_token != "nia_old_token_value_1234567890"


def test_admin_token_status_reports_rotation_support(client, monkeypatch, tmp_path) -> None:
    settings = Settings(
        internal_admin_enabled=True,
        nesty_internal_admin_token_mode="file",
        internal_admin_token_source="file",
        nesty_console_client_auth_required=False,
        trusted_hosts="testserver",
    )
    _patch_settings(monkeypatch, settings)
    status = admin_token_status(settings)
    assert status["rotation_supported"] is True
    assert status["rotate_on_start"] is False
