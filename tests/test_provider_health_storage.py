from __future__ import annotations

from app.storage.db import get_connection, init_db
from app.storage.provider_health import (
    delete_provider_health_checks,
    get_latest_provider_health,
    list_provider_health_checks,
    record_provider_health_check,
    summarize_provider_health,
)


def test_provider_health_table_initializes(tmp_path) -> None:
    db_path = str(tmp_path / "provider_health_init.db")
    init_db(db_path)
    with get_connection(db_path) as conn:
        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(provider_health_checks)").fetchall()}
    assert "provider" in columns
    assert "model" in columns
    assert "status" in columns
    assert "checked_at" in columns


def test_provider_health_record_list_latest_summarize(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "provider_health_ops.db")
    init_db(db_path)
    monkeypatch.setattr("app.storage.provider_health.get_settings", lambda: type("S", (), {"nesty_db_path": db_path})())

    _ = record_provider_health_check(
        provider="openrouter",
        model="deepseek/deepseek-v4-flash:free",
        model_alias="nesty-combined-1.0",
        role="main",
        status="ok",
        latency_ms=120,
        output_chars=2,
        tokens_per_second=8.0,
        metadata={"output_preview": "OK"},
    )
    _ = record_provider_health_check(
        provider="openrouter",
        model="deepseek/deepseek-v4-flash:free",
        model_alias="nesty-combined-1.0",
        role="main",
        status="failed",
        error_code="provider_unavailable",
        latency_ms=300,
        output_chars=0,
        metadata={"output_preview": ""},
    )
    _ = record_provider_health_check(
        provider="groq",
        model="llama-3.1-8b-instant",
        model_alias="nesty-flash-1.0",
        role="main",
        status="ok",
        latency_ms=80,
        output_chars=2,
        tokens_per_second=12.5,
        metadata={"output_preview": "OK"},
    )

    recent = list_provider_health_checks(limit=10)
    assert len(recent) == 3

    filtered = list_provider_health_checks(provider="openrouter", status="failed", limit=10)
    assert len(filtered) == 1
    assert filtered[0]["status"] == "failed"

    latest = get_latest_provider_health()
    assert latest
    assert any(item["provider"] == "openrouter" for item in latest)

    summary = summarize_provider_health()
    assert summary["total_checks"] == 3
    assert summary["status_counts"]["ok"] == 2
    assert summary["status_counts"]["failed"] == 1


def test_provider_health_cleanup_filters(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "provider_health_cleanup.db")
    init_db(db_path)
    monkeypatch.setattr("app.storage.provider_health.get_settings", lambda: type("S", (), {"nesty_db_path": db_path})())

    _ = record_provider_health_check(
        provider="openrouter",
        model="m1",
        model_alias="nesty-combined-1.0",
        role="main",
        status="failed",
        db_path=db_path,
    )
    _ = record_provider_health_check(
        provider="groq",
        model="m2",
        model_alias="nesty-flash-1.0",
        role="main",
        status="ok",
        db_path=db_path,
    )

    deleted = delete_provider_health_checks(provider="openrouter", db_path=db_path)
    assert deleted == 1
    remaining = list_provider_health_checks(limit=10, db_path=db_path)
    assert len(remaining) == 1
    assert remaining[0]["provider"] == "groq"
