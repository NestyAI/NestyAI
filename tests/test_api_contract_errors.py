from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app


def test_error_shape_invalid_model(monkeypatch) -> None:
    settings = Settings(
        app_env="development",
        diagnostics_enabled=True,
        require_api_key=False,
    )
    monkeypatch.setattr("app.deps.get_settings", lambda: settings)

    app = create_app(settings)
    client = TestClient(app)

    payload = {
        "model": "not-real-model-12345",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": False,
    }

    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 400
    data = response.json()

    assert "error" in data
    assert data["error"]["code"] == "invalid_model"
    assert "message" in data["error"]
    assert data["error"]["type"] == "invalid_request_error"


def test_error_shape_invalid_search_mode(monkeypatch) -> None:
    settings = Settings(
        app_env="development",
        diagnostics_enabled=True,
        require_api_key=False,
    )
    monkeypatch.setattr("app.deps.get_settings", lambda: settings)

    app = create_app(settings)
    client = TestClient(app)

    payload = {
        "model": "nesty-combined-1.0",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": False,
        "search": "invalid_value_here",
    }

    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 400
    data = response.json()

    assert "error" in data
    assert data["error"]["code"] == "invalid_search_mode"
    assert "message" in data["error"]
    assert data["error"]["type"] == "invalid_request_error"


def test_error_shape_missing_api_key_when_auth_enabled(monkeypatch) -> None:
    settings = Settings(
        app_env="development",
        diagnostics_enabled=True,
        require_api_key=True,  # Auth enabled
    )
    monkeypatch.setattr("app.deps.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.chat.get_settings", lambda: settings)
    monkeypatch.setattr("app.security.auth.get_settings", lambda: settings)

    app = create_app(settings)
    client = TestClient(app)

    payload = {
        "model": "nesty-combined-1.0",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": False,
    }

    # No authorization header passed
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 401
    data = response.json()

    assert "error" in data
    assert data["error"]["code"] == "missing_api_key"
    assert "message" in data["error"]
    assert data["error"]["type"] == "authentication_error"
