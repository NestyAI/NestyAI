from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app


def test_models_list_shape_and_ids(monkeypatch) -> None:
    settings = Settings(
        app_env="development",
        diagnostics_enabled=True,
        require_api_key=False,
    )
    monkeypatch.setattr("app.deps.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.models.get_settings", lambda: settings)
    monkeypatch.setattr("app.security.auth.get_settings", lambda: settings)

    app = create_app(settings)
    client = TestClient(app)

    response = client.get("/v1/models")
    assert response.status_code == 200
    data = response.json()
    
    assert data.get("object") == "list"
    assert "data" in data
    assert isinstance(data["data"], list)
    
    # Verify presence of core model IDs
    ids = {item["id"] for item in data["data"]}
    assert "nesty-flash-1.0" in ids
    assert "nesty-combined-1.0" in ids
    assert "nesty-pro-1.0" in ids

    # Check model object structure
    for model_card in data["data"]:
        assert "id" in model_card
        assert model_card.get("object") == "model"
        assert "owned_by" in model_card
        assert "description" in model_card


def test_internal_endpoints_hidden_when_admin_disabled(monkeypatch) -> None:
    settings = Settings(
        app_env="development",
        diagnostics_enabled=True,
        internal_admin_enabled=False,  # disabled
        nesty_internal_admin_token="",
    )
    monkeypatch.setattr("app.deps.get_settings", lambda: settings)
    monkeypatch.setattr("app.security.internal_auth.get_settings", lambda: settings)

    app = create_app(settings)
    client = TestClient(app)

    # Test configs endpoint
    response = client.get("/internal/model-configs")
    assert response.status_code == 404
    data = response.json()
    assert data["error"]["code"] == "internal_admin_disabled"

    # Test embeddings test endpoint
    response = client.post("/internal/embeddings/test", json={})
    assert response.status_code == 404
    
    # Test diagnostics endpoint
    response = client.get("/internal/diagnostics/provider-health")
    assert response.status_code == 404
