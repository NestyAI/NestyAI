from __future__ import annotations

import argparse
import json
import os
import pytest
from pathlib import Path
from app.config import Settings
from app.storage.db import init_db
from app.storage.provider_health import record_provider_health_check
from scripts import provider_health_summary


@pytest.fixture
def temp_db(tmp_path) -> str:
    db_file = tmp_path / "test_script.db"
    db_path = str(db_file)
    init_db(db_path)
    return db_path


def test_script_imports_without_side_effects() -> None:
    assert callable(provider_health_summary.main)


def test_script_output_with_reliability(temp_db, monkeypatch, capsys) -> None:
    settings = Settings(
        nesty_db_path=temp_db,
        provider_health_ttl_seconds=900,
        provider_reliability_scoring_enabled=True,
        provider_reliability_min_checks=2,
    )
    monkeypatch.setattr("app.deps.get_settings", lambda: settings)
    monkeypatch.setattr("scripts.provider_health_summary.get_settings", lambda: settings)

    # Record test checks
    record_provider_health_check(
        provider="groq",
        model="llama-3.1-8b-instant",
        status="ok",
        model_alias="nesty-flash-1.0",
        role="main",
        latency_ms=120,
        db_path=temp_db,
    )
    record_provider_health_check(
        provider="groq",
        model="llama-3.1-8b-instant",
        status="ok",
        model_alias="nesty-flash-1.0",
        role="main",
        latency_ms=180,
        db_path=temp_db,
    )

    args = argparse.Namespace(
        limit=10,
        provider=None,
        model_alias=None,
        since_seconds=None,
        only_unhealthy=False,
        json=False,
        show_reliability=True,
        window_checks=None,
        min_checks=None,
    )
    
    code = provider_health_summary._run(args)
    assert code == 0
    
    out = capsys.readouterr().out
    assert "score" in out
    assert "confidence" in out
    assert "avg_latency" in out
    assert "1.00" in out  # Score value (1.00)
    assert "low" in out   # Confidence (sample size = 2)


def test_script_output_no_reliability(temp_db, monkeypatch, capsys) -> None:
    settings = Settings(
        nesty_db_path=temp_db,
        provider_health_ttl_seconds=900,
        provider_reliability_scoring_enabled=True,
    )
    monkeypatch.setattr("app.deps.get_settings", lambda: settings)
    monkeypatch.setattr("scripts.provider_health_summary.get_settings", lambda: settings)

    # Record check
    record_provider_health_check(
        provider="groq",
        model="llama-3.1-8b-instant",
        status="ok",
        model_alias="nesty-flash-1.0",
        role="main",
        latency_ms=120,
        db_path=temp_db,
    )

    args = argparse.Namespace(
        limit=10,
        provider=None,
        model_alias=None,
        since_seconds=None,
        only_unhealthy=False,
        json=False,
        show_reliability=False,  # Explicitly disabled
        window_checks=None,
        min_checks=None,
    )
    
    code = provider_health_summary._run(args)
    assert code == 0
    
    out = capsys.readouterr().out
    # Reliability columns should not be shown
    assert "score" not in out
    assert "confidence" not in out


def test_script_output_json_format(temp_db, monkeypatch, capsys) -> None:
    settings = Settings(
        nesty_db_path=temp_db,
        provider_health_ttl_seconds=900,
        provider_reliability_scoring_enabled=True,
        provider_reliability_min_checks=2,
    )
    monkeypatch.setattr("app.deps.get_settings", lambda: settings)
    monkeypatch.setattr("scripts.provider_health_summary.get_settings", lambda: settings)

    record_provider_health_check(
        provider="groq",
        model="llama-3.1-8b-instant",
        status="ok",
        model_alias="nesty-flash-1.0",
        role="main",
        latency_ms=120,
        db_path=temp_db,
    )
    record_provider_health_check(
        provider="groq",
        model="llama-3.1-8b-instant",
        status="ok",
        model_alias="nesty-flash-1.0",
        role="main",
        latency_ms=140,
        db_path=temp_db,
    )

    args = argparse.Namespace(
        limit=10,
        provider=None,
        model_alias=None,
        since_seconds=None,
        only_unhealthy=False,
        json=True,  # JSON output
        show_reliability=True,
        window_checks=None,
        min_checks=None,
    )
    
    code = provider_health_summary._run(args)
    assert code == 0
    
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["ok"] is True
    assert "reliability" in payload
    assert len(payload["reliability"]) == 1
    assert payload["reliability"][0]["reliability_score"] == 1.0


def test_script_empty_db_friendly_message(tmp_path, monkeypatch, capsys) -> None:
    db_file = tmp_path / "nonexistent.db"
    settings = Settings(
        nesty_db_path=str(db_file),
        provider_health_ttl_seconds=900,
        provider_reliability_scoring_enabled=True,
    )
    monkeypatch.setattr("app.deps.get_settings", lambda: settings)
    monkeypatch.setattr("scripts.provider_health_summary.get_settings", lambda: settings)

    args = argparse.Namespace(
        limit=10,
        provider=None,
        model_alias=None,
        since_seconds=None,
        only_unhealthy=False,
        json=False,
        show_reliability=True,
        window_checks=None,
        min_checks=None,
    )
    
    # Should not crash on uninitialized DB and print friendly message
    code = provider_health_summary._run(args)
    assert code == 0
    
    out = capsys.readouterr().out
    assert "No provider health check records found." in out
