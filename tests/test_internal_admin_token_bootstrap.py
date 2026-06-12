from __future__ import annotations

import os

import pytest

from app.config import Settings
from app.core.bootstrap.bootstrap_credentials import resolve_bootstrap_credentials
from app.core.bootstrap.internal_admin_token import resolve_internal_admin_token
from app.security.secret_compare import secrets_equal


def test_env_admin_token_wins_over_file_mode(tmp_path, monkeypatch) -> None:
    token_file = tmp_path / "admin.token"
    token_file.write_text("nia_file_token_should_not_be_used", encoding="utf-8")
    monkeypatch.setenv("NESTY_INTERNAL_ADMIN_TOKEN", "nia_env_token_value_123456")
    monkeypatch.delenv("NESTY_INTERNAL_ADMIN_TOKEN_MODE", raising=False)
    settings = Settings(
        internal_admin_enabled=True,
        nesty_internal_admin_token_mode="file",
        internal_admin_token_file=str(token_file),
    )
    result = resolve_internal_admin_token(settings)
    assert result.token == "nia_env_token_value_123456"
    assert result.source == "env"


def test_file_admin_token_generated_when_enabled_and_missing_env(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("NESTY_INTERNAL_ADMIN_TOKEN", raising=False)
    token_file = tmp_path / "admin.token"
    settings = Settings(
        internal_admin_enabled=True,
        nesty_internal_admin_token_mode="file",
        internal_admin_token_file=str(token_file),
        nesty_print_bootstrap_admin_token=False,
    )
    first = resolve_internal_admin_token(settings)
    assert first.token is not None
    assert first.token.startswith("nia_")
    assert first.generated is True
    assert token_file.is_file()

    second = resolve_internal_admin_token(settings)
    assert second.token == first.token
    assert second.generated is False


def test_ephemeral_admin_token_changes_between_generations(monkeypatch) -> None:
    monkeypatch.delenv("NESTY_INTERNAL_ADMIN_TOKEN", raising=False)
    settings = Settings(
        internal_admin_enabled=True,
        nesty_internal_admin_token_mode="ephemeral",
    )
    first = resolve_internal_admin_token(settings)
    second = resolve_internal_admin_token(settings)
    assert first.token is not None
    assert second.token is not None
    assert first.token != second.token


def test_admin_bootstrap_skipped_when_internal_admin_disabled(monkeypatch) -> None:
    monkeypatch.delenv("NESTY_INTERNAL_ADMIN_TOKEN", raising=False)
    settings = Settings(
        internal_admin_enabled=False,
        nesty_internal_admin_token_mode="file",
    )
    result = resolve_internal_admin_token(settings)
    assert result.token is None
    assert result.source == "disabled"


def test_resolve_bootstrap_credentials_updates_settings(monkeypatch) -> None:
    monkeypatch.delenv("NESTY_INTERNAL_ADMIN_TOKEN", raising=False)
    settings = Settings(
        internal_admin_enabled=True,
        nesty_internal_admin_token_mode="ephemeral",
        nesty_console_client_auth_required=False,
    )
    resolved = resolve_bootstrap_credentials(settings)
    assert resolved.nesty_internal_admin_token is not None
    assert resolved.internal_admin_token_source == "ephemeral"


def test_secrets_equal_uses_constant_time_path() -> None:
    assert secrets_equal("abc", "abc") is True
    assert secrets_equal("abc", "abd") is False
    assert secrets_equal("abc", "abcd") is False
