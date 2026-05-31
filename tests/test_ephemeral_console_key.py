from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.core.ephemeral_console_key import (
    get_ephemeral_console_key_config_from_env,
    rotate_ephemeral_console_api_key_from_env,
)
from app.security.api_key import generate_api_key, hash_api_key, verify_api_key
from app.storage.api_keys import create_api_key_record, get_api_key_by_hash
from app.storage.db import get_connection, init_db


def _set_base_env(monkeypatch) -> None:
    monkeypatch.setenv("NESTY_EPHEMERAL_CONSOLE_KEY_NAME", "nesty-console-ephemeral")
    monkeypatch.setenv("NESTY_EPHEMERAL_CONSOLE_KEY_ENV", "prod")
    monkeypatch.setenv("NESTY_EPHEMERAL_CONSOLE_KEY_DAILY_LIMIT", "10000")
    monkeypatch.setenv("NESTY_EPHEMERAL_CONSOLE_KEY_MONTHLY_LIMIT", "")
    monkeypatch.setenv(
        "NESTY_EPHEMERAL_CONSOLE_KEY_MODELS",
        "nesty-flash-1.0,nesty-combined-1.0,nesty-pro-1.0",
    )
    monkeypatch.setenv("NESTY_EPHEMERAL_CONSOLE_KEY_PREFIX", "nsk_console")


def _count_active_ephemeral(db_path: str, *, name: str = "nesty-console-ephemeral", env: str = "prod") -> int:
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM api_keys
            WHERE is_active = 1
              AND name = ?
              AND environment = ?
              AND key_prefix LIKE 'nsk_console%'
            """,
            (name, env),
        ).fetchone()
    return int(row["c"])


def _get_raw_key_from_output(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("nsk_console_"):
            return stripped
    return ""


def test_feature_disabled_does_nothing(monkeypatch, tmp_path: Path, capsys) -> None:
    db_path = str(tmp_path / "ephemeral_disabled.db")
    init_db(db_path)
    _set_base_env(monkeypatch)
    monkeypatch.setenv("NESTY_EPHEMERAL_CONSOLE_KEY_ENABLED", "false")
    settings = Settings(nesty_db_path=db_path, nesty_api_key_hash_secret="secret123")

    result = rotate_ephemeral_console_api_key_from_env(settings=settings)
    captured = capsys.readouterr()

    assert result["enabled"] is False
    assert result["rotated"] is False
    assert captured.out.strip() == ""
    assert _count_active_ephemeral(db_path) == 0


def test_enabled_generates_new_api_key_record_and_prefix(monkeypatch, tmp_path: Path, capsys) -> None:
    db_path = str(tmp_path / "ephemeral_enabled.db")
    init_db(db_path)
    _set_base_env(monkeypatch)
    monkeypatch.setenv("NESTY_EPHEMERAL_CONSOLE_KEY_ENABLED", "true")
    settings = Settings(nesty_db_path=db_path, nesty_api_key_hash_secret="secret123")

    result = rotate_ephemeral_console_api_key_from_env(settings=settings)
    captured = capsys.readouterr()
    raw_key = _get_raw_key_from_output(captured.out)

    assert result["enabled"] is True
    assert result["rotated"] is True
    assert result["created_id"] is not None
    assert raw_key.startswith("nsk_console_")
    assert captured.out.count(raw_key) == 1
    assert captured.out.count("EPHEMERAL NESTY CONSOLE API KEY") == 1
    assert "sha256:" not in captured.out
    assert "hmac_sha256:" not in captured.out

    key_hash = hash_api_key(raw_key, hash_secret="secret123")
    stored = get_api_key_by_hash(db_path, key_hash)
    assert stored is not None
    assert stored["is_active"] is True
    assert stored["key_hash"] != raw_key
    assert verify_api_key(raw_key, stored["key_hash"], hash_secret="secret123") is True
    assert stored["daily_limit"] == 10000
    assert stored["monthly_limit"] is None
    assert stored["allowed_models"] == ["nesty-flash-1.0", "nesty-combined-1.0", "nesty-pro-1.0"]


def test_second_rotation_revokes_previous_ephemeral_key_only(monkeypatch, tmp_path: Path, capsys) -> None:
    db_path = str(tmp_path / "ephemeral_rotate.db")
    init_db(db_path)
    _set_base_env(monkeypatch)
    monkeypatch.setenv("NESTY_EPHEMERAL_CONSOLE_KEY_ENABLED", "1")
    settings = Settings(nesty_db_path=db_path, nesty_api_key_hash_secret="secret123")

    persistent_raw = generate_api_key("dev")
    persistent = create_api_key_record(
        db_path=db_path,
        name="persistent-user",
        raw_key=persistent_raw,
        environment="dev",
        hash_secret="secret123",
    )

    first = rotate_ephemeral_console_api_key_from_env(settings=settings)
    first_out = capsys.readouterr().out
    first_raw = _get_raw_key_from_output(first_out)

    second = rotate_ephemeral_console_api_key_from_env(settings=settings)
    second_out = capsys.readouterr().out
    second_raw = _get_raw_key_from_output(second_out)

    assert first["rotated"] is True
    assert second["rotated"] is True
    assert second["revoked_count"] >= 1
    assert first_raw
    assert second_raw
    assert first_raw != second_raw

    first_hash = hash_api_key(first_raw, hash_secret="secret123")
    second_hash = hash_api_key(second_raw, hash_secret="secret123")

    first_record = get_api_key_by_hash(db_path, first_hash)
    second_record = get_api_key_by_hash(db_path, second_hash)
    assert first_record is not None
    assert second_record is not None
    assert first_record["is_active"] is False
    assert second_record["is_active"] is True
    assert _count_active_ephemeral(db_path) == 1

    with get_connection(db_path) as conn:
        persistent_row = conn.execute(
            "SELECT is_active FROM api_keys WHERE id = ?",
            (persistent["id"],),
        ).fetchone()
    assert persistent_row is not None
    assert int(persistent_row["is_active"]) == 1


def test_model_and_limit_parsing(monkeypatch, tmp_path: Path) -> None:
    db_path = str(tmp_path / "ephemeral_parsing.db")
    _set_base_env(monkeypatch)
    monkeypatch.setenv("NESTY_EPHEMERAL_CONSOLE_KEY_ENABLED", "yes")
    monkeypatch.setenv("NESTY_EPHEMERAL_CONSOLE_KEY_MODELS", " model-a , ,model-b,model-c ")
    monkeypatch.setenv("NESTY_EPHEMERAL_CONSOLE_KEY_DAILY_LIMIT", "abc")
    monkeypatch.setenv("NESTY_EPHEMERAL_CONSOLE_KEY_MONTHLY_LIMIT", "  ")
    settings = Settings(nesty_db_path=db_path, nesty_api_key_hash_secret="secret123")

    cfg = get_ephemeral_console_key_config_from_env(settings=settings)
    assert cfg.enabled is True
    assert cfg.allowed_models == ["model-a", "model-b", "model-c"]
    assert cfg.daily_limit == 10000
    assert cfg.monthly_limit is None


def test_monthly_limit_valid_and_daily_fallback_non_positive(monkeypatch, tmp_path: Path) -> None:
    db_path = str(tmp_path / "ephemeral_limits.db")
    _set_base_env(monkeypatch)
    monkeypatch.setenv("NESTY_EPHEMERAL_CONSOLE_KEY_ENABLED", "on")
    monkeypatch.setenv("NESTY_EPHEMERAL_CONSOLE_KEY_DAILY_LIMIT", "0")
    monkeypatch.setenv("NESTY_EPHEMERAL_CONSOLE_KEY_MONTHLY_LIMIT", "250000")
    settings = Settings(nesty_db_path=db_path, nesty_api_key_hash_secret="secret123")

    cfg = get_ephemeral_console_key_config_from_env(settings=settings)
    assert cfg.daily_limit == 10000
    assert cfg.monthly_limit == 250000


def test_storage_failure_logs_safe_error_without_printing_raw_key(monkeypatch, tmp_path: Path, capsys) -> None:
    db_path = str(tmp_path / "ephemeral_failure.db")
    init_db(db_path)
    _set_base_env(monkeypatch)
    monkeypatch.setenv("NESTY_EPHEMERAL_CONSOLE_KEY_ENABLED", "true")
    settings = Settings(nesty_db_path=db_path, nesty_api_key_hash_secret="secret123")

    from app.core import ephemeral_console_key as feature

    monkeypatch.setattr(
        feature,
        "create_api_key_record",
        lambda **_: (_ for _ in ()).throw(RuntimeError("db write failed")),
    )

    result = feature.rotate_ephemeral_console_api_key_from_env(settings=settings)
    captured = capsys.readouterr()

    assert result["enabled"] is True
    assert result["rotated"] is False
    assert result["error"] == "create_failed"
    assert "EPHEMERAL NESTY CONSOLE API KEY" not in captured.out
    assert "nsk_console_" not in captured.out
    assert _count_active_ephemeral(db_path) == 0
