from __future__ import annotations

from fastapi import Request

from app.core.errors import APIError
from app.security.internal_auth import require_internal_admin


def _request_with_auth(value: str | None) -> Request:
    headers = []
    if value is not None:
        headers.append((b"authorization", value.encode("utf-8")))
    scope = {"type": "http", "headers": headers}
    return Request(scope)


def test_internal_admin_disabled_returns_404(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.security.internal_auth.get_settings",
        lambda: type("S", (), {"internal_admin_enabled": False, "nesty_internal_admin_token": "abc"})(),
    )
    try:
        require_internal_admin(_request_with_auth("Bearer abc"))
        assert False, "expected APIError"
    except APIError as exc:
        assert exc.status_code == 404
        assert exc.code == "internal_admin_disabled"


def test_internal_admin_enabled_missing_token_returns_401(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.security.internal_auth.get_settings",
        lambda: type("S", (), {"internal_admin_enabled": True, "nesty_internal_admin_token": "abc"})(),
    )
    try:
        require_internal_admin(_request_with_auth(None))
        assert False, "expected APIError"
    except APIError as exc:
        assert exc.status_code == 401
        assert exc.code == "internal_admin_unauthorized"


def test_internal_admin_enabled_valid_token_passes(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.security.internal_auth.get_settings",
        lambda: type("S", (), {"internal_admin_enabled": True, "nesty_internal_admin_token": "abc"})(),
    )
    require_internal_admin(_request_with_auth("Bearer abc"))
