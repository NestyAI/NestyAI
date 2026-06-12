from __future__ import annotations

from app.config import Settings
from app.core.provider_credentials.backends.sqlite_file import SQLiteFileCredentialBackend
from app.core.provider_credentials.resolver import (
    credentials_feature_enabled,
    parse_source_priority,
    resolve_builtin_provider_api_key,
)
from app.core.provider_credentials.secrets import read_builtin_provider_secret, write_builtin_provider_secret
from app.core.provider_credentials.store import get_provider_credential
from app.storage.db import init_db


def _settings(tmp_path, **overrides) -> Settings:
    base = {
        "nesty_db_path": str(tmp_path / "nesty.db"),
        "nesty_provider_secret_dir": str(tmp_path / "provider_secrets"),
        "nesty_provider_credentials_enabled": False,
    }
    base.update(overrides)
    return Settings(**base)


def test_credentials_disabled_uses_env_only(tmp_path, monkeypatch) -> None:
    db_path = str(tmp_path / "creds.db")
    init_db(db_path)
    settings = _settings(tmp_path, groq_api_key="env-groq-key")
    monkeypatch.setenv("GROQ_API_KEY", "env-from-os")
    backend = SQLiteFileCredentialBackend(settings, db_path=db_path)
    backend.upsert_managed("groq", "managed-key")

    value, status = resolve_builtin_provider_api_key("groq", settings, db_path=db_path)
    assert value == "env-groq-key"
    assert status == "env_ref"
    assert credentials_feature_enabled(settings) is False


def test_credentials_enabled_managed_priority(tmp_path) -> None:
    db_path = str(tmp_path / "creds.db")
    init_db(db_path)
    settings = _settings(
        tmp_path,
        nesty_provider_credentials_enabled=True,
        groq_api_key="env-groq-key",
    )
    backend = SQLiteFileCredentialBackend(settings, db_path=db_path)
    backend.upsert_managed("groq", "managed-key")

    value, status = resolve_builtin_provider_api_key("groq", settings, db_path=db_path)
    assert value == "managed-key"
    assert status == "managed"


def test_credentials_enabled_secret_file_before_env(tmp_path, monkeypatch) -> None:
    db_path = str(tmp_path / "creds.db")
    init_db(db_path)
    settings = _settings(
        tmp_path,
        nesty_provider_credentials_enabled=True,
        nesty_provider_credential_source_priority="secret_file,env",
        groq_api_key=None,
    )
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    write_builtin_provider_secret(settings, "groq", "file-key")

    value, status = resolve_builtin_provider_api_key("groq", settings, db_path=db_path)
    assert value == "file-key"
    assert status == "stored"


def test_credentials_enabled_falls_back_to_env(tmp_path, monkeypatch) -> None:
    db_path = str(tmp_path / "creds.db")
    init_db(db_path)
    settings = _settings(
        tmp_path,
        nesty_provider_credentials_enabled=True,
        groq_api_key=None,
    )
    monkeypatch.setenv("GROQ_API_KEY", "env-only-key")

    value, status = resolve_builtin_provider_api_key("groq", settings, db_path=db_path)
    assert value == "env-only-key"
    assert status == "env_ref"


def test_managed_store_never_puts_raw_key_in_sqlite(tmp_path) -> None:
    db_path = str(tmp_path / "creds.db")
    init_db(db_path)
    settings = _settings(tmp_path, nesty_provider_credentials_enabled=True)
    backend = SQLiteFileCredentialBackend(settings, db_path=db_path)
    backend.upsert_managed("openai", "sk-test-secret-value")

    record = get_provider_credential("openai", db_path=db_path, settings=settings)
    assert record is not None
    assert record.secret_ref == "builtin/openai.secret"
    assert "sk-test" not in str(record.to_safe_dict())

    stored = read_builtin_provider_secret(settings, "openai", record.secret_ref)
    assert stored == "sk-test-secret-value"


def test_parse_source_priority_normalizes_managed_store_alias() -> None:
    assert parse_source_priority("managed_store,env,secret_file") == ["managed", "env", "secret_file"]


def test_missing_credential_returns_missing_status(tmp_path, monkeypatch) -> None:
    db_path = str(tmp_path / "creds.db")
    init_db(db_path)
    settings = _settings(tmp_path, nesty_provider_credentials_enabled=True, groq_api_key=None)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    value, status = resolve_builtin_provider_api_key("groq", settings, db_path=db_path)
    assert value is None
    assert status == "missing"
