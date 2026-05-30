from __future__ import annotations

import os
import sqlite3
import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.storage.db import init_db, get_connection
from app.storage.provider_health import record_provider_health_check


@pytest.fixture
def temp_db(tmp_path) -> str:
    db_file = tmp_path / "test_diagnostics.db"
    db_path = str(db_file)
    init_db(db_path)
    return db_path


def test_provider_health_summary_endpoint_reliability_enabled(temp_db, monkeypatch) -> None:
    settings = Settings(
        app_env="development",
        nesty_db_path=temp_db,
        diagnostics_enabled=True,
        internal_admin_enabled=True,
        nesty_internal_admin_token="mysecretadmintoken",
        provider_reliability_scoring_enabled=True,
        provider_reliability_min_checks=2,
    )
    monkeypatch.setattr("app.deps.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.internal_diagnostics.get_settings", lambda: settings)
    monkeypatch.setattr("app.security.internal_auth.get_settings", lambda: settings)
    
    app = create_app(settings)
    client = TestClient(app)
    
    # Record some mock checks
    record_provider_health_check(
        provider="groq",
        model="llama-3.1-8b-instant",
        status="ok",
        model_alias="nesty-flash-1.0",
        role="main",
        latency_ms=150,
        db_path=temp_db,
    )
    record_provider_health_check(
        provider="groq",
        model="llama-3.1-8b-instant",
        status="ok",
        model_alias="nesty-flash-1.0",
        role="main",
        latency_ms=250,
        db_path=temp_db,
    )
    record_provider_health_check(
        provider="openrouter",
        model="gemma",
        status="failed",
        model_alias="nesty-combined-1.0",
        role="main",
        db_path=temp_db,
    )

    headers = {"Authorization": "Bearer mysecretadmintoken"}
    response = client.get("/internal/diagnostics/provider-health/summary", headers=headers)
    assert response.status_code == 200
    
    data = response.json()
    assert "reliability" in data
    reliability = data["reliability"]
    assert len(reliability) == 2
    
    # Check groq (2 passes -> low confidence since sample count is 2 (min_checks=2))
    groq_item = next(r for r in reliability if r["provider"] == "groq")
    assert groq_item["reliability_score"] == 1.0
    assert groq_item["confidence"] == "low"
    assert groq_item["sample_count"] == 2
    assert groq_item["avg_latency_ms"] == 200
    
    # Check openrouter (1 fail -> insufficient_data)
    or_item = next(r for r in reliability if r["provider"] == "openrouter")
    assert or_item["reliability_score"] == 0.0
    assert or_item["confidence"] == "insufficient_data"


def test_provider_health_summary_endpoint_reliability_disabled(temp_db, monkeypatch) -> None:
    settings = Settings(
        app_env="development",
        nesty_db_path=temp_db,
        diagnostics_enabled=True,
        internal_admin_enabled=True,
        nesty_internal_admin_token="mysecretadmintoken",
        provider_reliability_scoring_enabled=False,
    )
    monkeypatch.setattr("app.deps.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.internal_diagnostics.get_settings", lambda: settings)
    monkeypatch.setattr("app.security.internal_auth.get_settings", lambda: settings)
    
    app = create_app(settings)
    client = TestClient(app)
    
    headers = {"Authorization": "Bearer mysecretadmintoken"}
    response = client.get("/internal/diagnostics/provider-health/summary", headers=headers)
    assert response.status_code == 200
    
    data = response.json()
    assert data.get("reliability_enabled") is False
    assert data.get("reliability") == []


def test_provider_health_summary_endpoint_empty_db_does_not_crash(tmp_path, monkeypatch) -> None:
    # Use a non-existent database file path (uninitialized db)
    db_path = str(tmp_path / "missing.db")
    settings = Settings(
        app_env="development",
        nesty_db_path=db_path,
        diagnostics_enabled=True,
        internal_admin_enabled=True,
        nesty_internal_admin_token="mysecretadmintoken",
        provider_reliability_scoring_enabled=True,
    )
    monkeypatch.setattr("app.deps.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.internal_diagnostics.get_settings", lambda: settings)
    monkeypatch.setattr("app.security.internal_auth.get_settings", lambda: settings)
    
    # Note: We do NOT call init_db here! Table provider_health_checks is missing.
    
    app = create_app(settings)
    client = TestClient(app)
    
    headers = {"Authorization": "Bearer mysecretadmintoken"}
    response = client.get("/internal/diagnostics/provider-health/summary", headers=headers)
    
    # Should complete successfully (exit code 200) with empty payload
    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["total_checks"] == 0
    assert data["reliability"] == []
