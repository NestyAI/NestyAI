from __future__ import annotations

from dataclasses import dataclass

from app.storage.db import init_db


@dataclass
class _DummyRouteResult:
    provider_used: str
    provider_result: object


@dataclass
class _DummyProviderResult:
    provider: str
    content: str
    usage: object


@dataclass
class _DummyUsage:
    prompt_tokens: int = 1
    completion_tokens: int = 1
    total_tokens: int = 2


class _DummyInternalRouter:
    async def generate_with_provider_chain(
        self,
        request_id,
        provider_chain,
        messages,
        temperature,
        max_tokens,
        trace_label="custom_chain",
    ):
        return _DummyRouteResult(
            provider_used="groq",
            provider_result=_DummyProviderResult(provider="groq", content="OK", usage=_DummyUsage()),
        )


def _set_db_settings(monkeypatch, db_path: str) -> None:
    monkeypatch.setattr("app.storage.model_configs.get_settings", lambda: type("S", (), {"nesty_db_path": db_path})())


def test_internal_endpoints_disabled_return_404(client, monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "internal_disabled.db")
    init_db(db_path)
    _set_db_settings(monkeypatch, db_path)
    monkeypatch.setattr(
        "app.security.internal_auth.get_settings",
        lambda: type("S", (), {"internal_admin_enabled": False, "nesty_internal_admin_token": "abc"})(),
    )
    response = client.get("/internal/model-configs")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "internal_admin_disabled"


def test_internal_endpoints_enabled_missing_token_rejected(client, monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "internal_no_token.db")
    init_db(db_path)
    _set_db_settings(monkeypatch, db_path)
    monkeypatch.setattr(
        "app.security.internal_auth.get_settings",
        lambda: type("S", (), {"internal_admin_enabled": True, "nesty_internal_admin_token": "abc"})(),
    )
    response = client.get("/internal/model-configs")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "internal_admin_unauthorized"


def test_internal_model_config_crud_and_test_endpoint(client, monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "internal_crud.db")
    init_db(db_path)
    _set_db_settings(monkeypatch, db_path)
    monkeypatch.setattr(
        "app.security.internal_auth.get_settings",
        lambda: type("S", (), {"internal_admin_enabled": True, "nesty_internal_admin_token": "abc"})(),
    )
    monkeypatch.setattr("app.api.internal_model_configs.get_provider_router", lambda: _DummyInternalRouter())
    headers = {"Authorization": "Bearer abc"}

    list_resp = client.get("/internal/model-configs", headers=headers)
    assert list_resp.status_code == 200
    assert list_resp.json()["object"] == "list"

    patch_resp = client.patch(
        "/internal/model-configs/nesty-flash-1.0",
        headers=headers,
        json={"override": {"display_name": "Flash Runtime"}, "changed_by_label": "nesty-console"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["ok"] is True
    assert patch_resp.json()["config_source"] == "override"

    get_resp = client.get("/internal/model-configs/nesty-flash-1.0", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["override_config"]["display_name"] == "Flash Runtime"

    test_resp = client.post(
        "/internal/model-configs/nesty-flash-1.0/test",
        headers=headers,
        json={"message": "Reply with only: OK"},
    )
    assert test_resp.status_code == 200
    assert test_resp.json()["ok"] is True
    assert test_resp.json()["provider"] == "groq"

    reset_resp = client.post("/internal/model-configs/nesty-flash-1.0/reset", headers=headers)
    assert reset_resp.status_code == 200
    assert reset_resp.json()["config_source"] == "default"

    audit_resp = client.get("/internal/model-configs/audit?model_id=nesty-flash-1.0&limit=20", headers=headers)
    assert audit_resp.status_code == 200
    actions = [item["action"] for item in audit_resp.json()["data"]]
    assert "create_override" in actions
    assert "reset_override" in actions
    assert "test_config" in actions
